package com.bullbear.api.experiment;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.DebateQuota;
import com.bullbear.api.debate.LlmUsage;
import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerEvent;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 실험 조건 B: 정식 운용 토론이 끝나면 같은 스냅샷으로 단일 판정을 한 번 받아 둔다 (계약 v0.6 단일 모드).
 *
 * - 사용자에게는 보이지 않는다. AI 성적표에서 토론 판정과 같은 결과로 채점해 비교한다.
 * - 전향 운용 하루 비용 상한을 같이 쓴다. 실제 종료 실패만 maxAttempts까지 새로 시도한다.
 * - 연결 오류·재시작은 저장한 요청키/worker_id로 다음 회차에 같은 실행을 이어 받는다.
 * - 판정 하나를 기다리는 데 몇십 초가 걸리므로 스케줄러 스레드를 막지 않게 전용 스레드에서 돈다.
 */
@Service
public class SingleVerdictRunner implements DisposableBean {

	private static final Logger log = LoggerFactory.getLogger(SingleVerdictRunner.class);
	private static final Duration TIMEOUT = Duration.ofMinutes(10);

	private record Pending(UUID debateId, String ticker, String snapshotId, int attempts, String status) {
	}

	private record Attempt(int number, String requestId, String workerId) { }

	private final JdbcClient jdbc;
	private final WorkerClient worker;
	private final DebateQuota quota;
	private final LlmUsage usage;
	private final ObjectMapper json;
	private final BullbearProperties.Experiment config;
	private final BigDecimal dailyUsd;
	private final Clock clock;
	private final TransactionTemplate tx;
	private final ExecutorService runner = Executors.newSingleThreadExecutor(r -> new Thread(r, "single-verdict"));
	private final AtomicBoolean running = new AtomicBoolean();

	SingleVerdictRunner(JdbcClient jdbc, WorkerClient worker, DebateQuota quota, LlmUsage usage, ObjectMapper json,
			BullbearProperties properties, Clock clock, PlatformTransactionManager transactions) {
		this.jdbc = jdbc;
		this.worker = worker;
		this.quota = quota;
		this.usage = usage;
		this.json = json;
		this.config = properties.experiment();
		this.dailyUsd = properties.forwardRun().dailyUsd();
		this.clock = clock;
		this.tx = new TransactionTemplate(transactions);
	}

	/** 전향 운용 토론은 몇 분에 걸쳐 끝나므로 주기적으로 살핀다 */
	@Scheduled(fixedDelayString = "${bullbear.experiment.poll-interval}", initialDelayString = "PT1M")
	public void scheduled() {
		if (!config.singleEnabled() || !running.compareAndSet(false, true)) {
			return;
		}
		runner.submit(() -> {
			try {
				runDue();
			} finally {
				running.set(false);
			}
		});
	}

	/** @return 이번에 판정을 받은 수 */
	public synchronized int runDue() {
		List<Pending> due = jdbc.sql("""
				select d.id, d.ticker, d.snapshot_id, coalesce(s.attempts, 0), s.status
				from debates d
				left join single_verdicts s on s.debate_id = d.id
				where d.origin = 'SCHEDULED' and d.status = 'COMPLETED' and d.snapshot_id is not null
				  and d.trade_date >= :start
				  and (s.debate_id is null or s.status = 'RUNNING' or (s.status = 'FAILED' and s.attempts < :max))
				order by (s.status = 'RUNNING') desc nulls last, d.created_at
				""")
				.param("start", config.start()).param("max", config.maxAttempts())
				.query((rs, i) -> new Pending(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), rs.getInt(4), rs.getString(5)))
				.list();
		int done = 0;
		for (Pending p : due) {
			// Re-subscription/replaying an existing idempotency key is not a new execution.
			if (!"RUNNING".equals(p.status()) && !quota.scheduledBudgetOpen(dailyUsd)) {
				log.warn("전향 운용 하루 비용 상한 도달 — 단일 판정 {}건 미룸", due.size() - done);
				break;
			}
			done += run(p) ? 1 : 0;
		}
		return done;
	}

	private boolean run(Pending p) {
		Attempt attempt;
		if ("RUNNING".equals(p.status())) {
			attempt = jdbc.sql("select attempt, request_id, worker_id from single_verdict_attempts where debate_id = :id and attempt = :a")
					.param("id", p.debateId()).param("a", p.attempts())
					.query((rs, i) -> new Attempt(rs.getInt(1), rs.getString(2), rs.getString(3))).single();
		} else {
			attempt = new Attempt(p.attempts() + 1, "single-" + p.debateId() + "-" + (p.attempts() + 1), null);
			tx.executeWithoutResult(status -> {
				jdbc.sql("""
				insert into single_verdicts (debate_id, status, attempts, run_day, created_at)
				values (:id, 'RUNNING', :a, :day, :t)
				on conflict (debate_id) do update set status = 'RUNNING', attempts = :a, error = null,
				    worker_id = null, cost_usd = null, run_day = :day
				""")
				.param("id", p.debateId()).param("a", attempt.number()).param("day", LocalDate.now(clock))
				.param("t", Timestamp.from(clock.instant())).update();
				jdbc.sql("""
					insert into single_verdict_attempts (debate_id, attempt, request_id, status, run_day, created_at)
					values (:id, :a, :r, 'RUNNING', :day, :t)
					""").param("id", p.debateId()).param("a", attempt.number()).param("r", attempt.requestId())
					.param("day", LocalDate.now(clock)).param("t", Timestamp.from(clock.instant())).update();
			});
		}
		try {
			String workerId = attempt.workerId();
			if (workerId == null) {
				var started = worker.startSingle(p.ticker(), p.snapshotId(), attempt.requestId());
				workerId = started.debateId();
				String savedId = workerId;
				tx.executeWithoutResult(status -> {
					jdbc.sql("update single_verdict_attempts set worker_id = :w where debate_id = :id and attempt = :a")
						.param("w", savedId).param("id", p.debateId()).param("a", attempt.number()).update();
					jdbc.sql("update single_verdicts set worker_id = :w where debate_id = :id")
						.param("w", savedId).param("id", p.debateId()).update();
				});
			}
			// Replay from zero is safe: only the terminal result is stored, atomically.
			WorkerEvent end = worker.events(workerId, 0).filter(WorkerEvent::isTerminal).next().block(TIMEOUT);
			if (end == null) {
				throw new IllegalStateException("종료 이벤트 없이 끝남");
			}
			JsonNode data = json.readTree(end.data());
			BigDecimal cost = usage.parse(data.get("usage")).map(LlmUsage.Usage::costUsd).orElse(null);
			if (!WorkerEvent.DEBATE_COMPLETED.equals(end.type())) {
				tx.executeWithoutResult(status -> {
					finishAttempt(p, attempt, "FAILED", cost);
					jdbc.sql("update single_verdicts set status = 'FAILED', error = :e, cost_usd = :c where debate_id = :id")
						.param("e", data.path("error").path("message").asString()).param("c", cost).param("id", p.debateId()).update();
				});
				return false;
			}
			JsonNode v = data.path("verdict");
			tx.executeWithoutResult(status -> {
				finishAttempt(p, attempt, "COMPLETED", cost);
				jdbc.sql("""
					update single_verdicts set status = 'COMPLETED', decision = :dec, confidence = :conf,
					    reasoning = :r, payload = cast(:p as jsonb), cost_usd = :c, completed_at = :t
					where debate_id = :id
					""")
					.param("dec", v.path("decision").asString()).param("conf", v.path("confidence").decimalValue())
					.param("r", v.path("reasoning").asString()).param("p", v.toString()).param("c", cost)
					.param("t", Timestamp.from(clock.instant())).param("id", p.debateId()).update();
			});
			return true;
		} catch (RuntimeException e) {
			// Transport uncertainty is not a terminal model failure. Keep the same
			// request/worker identity and the unknown-cost estimate for the next poll.
			log.warn("단일 판정 연결/저장 보류: debate={} type={}", p.debateId(), e.getClass().getSimpleName());
			return false;
		}
	}

	private void finishAttempt(Pending p, Attempt attempt, String status, BigDecimal cost) {
		jdbc.sql("""
			update single_verdict_attempts set status = :s, cost_usd = :c, completed_at = :t
			where debate_id = :id and attempt = :a
			""").param("s", status).param("c", cost).param("t", Timestamp.from(clock.instant()))
			.param("id", p.debateId()).param("a", attempt.number()).update();
	}

	@Override
	public void destroy() {
		runner.shutdownNow();
	}
}

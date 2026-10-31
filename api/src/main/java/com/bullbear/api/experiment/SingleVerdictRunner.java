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
 * - 전향 운용 하루 비용 상한을 같이 쓴다. 실패하면 maxAttempts까지 다음 회차에 다시 시도한다.
 * - 판정 하나를 기다리는 데 몇십 초가 걸리므로 스케줄러 스레드를 막지 않게 전용 스레드에서 돈다.
 */
@Service
public class SingleVerdictRunner implements DisposableBean {

	private static final Logger log = LoggerFactory.getLogger(SingleVerdictRunner.class);
	private static final Duration TIMEOUT = Duration.ofMinutes(10);

	private record Pending(UUID debateId, String ticker, String snapshotId, int attempts) {
	}

	private final JdbcClient jdbc;
	private final WorkerClient worker;
	private final DebateQuota quota;
	private final LlmUsage usage;
	private final ObjectMapper json;
	private final BullbearProperties.Experiment config;
	private final BigDecimal dailyUsd;
	private final Clock clock;
	private final ExecutorService runner = Executors.newSingleThreadExecutor(r -> new Thread(r, "single-verdict"));
	private final AtomicBoolean running = new AtomicBoolean();

	SingleVerdictRunner(JdbcClient jdbc, WorkerClient worker, DebateQuota quota, LlmUsage usage, ObjectMapper json,
			BullbearProperties properties, Clock clock) {
		this.jdbc = jdbc;
		this.worker = worker;
		this.quota = quota;
		this.usage = usage;
		this.json = json;
		this.config = properties.experiment();
		this.dailyUsd = properties.forwardRun().dailyUsd();
		this.clock = clock;
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
	public int runDue() {
		List<Pending> due = jdbc.sql("""
				select d.id, d.ticker, d.snapshot_id, coalesce(s.attempts, 0)
				from debates d
				left join single_verdicts s on s.debate_id = d.id
				where d.origin = 'SCHEDULED' and d.status = 'COMPLETED' and d.snapshot_id is not null
				  and d.trade_date >= :start
				  and (s.debate_id is null or (s.status = 'FAILED' and s.attempts < :max))
				order by d.created_at
				""")
				.param("start", config.start()).param("max", config.maxAttempts())
				.query((rs, i) -> new Pending(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), rs.getInt(4)))
				.list();
		int done = 0;
		for (Pending p : due) {
			if (!quota.scheduledBudgetOpen(dailyUsd)) {
				log.warn("전향 운용 하루 비용 상한 도달 — 단일 판정 {}건 미룸", due.size() - done);
				break;
			}
			done += run(p) ? 1 : 0;
		}
		return done;
	}

	private boolean run(Pending p) {
		int attempt = p.attempts() + 1;
		jdbc.sql("""
				insert into single_verdicts (debate_id, status, attempts, run_day, created_at)
				values (:id, 'RUNNING', :a, :day, :t)
				on conflict (debate_id) do update set status = 'RUNNING', attempts = :a, error = null, run_day = :day
				""")
				.param("id", p.debateId()).param("a", attempt).param("day", LocalDate.now(clock))
				.param("t", Timestamp.from(clock.instant())).update();
		try {
			// 재시도는 새 요청이어야 워커가 실패한 판정을 재사용하지 않는다
			var started = worker.startSingle(p.ticker(), p.snapshotId(), "single-" + p.debateId() + "-" + attempt);
			jdbc.sql("update single_verdicts set worker_id = :w where debate_id = :id")
					.param("w", started.debateId()).param("id", p.debateId()).update();
			WorkerEvent end = worker.events(started.debateId(), 0).filter(WorkerEvent::isTerminal).blockLast(TIMEOUT);
			if (end == null) {
				return fail(p, "종료 이벤트 없이 끝남", null);
			}
			JsonNode data = json.readTree(end.data());
			BigDecimal cost = usage.parse(data.get("usage")).map(LlmUsage.Usage::costUsd).orElse(null);
			if (!WorkerEvent.DEBATE_COMPLETED.equals(end.type())) {
				return fail(p, data.path("error").path("message").asString(), cost);
			}
			JsonNode v = data.path("verdict");
			jdbc.sql("""
					update single_verdicts set status = 'COMPLETED', decision = :dec, confidence = :conf,
					    reasoning = :r, payload = cast(:p as jsonb), cost_usd = :c, completed_at = :t
					where debate_id = :id
					""")
					.param("dec", v.path("decision").asString()).param("conf", v.path("confidence").decimalValue())
					.param("r", v.path("reasoning").asString()).param("p", v.toString()).param("c", cost)
					.param("t", Timestamp.from(clock.instant())).param("id", p.debateId()).update();
			return true;
		} catch (RuntimeException e) {
			return fail(p, e.getMessage(), null);
		}
	}

	private boolean fail(Pending p, String error, BigDecimal cost) {
		log.warn("단일 판정 실패: debate={} {}", p.debateId(), error);
		jdbc.sql("update single_verdicts set status = 'FAILED', error = :e, cost_usd = :c where debate_id = :id")
				.param("e", error).param("c", cost).param("id", p.debateId()).update();
		return false;
	}

	@Override
	public void destroy() {
		runner.shutdownNow();
	}
}

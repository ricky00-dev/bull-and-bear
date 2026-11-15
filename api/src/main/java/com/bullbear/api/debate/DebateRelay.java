package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDate;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerEvent;

import reactor.core.publisher.Flux;
import reactor.core.scheduler.Schedulers;
import reactor.util.retry.Retry;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 워커 이벤트를 구독해 DB에 쌓고 브라우저로 중계한다.
 *
 * - 끊기면 마지막으로 저장한 seq부터 다시 구독한다 (최대 5회, 지수 백오프).
 * - 같은 seq가 다시 와도 한 번만 저장한다.
 * - 서버가 재시작되면 진행 중이던 토론의 구독을 이어간다.
 */
@Component
public class DebateRelay {

	private static final Logger log = LoggerFactory.getLogger(DebateRelay.class);

	private final Set<UUID> active = ConcurrentHashMap.newKeySet();
	private final WorkerClient worker;
	private final DebateRepository debates;
	private final DebateEventRepository events;
	private final ModeratorVerdictRepository verdicts;
	private final DebateStreamHub hub;
	private final TransactionTemplate tx;
	private final ObjectMapper json;
	private final LlmUsage usage;

	DebateRelay(WorkerClient worker, DebateRepository debates, DebateEventRepository events,
			ModeratorVerdictRepository verdicts, DebateStreamHub hub, TransactionTemplate tx, ObjectMapper json,
			LlmUsage usage) {
		this.usage = usage;
		this.worker = worker;
		this.debates = debates;
		this.events = events;
		this.verdicts = verdicts;
		this.hub = hub;
		this.tx = tx;
		this.json = json;
	}

	@EventListener(ApplicationReadyEvent.class)
	void resumeRunning() {
		for (Debate d : debates.findByStatus(Debate.Status.RUNNING)) {
			if (d.getWorkerDebateId() != null) {
				log.info("진행 중 토론 구독 재개: {}", d.getId());
				start(d.getId());
			}
		}
	}

	public void start(UUID debateId) {
		if (!active.add(debateId)) {
			return;
		}
		Flux.defer(() -> {
					Debate d = debates.findById(debateId).orElseThrow();
					return worker.events(d.getWorkerDebateId(), d.getLastEventSeq());
				})
				.subscribeOn(Schedulers.boundedElastic())
				.publishOn(Schedulers.boundedElastic())
				.doOnNext(e -> handle(debateId, e))
				.takeUntil(WorkerEvent::isTerminal)
				.retryWhen(Retry.backoff(5, Duration.ofSeconds(1)))
				.doFinally(signal -> active.remove(debateId))
				.subscribe(e -> {
				}, err -> fail(debateId, err));
	}

	private void handle(UUID debateId, WorkerEvent e) {
		Boolean stored = tx.execute(status -> {
			if (events.existsByDebateIdAndSeq(debateId, e.seq())) {
				return false;
			}
			Debate d = debates.findById(debateId).orElseThrow();
			events.save(new DebateEvent(debateId, e.seq(), e.type(), e.data()));
			d.advanceTo(e.seq());
			switch (e.type()) {
				case WorkerEvent.SNAPSHOT_CREATED -> {
					JsonNode n = json.readTree(e.data());
					d.recordSnapshot(n.path("snapshot_id").asString(), LocalDate.parse(n.path("as_of").asString()),
							n.path("close").decimalValue());
				}
				case WorkerEvent.DEBATE_COMPLETED -> {
					JsonNode v = json.readTree(e.data()).path("verdict");
					verdicts.save(new ModeratorVerdict(debateId, v.path("decision").asString(),
							BigDecimal.valueOf(v.path("confidence").asDouble()), v.path("reasoning").asString(),
							json.writeValueAsString(v)));
					recordUsage(d, e.data());
					d.finish(Debate.Status.COMPLETED);
				}
				case WorkerEvent.DEBATE_FAILED -> {
					recordUsage(d, e.data());
					d.finish(Debate.Status.FAILED);
				}
				default -> {
				}
			}
			return true;
		});
		if (Boolean.TRUE.equals(stored)) {
			hub.publish(debateId, ClientEvent.from(e.seq(), e.type(), e.data()), e.isTerminal());
		}
	}

	private void recordUsage(Debate d, String data) {
		usage.parse(json.readTree(data).get("usage")).ifPresent(u -> {
			d.recordUsage(u.inputTokens(), u.outputTokens(), u.costUsd());
			log.info("토론 {} {} 사용량: 입력 {} 출력 {} 토큰, ${}", d.getId(), d.getTicker(), u.inputTokens(),
					u.outputTokens(), u.costUsd());
		});
	}

	/** 재시도까지 실패하면 토론을 실패로 닫고 브라우저에 알린다. 알림은 커밋 뒤에 보낸다. */
	private void fail(UUID debateId, Throwable err) {
		log.warn("토론 중계 실패: {}", debateId, err);
		ClientEvent failed = tx.execute(status -> {
			Debate d = debates.findById(debateId).orElseThrow();
			if (d.getStatus().isTerminal()) {
				return null;
			}
			long next = d.getLastEventSeq() + 1;
			String payload = json.writeValueAsString(Map.of("error",
					Map.of("code", "WORKER_UNAVAILABLE", "message", "토론을 이어갈 수 없어요. 잠시 후 다시 시도해 주세요.")));
			events.save(new DebateEvent(debateId, next, WorkerEvent.DEBATE_FAILED, payload));
			d.advanceTo(next);
			d.finish(Debate.Status.FAILED);
			return new ClientEvent(next, WorkerEvent.DEBATE_FAILED, payload);
		});
		if (failed != null) {
			hub.publish(debateId, failed, true);
		}
	}
}

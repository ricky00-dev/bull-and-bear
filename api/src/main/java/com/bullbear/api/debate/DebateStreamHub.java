package com.bullbear.api.debate;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 브라우저 SSE 연결 관리.
 *
 * 연결 시 DB에 쌓인 이벤트를 먼저 재생하고, 이후 라이브 이벤트를 이어서 보낸다.
 * 재생과 라이브 전송은 구독자 단위로 동기화하고 seq로 중복을 걸러서,
 * 그 사이에 들어온 이벤트가 빠지거나 두 번 가지 않게 한다.
 */
@Component
public class DebateStreamHub {

	private static final Duration TIMEOUT = Duration.ofMinutes(10);

	private final Map<UUID, Set<Subscriber>> subscribers = new ConcurrentHashMap<>();
	private final DebateEventRepository events;
	private final DebateRepository debates;

	DebateStreamHub(DebateEventRepository events, DebateRepository debates) {
		this.events = events;
		this.debates = debates;
	}

	public SseEmitter subscribe(UUID debateId, long afterSeq) {
		SseEmitter emitter = new SseEmitter(TIMEOUT.toMillis());
		Subscriber s = new Subscriber(emitter, afterSeq);
		Set<Subscriber> set = subscribers.computeIfAbsent(debateId, k -> ConcurrentHashMap.newKeySet());
		Runnable remove = () -> set.remove(s);
		emitter.onCompletion(remove);
		emitter.onTimeout(remove);
		emitter.onError(e -> remove.run());

		synchronized (s) {
			// Publish must not overtake the initial replay and advance lastSent.
			set.add(s);
			for (DebateEvent e : events.findByDebateIdAndSeqGreaterThanOrderBySeq(debateId, afterSeq)) {
				s.send(ClientEvent.from(e));
			}
			if (debates.findById(debateId).map(d -> d.getStatus().isTerminal()).orElse(true)) {
				// Completion can commit after the first query. Drain its committed
				// events before closing; a waiting publish is deduplicated by seq.
				for (DebateEvent e : events.findByDebateIdAndSeqGreaterThanOrderBySeq(debateId, s.lastSent)) {
					s.send(ClientEvent.from(e));
				}
				s.complete();
			}
		}
		return emitter;
	}

	void publish(UUID debateId, ClientEvent event, boolean terminal) {
		for (Subscriber s : subscribers.getOrDefault(debateId, Set.of())) {
			synchronized (s) {
				s.send(event);
				if (terminal) {
					s.complete();
				}
			}
		}
	}

	private static final class Subscriber {
		private final SseEmitter emitter;
		private long lastSent;
		private boolean closed;

		Subscriber(SseEmitter emitter, long lastSent) {
			this.emitter = emitter;
			this.lastSent = lastSent;
		}

		void send(ClientEvent e) {
			if (closed || e.seq() <= lastSent) {
				return;
			}
			try {
				emitter.send(SseEmitter.event().id(Long.toString(e.seq())).name(e.type()).data(e.data()));
				lastSent = e.seq();
			} catch (IOException | IllegalStateException ex) {
				closed = true; // 브라우저가 떠남
			}
		}

		void complete() {
			if (!closed) {
				closed = true;
				emitter.complete();
			}
		}
	}
}

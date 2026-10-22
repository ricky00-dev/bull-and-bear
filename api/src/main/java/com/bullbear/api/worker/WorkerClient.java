package com.bullbear.api.worker;

import java.util.List;

import reactor.core.publisher.Flux;

/**
 * Python AI 워커 호출. 계약은 docs/worker-api.md.
 * bullbear.worker.mode = fake | http 로 구현체를 고른다.
 */
public interface WorkerClient {

	List<WorkerStock> search(String query, int limit);

	WorkerStockDetail stock(String ticker);

	WorkerDebateStarted startDebate(String ticker, String requestId);

	/** afterSeq보다 큰 이벤트부터. 완료된 토론이면 끝까지 재생하고 끝난다. */
	Flux<WorkerEvent> events(String workerDebateId, long afterSeq);
}

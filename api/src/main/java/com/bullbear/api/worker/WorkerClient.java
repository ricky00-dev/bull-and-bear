package com.bullbear.api.worker;

import java.time.LocalDate;
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

	/** 단일 모드(실험 조건 B, 계약 v0.6): 같은 스냅샷으로 모델 하나가 바로 판정. 이벤트는 events()로 받는다 */
	WorkerDebateStarted startSingle(String ticker, String snapshotId, String requestId);

	/** [from, to] 구간 종목 일별 종가, 날짜 오름차순. 휴장일은 없다. */
	List<DailyClose> dailyCloses(String ticker, LocalDate from, LocalDate to);

	/** [from, to] 구간 지수 일별 종가. code: KOSPI | KOSDAQ */
	List<DailyClose> indexCloses(String code, LocalDate from, LocalDate to);

	/** afterSeq보다 큰 이벤트부터. 완료된 토론이면 끝까지 재생하고 끝난다. */
	Flux<WorkerEvent> events(String workerDebateId, long afterSeq);
}

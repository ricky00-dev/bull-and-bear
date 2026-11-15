package com.bullbear.api.worker;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;

import reactor.core.publisher.Flux;

/**
 * Python AI 워커 호출. 계약은 docs/worker-api.md.
 * bullbear.worker.mode = fake | http 로 구현체를 고른다.
 */
public interface WorkerClient {

	List<WorkerStock> search(String query, int limit);

	default WorkerStockDetail stock(String ticker) {
		return stock(ticker, null);
	}

	/** @param asOf 백테스트(계약 v0.7): 이 날짜 이전 마지막 거래일 기준. null이면 최신 종가 기준 */
	WorkerStockDetail stock(String ticker, LocalDate asOf);

	/**
	 * 워커는 종목 시세를 처음 계산하는 동안 503(준비 중)을 준다. 계산은 워커에서 이어지므로 잠시 뒤 다시 물으면 된다.
	 * 스케줄러·백테스트처럼 기다려도 되는 곳에서 쓴다. 사용자 요청은 웹이 다시 시도한다.
	 */
	default WorkerStockDetail stockWhenReady(String ticker, LocalDate asOf, int attempts, Duration delay) {
		for (int i = 1;; i++) {
			try {
				return stock(ticker, asOf);
			} catch (ApiException e) {
				if (e.code() != ErrorCode.WORKER_UNAVAILABLE || i >= attempts) {
					throw e;
				}
			}
			try {
				Thread.sleep(delay.toMillis());
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				throw new ApiException(ErrorCode.WORKER_UNAVAILABLE, "시세를 기다리다 중단됐습니다");
			}
		}
	}

	default WorkerDebateStarted startDebate(String ticker, String requestId) {
		return startDebate(ticker, requestId, null);
	}

	/** @param asOf 백테스트(계약 v0.7): 이 날짜까지의 데이터만으로 토론. null이면 최신 종가 기준 */
	WorkerDebateStarted startDebate(String ticker, String requestId, LocalDate asOf);

	/** 단일 모드(실험 조건 B, 계약 v0.6): 같은 스냅샷으로 모델 하나가 바로 판정. 이벤트는 events()로 받는다 */
	WorkerDebateStarted startSingle(String ticker, String snapshotId, String requestId);

	/** [from, to] 구간 종목 일별 종가, 날짜 오름차순. 휴장일은 없다. */
	List<DailyClose> dailyCloses(String ticker, LocalDate from, LocalDate to);

	/** [from, to] 구간 지수 일별 종가. code: KOSPI | KOSDAQ */
	List<DailyClose> indexCloses(String code, LocalDate from, LocalDate to);

	/** afterSeq보다 큰 이벤트부터. 완료된 토론이면 끝까지 재생하고 끝난다. */
	Flux<WorkerEvent> events(String workerDebateId, long afterSeq);
}

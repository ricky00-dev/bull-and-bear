package com.bullbear.api.worker;

import java.time.LocalDate;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 종목 확인 화면용.
 *
 * @param sparkline 최근 60거래일 종가, 오래된 순
 * @param reasons 토론 불가 사유. 토론 가능하면 빈 목록
 */
public record WorkerStockDetail(
		String ticker,
		String name,
		String market,
		long close,
		@JsonProperty("change_pct") double changePct,
		@JsonProperty("as_of") LocalDate asOf,
		boolean eligible,
		List<String> reasons,
		List<Long> sparkline) {
}

package com.bullbear.api.worker;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 검색 결과 한 줄.
 *
 * @param blockReason 토론 불가 사유 (우선주, ETF 등). 토론 가능하면 null
 */
public record WorkerStock(
		String ticker,
		String name,
		String market,
		boolean featured,
		long close,
		@JsonProperty("change_pct") double changePct,
		boolean eligible,
		@JsonProperty("block_reason") String blockReason) {
}

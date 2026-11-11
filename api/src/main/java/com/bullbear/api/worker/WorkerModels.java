package com.bullbear.api.worker;

import java.time.LocalDate;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/** 워커 응답 형식 (snake_case). */
final class WorkerModels {

	private WorkerModels() {
	}

	record SearchResponse(List<WorkerStock> items) {
	}

	record DailyResponse(List<DailyClose> items) {
	}

	/** mode·snapshot_id는 단일 모드(v0.6), as_of는 백테스트(v0.7)에서만 보낸다. 토론 요청은 이전과 똑같은 본문 */
	@JsonInclude(JsonInclude.Include.NON_NULL)
	record StartDebateRequest(String ticker, @JsonProperty("request_id") String requestId,
			@JsonProperty("max_extra_rounds") Integer maxExtraRounds, String mode,
			@JsonProperty("snapshot_id") String snapshotId, @JsonProperty("as_of") LocalDate asOf) {

		StartDebateRequest(String ticker, String requestId, Integer maxExtraRounds, String mode, String snapshotId) {
			this(ticker, requestId, maxExtraRounds, mode, snapshotId, null);
		}
	}
}

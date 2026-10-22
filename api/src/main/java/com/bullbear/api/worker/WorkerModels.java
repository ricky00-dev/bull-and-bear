package com.bullbear.api.worker;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 워커 응답 형식 (snake_case). */
final class WorkerModels {

	private WorkerModels() {
	}

	record SearchResponse(List<WorkerStock> items) {
	}

	record DailyResponse(List<DailyClose> items) {
	}

	record StartDebateRequest(String ticker, @JsonProperty("request_id") String requestId,
			@JsonProperty("max_extra_rounds") int maxExtraRounds) {
	}
}

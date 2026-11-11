package com.bullbear.api.worker;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

import tools.jackson.databind.json.JsonMapper;

/** 계약 v0.6: 토론 요청 본문은 예전과 같고, 단일 모드에서만 mode·snapshot_id를 보낸다. */
class StartDebateRequestTest {

	private final JsonMapper json = JsonMapper.builder().build();

	@Test
	void 토론_요청은_새_필드를_보내지_않는다() {
		assertThat(json.writeValueAsString(new WorkerModels.StartDebateRequest("005930", "r1", 1, null, null)))
				.isEqualTo("{\"ticker\":\"005930\",\"request_id\":\"r1\",\"max_extra_rounds\":1}");
	}

	@Test
	void 단일_요청은_모드와_스냅샷을_보낸다() {
		assertThat(json.writeValueAsString(new WorkerModels.StartDebateRequest("005930", "r2", null, "single", "s1")))
				.isEqualTo("{\"ticker\":\"005930\",\"request_id\":\"r2\",\"mode\":\"single\",\"snapshot_id\":\"s1\"}");
	}

	@Test
	void 백테스트_요청은_기준일을_보낸다() {
		assertThat(json.writeValueAsString(new WorkerModels.StartDebateRequest("005930", "r3", 1, null, null,
				java.time.LocalDate.of(2026, 9, 1))))
				.isEqualTo("{\"ticker\":\"005930\",\"request_id\":\"r3\",\"max_extra_rounds\":1,\"as_of\":\"2026-09-01\"}");
	}
}

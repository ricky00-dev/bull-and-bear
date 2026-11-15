package com.bullbear.api;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;

import org.hamcrest.Matchers;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.jayway.jsonpath.JsonPath;

/** 관리자 화면 API: 관리자 토큰으로만 열리고, 끝난 토론의 비용·이벤트가 집계에 잡힌다. */
@Import(TestcontainersConfiguration.class)
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.budget.user-daily-usd=1000", "bullbear.admin.token=test-admin" })
@AutoConfigureMockMvc
class AdminTest {

	@Autowired
	MockMvc mvc;

	@Test
	void 관리자_토큰이_없거나_틀리면_401() throws Exception {
		mvc.perform(get("/api/admin/overview")).andExpect(status().isUnauthorized());
		mvc.perform(get("/api/admin/overview").header("X-Admin-Token", "wrong")).andExpect(status().isUnauthorized());
		// 사용자 토큰으로는 열리지 않는다
		String guest = JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
		mvc.perform(get("/api/admin/overview").header("Authorization", "Bearer " + guest)).andExpect(status().isUnauthorized());
	}

	@Test
	void 끝난_토론이_비용_목록_이벤트에_잡힌다() throws Exception {
		String guest = JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
		String id = JsonPath.read(mvc.perform(post("/api/debates").header("Authorization", "Bearer " + guest)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"032830\"}"))
				.andReturn().getResponse().getContentAsString(), "$.id");
		awaitCompleted(id, guest);

		mvc.perform(get("/api/admin/overview").header("X-Admin-Token", "test-admin"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.workerMode").value("fake"))
				.andExpect(jsonPath("$.periods[3].label").value("전체"))
				.andExpect(jsonPath("$.periods[3].completed").value(Matchers.greaterThanOrEqualTo(1)))
				.andExpect(jsonPath("$.budget.user.limitUsd").value(1000.0))
				.andExpect(jsonPath("$.daily.length()").value(14))
				.andExpect(jsonPath("$.daily[13].day").value(java.time.LocalDate.now(java.time.ZoneId.of("Asia/Seoul")).toString()))
				.andExpect(jsonPath("$.models[0].model").exists())
				.andExpect(jsonPath("$.users.total").value(Matchers.greaterThanOrEqualTo(1)));

		mvc.perform(get("/api/admin/debates").param("status", "COMPLETED").header("X-Admin-Token", "test-admin"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$[?(@.id == '" + id + "')].ticker").value("032830"));

		mvc.perform(get("/api/admin/debates/" + id).header("X-Admin-Token", "test-admin"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.status").value("COMPLETED"))
				.andExpect(jsonPath("$.events[0].type").value("snapshot_created"))
				.andExpect(jsonPath("$.usage").isString());
	}

	private void awaitCompleted(String id, String guest) throws Exception {
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String body = mvc.perform(get("/api/debates/" + id).header("Authorization", "Bearer " + guest))
					.andReturn().getResponse().getContentAsString();
			if ("COMPLETED".equals(JsonPath.read(body, "$.status"))) {
				return;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다: " + id);
	}
}

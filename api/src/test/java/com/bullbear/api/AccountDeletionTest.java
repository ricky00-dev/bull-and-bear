package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.MockMvc;

import com.jayway.jsonpath.JsonPath;

/** 내 기록 삭제: 판정·채점·퀴즈·닉네임·계정이 지워지고, 공용 토론은 남는다. */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms" })
@AutoConfigureMockMvc
class AccountDeletionTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	JdbcClient jdbc;

	@Test
	void 내_기록을_모두_지우고_토큰은_더_이상_쓸_수_없다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String guest = mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString();
		String token = JsonPath.read(guest, "$.token");
		UUID userId = UUID.fromString(JsonPath.read(guest, "$.userId"));
		String debateId = createAndFinish(token, "005930");
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"BUY\",\"confidence\":70,\"evidencePicks\":[],\"memo\":\"지워져야 할 메모\"}"))
				.andExpect(status().isCreated());
		mvc.perform(put("/api/me/nickname").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"nickname\":\"지울사람\"}"))
				.andExpect(status().isOk());

		mvc.perform(delete("/api/me").header("Authorization", "Bearer " + token)).andExpect(status().isNoContent());

		mvc.perform(get("/api/me").header("Authorization", "Bearer " + token)).andExpect(status().isUnauthorized());
		assertThat(count("select count(*) from users where id = :u", userId)).isZero();
		assertThat(count("select count(*) from judgments where user_id = :u", userId)).isZero();
		assertThat(count("select count(*) from judgment_scores s join judgments j on j.id = s.judgment_id where j.user_id = :u", userId)).isZero();
		// 토론은 공용 기록이라 남고 요청자만 비운다
		mvc.perform(get("/api/debates/" + debateId).header("Authorization", "Bearer " + newGuest()))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.status").value("COMPLETED"));
		assertThat(count("select count(*) from debates where requested_by = :u", userId)).isZero();
	}

	private long count(String sql, UUID userId) {
		return jdbc.sql(sql).param("u", userId).query(Long.class).single();
	}

	private String newGuest() throws Exception {
		return JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
	}

	private String createAndFinish(String token, String ticker) throws Exception {
		String body = mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"))
				.andReturn().getResponse().getContentAsString();
		String id = JsonPath.read(body, "$.id");
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String d = mvc.perform(get("/api/debates/" + id).header("Authorization", "Bearer " + token))
					.andReturn().getResponse().getContentAsString();
			if ("COMPLETED".equals(JsonPath.read(d, "$.status"))) {
				return id;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다");
	}
}

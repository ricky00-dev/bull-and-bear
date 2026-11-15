package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import com.jayway.jsonpath.JsonPath;

/**
 * 비용 상한과 중복 방지. 가짜 워커 토론 한 번 ≈ $0.262 (Haiku + Opus 단가로 계산).
 * 상한을 작게 잡아 몇 번 만에 걸리게 한다: 사용자당 하루 2회, 하루 $1.0, 추정치 $0.3.
 */
@Import(TestcontainersConfiguration.class)
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.budget.per-user-daily-debates=2", "bullbear.budget.user-daily-usd=1.0",
		"bullbear.budget.estimate-usd=0.3" })
@AutoConfigureMockMvc
class DebateQuotaTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	JdbcTemplate jdbc;

	@Test
	void 사용량으로_비용을_계산하고_사용자별_횟수와_하루_비용을_제한한다() throws Exception {
		String a = guest();
		String t1 = id(create(a, "005930").andExpect(status().isCreated()));
		awaitCompleted(a, t1);
		// Haiku: 98k×0.10 + 21k×0.50 + 61k×0.01 + 9k×0.125 = $0.022035, Opus: 20k×4 + 8k×20 = $0.24
		assertThat(jdbc.queryForObject("select cost_usd from debates where id = ?::uuid", BigDecimal.class, t1))
				.isEqualByComparingTo("0.2620");
		awaitCompleted(a, id(create(a, "000660").andExpect(status().isCreated())));

		// 1. 사용자당 하루 2회: 세 번째 새 토론은 막히지만, 오늘 있는 토론 재사용은 된다
		mvc.perform(get("/api/stocks/006400").header("Authorization", "Bearer " + a))
				.andExpect(jsonPath("$.quota.left").value(0))
				.andExpect(jsonPath("$.quota.budgetOpen").value(true));
		create(a, "006400").andExpect(status().isTooManyRequests())
				.andExpect(jsonPath("$.error.code").value("DAILY_LIMIT"));
		create(a, "005930").andExpect(status().isCreated()).andExpect(jsonPath("$.reused").value(true));

		// 2. 하루 비용: $0.524 + 새 토론 $0.262 = $0.786, 그다음은 추정치 $0.3을 더하면 $1.0을 넘는다
		String b = guest();
		awaitCompleted(b, id(create(b, "006400").andExpect(status().isCreated())));
		mvc.perform(get("/api/stocks/028260").header("Authorization", "Bearer " + b))
				.andExpect(jsonPath("$.quota.left").value(1))
				.andExpect(jsonPath("$.quota.budgetOpen").value(false));
		create(b, "028260").andExpect(status().isServiceUnavailable())
				.andExpect(jsonPath("$.error.code").value("BUDGET_EXHAUSTED"));
		create(b, "000660").andExpect(status().isCreated()).andExpect(jsonPath("$.reused").value(true));
	}

	private ResultActions create(String token, String ticker) throws Exception {
		return mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"));
	}

	private static String id(ResultActions result) throws Exception {
		return JsonPath.read(result.andReturn().getResponse().getContentAsString(), "$.id");
	}

	private String guest() throws Exception {
		return JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
	}

	private void awaitCompleted(String token, String id) throws Exception {
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String d = mvc.perform(get("/api/debates/" + id).header("Authorization", "Bearer " + token))
					.andReturn().getResponse().getContentAsString();
			if ("COMPLETED".equals(JsonPath.read(d, "$.status"))) {
				return;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다");
	}
}

package com.bullbear.api;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

import com.jayway.jsonpath.JsonPath;

/** 외부 감시용 /ops/health: 인증 없이 열리고, 전향 운용이 그날 다 돌지 않았으면 503. */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.forward-run.enabled=true", "bullbear.forward-run.tickers=005930,000660" })
@AutoConfigureMockMvc
class OpsHealthTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Test
	void 전향_운용이_끝났는지_시각에_맞춰_확인한다() throws Exception {
		// 기동 직후 catchUp이 10/23(금) 고정 종목 토론을 돌린다. 마감(19:30) 전에는 기다리는 중
		clock.set(LocalDateTime.of(2026, 10, 23, 17, 0));
		mvc.perform(get("/ops/health"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.db").value("UP"))
				.andExpect(jsonPath("$.worker").value("FAKE"))
				.andExpect(jsonPath("$.forwardRun.status").value("WAITING"));

		// 마감 뒤: 두 종목 다 끝났으면 정상
		clock.set(LocalDateTime.of(2026, 10, 23, 20, 0));
		Instant deadline = Instant.now().plus(Duration.ofSeconds(15));
		String body = "";
		while (Instant.now().isBefore(deadline)) {
			body = mvc.perform(get("/ops/health")).andReturn().getResponse().getContentAsString();
			if ("UP".equals(JsonPath.read(body, "$.status"))) {
				break;
			}
			Thread.sleep(200);
		}
		org.assertj.core.api.Assertions.assertThat((String) JsonPath.read(body, "$.forwardRun.status")).isEqualTo("UP");

		// 다음 평일 마감 뒤에 토론이 없으면 알림 대상
		clock.set(LocalDateTime.of(2026, 10, 26, 20, 0));
		mvc.perform(get("/ops/health"))
				.andExpect(status().isServiceUnavailable())
				.andExpect(jsonPath("$.status").value("DOWN"))
				.andExpect(jsonPath("$.forwardRun.completed").value(0));

		// 주말엔 확인하지 않는다
		clock.set(LocalDateTime.of(2026, 10, 25, 20, 0));
		mvc.perform(get("/ops/health"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.forwardRun.status").value("WAITING"));
	}
}

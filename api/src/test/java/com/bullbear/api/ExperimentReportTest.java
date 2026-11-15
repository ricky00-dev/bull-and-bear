package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.experiment.SingleVerdictRunner;
import com.bullbear.api.quiz.OutcomeRecorder;
import com.jayway.jsonpath.JsonPath;

/**
 * AI 성적표: 전향 운용 토론 → 단일 판정(조건 B) → 3·7거래일 결과 → 같은 규칙으로 채점.
 * 가짜 워커는 기준일이 10/22라, 정식 운용 시작일을 그 전으로 둔다.
 */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.experiment.start=2026-10-01", "bullbear.experiment.single-enabled=true",
		"bullbear.experiment.poll-interval=1h" })
@AutoConfigureMockMvc
class ExperimentReportTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	DebateService debates;

	@Autowired
	SingleVerdictRunner singles;

	@Autowired
	OutcomeRecorder outcomes;

	@Autowired
	JdbcClient jdbc;

	@Test
	void 토론과_단일_판정을_같은_결과로_채점한다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 17, 0));
		UUID a = debates.create("005930", null, Debate.Origin.SCHEDULED).debate().getId();
		UUID b = debates.create("000660", null, Debate.Origin.SCHEDULED).debate().getId();
		waitCompleted(a);
		waitCompleted(b);

		// 정식 운용 토론마다 단일 판정을 한 번 받는다. 이미 받았으면 다시 부르지 않는다
		assertThat(singles.runDue()).isEqualTo(2);
		assertThat(singles.runDue()).isZero();
		assertThat(jdbc.sql("select count(*) from single_verdicts where status = 'COMPLETED' and cost_usd > 0")
				.query(Integer.class).single()).isEqualTo(2);

		// 3·7거래일 결과가 기록된 뒤 성적표에 들어간다
		clock.set(LocalDateTime.of(2026, 11, 3, 18, 10));
		outcomes.recordDue();
		String token = JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(),
				"$.token");
		String body = mvc.perform(get("/api/report").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.official").value(true))
				.andExpect(jsonPath("$.stocks").value(2))
				.andExpect(jsonPath("$.horizons[0].days").value(7))
				.andExpect(jsonPath("$.horizons[0].debate.n").value(2))
				.andExpect(jsonPath("$.horizons[0].single.n").value(2))
				.andExpect(jsonPath("$.horizons[1].days").value(3))
				.andExpect(jsonPath("$.horizons[1].debate.n").value(2))
				.andReturn().getResponse().getContentAsString();
		// 가짜 토론 판정은 항상 보류 → 토론 적중 수는 "항상 보류" 기준선과 같다
		int debateHits = JsonPath.read(body, "$.horizons[0].debate.hits");
		int holdHits = JsonPath.read(body, "$.horizons[0].alwaysHold.hits");
		assertThat(debateHits).isEqualTo(holdHits);

		// 예비 운용 포함으로 봐도 전향 운용 토론만 센다
		mvc.perform(get("/api/report?scope=all").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.official").value(false))
				.andExpect(jsonPath("$.horizons[0].debate.n").value(2));
	}

	private void waitCompleted(UUID id) throws InterruptedException {
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String status = jdbc.sql("select status from debates where id = :id").param("id", id).query(String.class)
					.single();
			if ("COMPLETED".equals(status)) {
				return;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다");
	}
}

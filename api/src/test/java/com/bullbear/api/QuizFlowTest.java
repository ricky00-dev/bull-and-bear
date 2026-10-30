package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.quiz.OutcomeRecorder;
import com.bullbear.api.scoring.ScoreRule;
import com.jayway.jsonpath.JsonPath;

/** 타임머신 퀴즈: 결과가 나온 토론만 출제, 공개 전엔 종목을 가리고, 답하면 실제 결과로 채점. */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms" })
@AutoConfigureMockMvc
class QuizFlowTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	OutcomeRecorder outcomes;

	@Test
	void 결과가_나온_토론으로_퀴즈를_내고_답하면_공개한다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String maker = guest();
		createAndFinish(maker, "035420");
		createAndFinish(maker, "005380");

		// 7거래일(11/2)이 지나야 결과가 기록된다
		clock.set(LocalDateTime.of(2026, 11, 3, 18, 10));
		outcomes.recordDue();
		assertThat(outcomes.recordDue()).isZero(); // 두 번 기록하지 않는다

		String player = guest();
		String round = mvc.perform(post("/api/quiz/rounds").header("Authorization", "Bearer " + player))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.current.idx").value(0))
				.andExpect(jsonPath("$.current.chart.ticker").doesNotExist())
				.andExpect(jsonPath("$.current.chart.points[-1].stockPct").value(0.0))
				.andReturn().getResponse().getContentAsString();
		String roundId = JsonPath.read(round, "$.id");
		int total = JsonPath.read(round, "$.total");
		assertThat(total).isBetween(2, 5);
		// 공개 전: 종목명·종목코드가 어디에도 없다
		String current = JsonPath.parse(round).read("$.current").toString();
		assertThat(current).doesNotContain("NAVER", "현대차", "035420", "005380").contains("이 회사");
		assertThat((String) JsonPath.read(round, "$.current.period")).isEqualTo("2026년 10월 넷째 주");

		// 답하면 종목·실제 결과·AI 판정이 공개되고, 채점은 실제 초과수익 기준
		String answer = mvc.perform(post("/api/quiz/rounds/" + roundId + "/questions/0/answer")
				.header("Authorization", "Bearer " + player)
				.contentType(MediaType.APPLICATION_JSON).content("{\"decision\":\"BUY\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.stockName").exists())
				.andExpect(jsonPath("$.moderatorDecision").exists())
				.andExpect(jsonPath("$.chart.ticker").exists())
				.andExpect(jsonPath("$.decisiveEvidence[0]").value("PX.VS_MA120"))
				.andExpect(jsonPath("$.last").value(false))
				.andReturn().getResponse().getContentAsString();
		BigDecimal excess = new BigDecimal(JsonPath.read(answer, "$.excessReturn").toString());
		boolean userHit = JsonPath.read(answer, "$.userHit");
		assertThat(userHit).isEqualTo(ScoreRule.hit("BUY", excess, new BigDecimal("2.0")));
		assertThat((String) JsonPath.read(answer, "$.correct"))
				.isEqualTo(excess.compareTo(new BigDecimal("2.0")) > 0 ? "BUY"
						: excess.compareTo(new BigDecimal("-2.0")) < 0 ? "SELL" : "HOLD");

		// 같은 문제는 두 번 못 푼다, 다음 문제로 넘어간다
		mvc.perform(post("/api/quiz/rounds/" + roundId + "/questions/0/answer")
				.header("Authorization", "Bearer " + player)
				.contentType(MediaType.APPLICATION_JSON).content("{\"decision\":\"SELL\"}"))
				.andExpect(status().isConflict());
		mvc.perform(get("/api/quiz/rounds/" + roundId).header("Authorization", "Bearer " + player))
				.andExpect(jsonPath("$.questions[0].decision").value("BUY"))
				.andExpect(jsonPath("$.userScore").value(userHit ? 1 : 0))
				.andExpect(jsonPath("$.current.idx").value(1));

		// 남의 퀴즈는 볼 수 없고, 퀴즈는 실제 판정 통계에 들어가지 않는다
		mvc.perform(get("/api/quiz/rounds/" + roundId).header("Authorization", "Bearer " + guest()))
				.andExpect(status().isNotFound());
		mvc.perform(get("/api/me/stats").header("Authorization", "Bearer " + player))
				.andExpect(jsonPath("$.judged").value(0));
	}

	private String guest() throws Exception {
		return JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
	}

	private void createAndFinish(String token, String ticker) throws Exception {
		String body = mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"))
				.andReturn().getResponse().getContentAsString();
		String id = JsonPath.read(body, "$.id");
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

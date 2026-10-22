package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.scoring.ScoreRule;
import com.bullbear.api.scoring.ScoringService;
import com.bullbear.api.worker.DailyClose;
import com.bullbear.api.worker.WorkerClient;
import com.jayway.jsonpath.JsonPath;

/**
 * 판정 → 채점 예약 → 시간이 흘러 3거래일·7거래일 채점 → 내 판정·통계 확인.
 * 가짜 워커 시세는 10/22 실제 종가에서 시작해 평일마다 결정적으로 움직인다.
 */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms" })
@AutoConfigureMockMvc
class ScoringFlowTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	ScoringService scoring;

	@Autowired
	WorkerClient worker;

	@Test
	void 판정은_3거래일과_7거래일에_코스피_대비로_채점된다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String token = guest();
		String debateId = createAndFinish(token, "000660");
		judge(token, debateId, "BUY", "[\"PX.RET_1Y\",\"PX.VOL_20D\"]");

		// 1. 채점 두 건이 예약된다 (기준일 10/22 목 → 3거래일 10/27 화, 7거래일 11/2 월)
		mvc.perform(get("/api/me/judgments").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.items[0].scores.length()").value(2))
				.andExpect(jsonPath("$.items[0].scores[0].status").value("PENDING"))
				.andExpect(jsonPath("$.items[0].scores[0].scheduledDate").value("2026-10-27"))
				.andExpect(jsonPath("$.items[0].scores[1].scheduledDate").value("2026-11-02"));

		// 2. 아직 시세가 없으면 채점하지 않는다
		assertThat(scoring.scorePending()).isZero();

		// 3. 10/28: 3거래일 채점만 된다
		// (같은 컨텍스트의 다른 테스트 판정도 함께 채점될 수 있어 건수는 하한만 본다)
		clock.set(LocalDateTime.of(2026, 10, 28, 18, 10));
		assertThat(scoring.scorePending()).isPositive();
		String body = mvc.perform(get("/api/me/judgments").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.items[0].scores[0].status").value("SCORED"))
				.andExpect(jsonPath("$.items[0].scores[0].scoredTradeDate").value("2026-10-27"))
				.andExpect(jsonPath("$.items[0].scores[1].status").value("PENDING"))
				.andReturn().getResponse().getContentAsString();
		assertScoreMatchesPrices(body, 0, "000660", LocalDate.of(2026, 10, 27), "BUY");

		// 4. 11/3: 7거래일 채점, 같은 건을 두 번 채점하지 않는다
		clock.set(LocalDateTime.of(2026, 11, 3, 18, 10));
		assertThat(scoring.scorePending()).isPositive();
		assertThat(scoring.scorePending()).isZero();
		body = mvc.perform(get("/api/me/judgments").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.items[0].scores[1].scoredTradeDate").value("2026-11-02"))
				.andReturn().getResponse().getContentAsString();
		assertScoreMatchesPrices(body, 1, "000660", LocalDate.of(2026, 11, 2), "BUY");

		// 5. 통계: 7거래일 기준 1건, 근거 습관은 추세 1·변동성 1
		boolean userHit = JsonPath.read(body, "$.items[0].scores[1].userHit");
		boolean modHit = JsonPath.read(body, "$.items[0].scores[1].moderatorHit");
		mvc.perform(get("/api/me/stats").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.judged").value(1))
				.andExpect(jsonPath("$.scored").value(1))
				.andExpect(jsonPath("$.userHits").value(userHit ? 1 : 0))
				.andExpect(jsonPath("$.beatAi").value(userHit && !modHit ? 1 : 0))
				.andExpect(jsonPath("$.evidenceHabit.length()").value(2));
	}

	@Test
	void 남의_판정_상세는_볼_수_없다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String owner = guest();
		String debateId = createAndFinish(owner, "035420");
		String judgmentId = JsonPath.read(judge(owner, debateId, "HOLD", "[]"), "$.mine.id");
		mvc.perform(get("/api/me/judgments/" + judgmentId).header("Authorization", "Bearer " + owner))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.decisiveEvidence[0]").value("PX.VS_MA120"))
				.andExpect(jsonPath("$.holdBand").value(2.0));
		mvc.perform(get("/api/me/judgments/" + judgmentId).header("Authorization", "Bearer " + guest()))
				.andExpect(status().isNotFound());
	}

	/** 저장된 채점 값이 워커 시세로 직접 계산한 값과 같은지 */
	private void assertScoreMatchesPrices(String body, int idx, String ticker, LocalDate day, String decision) {
		LocalDate base = LocalDate.of(2026, 10, 22);
		BigDecimal baseClose = close(worker.dailyCloses(ticker, base, day), base);
		BigDecimal stockRet = ScoreRule.returnPct(baseClose, close(worker.dailyCloses(ticker, base, day), day));
		BigDecimal indexRet = ScoreRule.returnPct(close(worker.indexCloses("KOSPI", base, day), base),
				close(worker.indexCloses("KOSPI", base, day), day));
		BigDecimal excess = stockRet.subtract(indexRet);
		String p = "$.items[0].scores[" + idx + "].";
		assertThat(new BigDecimal(JsonPath.read(body, p + "excessReturn").toString())).isEqualByComparingTo(excess);
		assertThat((Boolean) JsonPath.read(body, p + "userHit"))
				.isEqualTo(ScoreRule.hit(decision, excess, new BigDecimal("2.0")));
		assertThat((Boolean) JsonPath.read(body, p + "moderatorHit"))
				.isEqualTo(ScoreRule.hit("HOLD", excess, new BigDecimal("2.0")));
	}

	private static BigDecimal close(java.util.List<DailyClose> series, LocalDate day) {
		return series.stream().filter(c -> c.date().equals(day)).findFirst().orElseThrow().close();
	}

	private String guest() throws Exception {
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

	private String judge(String token, String debateId, String decision, String picks) throws Exception {
		return mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"" + decision + "\",\"confidence\":70,\"evidencePicks\":" + picks + "}"))
				.andExpect(status().isCreated())
				.andReturn().getResponse().getContentAsString();
	}
}

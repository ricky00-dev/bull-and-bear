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
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.scoring.ScoringService;
import com.jayway.jsonpath.JsonPath;

/** 판정일 전후 차트: 판정일이 0%, 채점일 표시, 두 선의 차이 = 채점 초과수익. */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms" })
@AutoConfigureMockMvc
class ChartFlowTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	ScoringService scoring;

	@Test
	void 차트는_판정일_대비_수익률이고_채점_초과수익과_맞는다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String token = guest();
		String id = createAndFinish(token, "005380");
		judge(token, id);

		// 판정 직후: 판정일 앞 약 20거래일 + 판정일이 0%, 채점일은 아직 예상일
		String before = chart(token, id);
		List<Map<String, Object>> pts = JsonPath.read(before, "$.points");
		assertThat(pts.size()).isBetween(18, 24);
		List<Object> s0 = JsonPath.read(before, "$.points[?(@.date == '2026-10-22')].stockPct");
		List<Object> i0 = JsonPath.read(before, "$.points[?(@.date == '2026-10-22')].indexPct");
		assertThat(num(s0.get(0))).isEqualByComparingTo("0");
		assertThat(num(i0.get(0))).isEqualByComparingTo("0");
		assertThat((Boolean) JsonPath.read(before, "$.marks[1].reached")).isFalse();
		assertThat((String) JsonPath.read(before, "$.marks[1].date")).isEqualTo("2026-11-02");

		// 11/3: 3·7거래일 지점이 실제 날짜로 찍히고, 7일 지점의 두 선 차이가 채점 초과수익과 같다
		clock.set(LocalDateTime.of(2026, 11, 3, 18, 10));
		scoring.scorePending();
		String after = chart(token, id);
		assertThat((Boolean) JsonPath.read(after, "$.marks[0].reached")).isTrue();
		assertThat((String) JsonPath.read(after, "$.marks[0].date")).isEqualTo("2026-10-27");
		assertThat((String) JsonPath.read(after, "$.marks[1].date")).isEqualTo("2026-11-02");
		List<Object> s7 = JsonPath.read(after, "$.points[?(@.date == '2026-11-02')].stockPct");
		List<Object> i7 = JsonPath.read(after, "$.points[?(@.date == '2026-11-02')].indexPct");
		String judgments = mvc.perform(get("/api/me/judgments").header("Authorization", "Bearer " + token))
				.andReturn().getResponse().getContentAsString();
		List<Object> excess = JsonPath.read(judgments, "$.items[?(@.debateId == '" + id + "')].scores[1].excessReturn");
		assertThat(num(s7.get(0)).subtract(num(i7.get(0)))).isEqualByComparingTo(num(excess.get(0)));
	}

	private static BigDecimal num(Object o) {
		return new BigDecimal(o.toString());
	}

	private String chart(String token, String id) throws Exception {
		return mvc.perform(get("/api/debates/" + id + "/chart").header("Authorization", "Bearer " + token))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
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

	private void judge(String token, String debateId) throws Exception {
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"BUY\",\"confidence\":70,\"evidencePicks\":[]}"))
				.andExpect(status().isCreated());
	}
}

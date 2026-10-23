package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;

import com.jayway.jsonpath.JsonPath;

/**
 * 가짜 워커 + 실제 Postgres(Testcontainers)로 전체 흐름을 검증한다.
 * 검색 → 토론 생성 → 중계 저장 → 판정 봉인 → 사용자 판정 → 공개.
 */
@Import(TestcontainersConfiguration.class)
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms" })
@AutoConfigureMockMvc
class DebateFlowTest {

	@Autowired
	MockMvc mvc;

	@Autowired
	JdbcTemplate jdbc;

	String token;

	@BeforeEach
	void guest() throws Exception {
		String body = mvc.perform(post("/api/auth/guest"))
				.andExpect(status().isCreated())
				.andReturn().getResponse().getContentAsString();
		token = JsonPath.read(body, "$.token");
	}

	@Test
	void 토큰이_없으면_401() throws Exception {
		mvc.perform(get("/api/me")).andExpect(status().isUnauthorized())
				.andExpect(jsonPath("$.error.code").value("UNAUTHORIZED"));
	}

	@Test
	void 초성으로_검색하고_토론불가_종목은_이유와_함께_나온다() throws Exception {
		mvc.perform(get("/api/stocks/search").param("q", "ㅅㅅㅈㅈ").header("Authorization", bearer()))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items[0].ticker").value("005930"))
				.andExpect(jsonPath("$.items[?(@.ticker == '005935')].blockReason").value("우선주는 토론하지 않아요"));
	}

	@Test
	void 토론불가_종목은_422() throws Exception {
		mvc.perform(post("/api/debates").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"005935\"}"))
				.andExpect(status().isUnprocessableContent())
				.andExpect(jsonPath("$.error.code").value("NOT_ELIGIBLE"));
	}

	@Test
	void 판정_전에는_중재자_판정이_봉인되고_판정_후에_공개된다() throws Exception {
		String debateId = createDebate("000660");
		awaitCompleted(debateId);

		// 1. 토론 기록과 스냅샷 기준 가격이 저장됐다
		mvc.perform(get("/api/debates/" + debateId).header("Authorization", bearer()))
				.andExpect(jsonPath("$.status").value("COMPLETED"))
				.andExpect(jsonPath("$.basePrice").value(1234000.0))
				.andExpect(jsonPath("$.tradeDate").value("2026-10-22"));

		// 2. 판정 전 공개 요청은 403
		mvc.perform(get("/api/debates/" + debateId + "/reveal").header("Authorization", bearer()))
				.andExpect(status().isForbidden())
				.andExpect(jsonPath("$.error.code").value("SEALED"));

		// 3. 스트림에는 발언은 있지만 판정 내용은 없다
		String stream = readStream(debateId, 0);
		assertThat(stream).contains("event:statement_accepted", "event:statement_rejected", "event:debate_sealed");
		assertThat(stream).doesNotContain("debate_completed", "reasoning", "decisive_evidence");

		// 4. 재연결: after 이후 이벤트만 다시 받는다
		String resumed = readStream(debateId, 20);
		assertThat(resumed).doesNotContain("event:snapshot_created").contains("event:debate_sealed");

		// 5. 판정 제출 → 같은 응답에 중재자 판정이 열린다
		String submit = "{\"decision\":\"SELL\",\"confidence\":70,\"evidencePicks\":[\"PX.VS_MA120\",\"PX.VOL_20D\"],\"memo\":\"추세 하락\"}";
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON).content(submit))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.mine.decision").value("SELL"))
				.andExpect(jsonPath("$.verdict.decision").value("HOLD"))
				.andExpect(jsonPath("$.agrees").value(false))
				.andExpect(jsonPath("$.crowd.sell").value(1));

		// 6. 다시 제출해도 첫 판정이 유지된다
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"BUY\",\"confidence\":90,\"evidencePicks\":[]}"))
				.andExpect(jsonPath("$.mine.decision").value("SELL"))
				.andExpect(jsonPath("$.crowd.total").value(1));
	}

	@Test
	void 같은_날_같은_종목_토론은_재사용한다() throws Exception {
		String first = createDebate("035720");
		String second = mvc.perform(post("/api/debates").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"035720\"}"))
				.andExpect(jsonPath("$.reused").value(true))
				.andReturn().getResponse().getContentAsString();
		assertThat((String) JsonPath.read(second, "$.id")).isEqualTo(first);
	}

	@Test
	void 잘못된_판정_요청은_400() throws Exception {
		String debateId = createDebate("005380");
		awaitCompleted(debateId);
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"BUY\",\"confidence\":40,\"evidencePicks\":[\"A1\",\"A2\",\"A3\"]}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
	}

	private String bearer() {
		return "Bearer " + token;
	}

	@Test
	void 같은_종목을_동시에_요청해도_토론은_하나만_생긴다() throws Exception {
		List<String> tokens = new ArrayList<>();
		for (int i = 0; i < 6; i++) {
			tokens.add(newGuest());
		}
		List<Callable<String>> calls = tokens.stream()
				.<Callable<String>>map(t -> () -> JsonPath.read(createAs(t, "028260").andExpect(status().isCreated()).andReturn().getResponse().getContentAsString(), "$.id"))
				.toList();
		Set<String> ids = new HashSet<>();
		var pool = Executors.newFixedThreadPool(calls.size());
		try {
			for (Future<String> f : pool.invokeAll(calls)) {
				ids.add(f.get());
			}
		} finally {
			pool.shutdown();
		}
		assertThat(ids).hasSize(1);
		assertThat(jdbc.queryForObject("select count(*) from debates where ticker = '028260'", Integer.class))
				.isEqualTo(1);
	}

	private ResultActions createAs(String token, String ticker) throws Exception {
		return mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"));
	}

	private String newGuest() throws Exception {
		return JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
	}

	private String createDebate(String ticker) throws Exception {
		String body = mvc.perform(post("/api/debates").header("Authorization", bearer())
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"))
				.andExpect(status().isCreated())
				.andReturn().getResponse().getContentAsString();
		return JsonPath.read(body, "$.id");
	}

	private void awaitCompleted(String debateId) throws Exception {
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String body = mvc.perform(get("/api/debates/" + debateId).header("Authorization", bearer()))
					.andReturn().getResponse().getContentAsString();
			if ("COMPLETED".equals(JsonPath.read(body, "$.status"))) {
				return;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다: " + debateId);
	}

	/** 끝난 토론의 스트림은 재생 후 바로 닫힌다. EventSource처럼 쿼리 파라미터 토큰을 쓴다. */
	private String readStream(String debateId, long after) throws Exception {
		MvcResult result = mvc.perform(get("/api/debates/" + debateId + "/stream")
				.param("access_token", token).param("after", Long.toString(after)))
				.andExpect(request().asyncStarted())
				.andReturn();
		return result.getResponse().getContentAsString();
	}
}

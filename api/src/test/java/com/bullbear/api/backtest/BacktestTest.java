package com.bullbear.api.backtest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.TestcontainersConfiguration;
import com.jayway.jsonpath.JsonPath;

/**
 * 백테스트: 과거 기준일로 토론하고, 끝나면 7거래일 결과까지 바로 기록한다. 다시 돌리면 재사용만 한다.
 * 가짜 워커는 기준일 종가를 결정적으로 만들고, 휴장일(주말)은 그 전 금요일로 맞춘다.
 */
@Import(TestcontainersConfiguration.class)
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.backtest.poll-interval=20ms" })
@AutoConfigureMockMvc
class BacktestTest {

	private static final String REQUEST = """
			{"tickers":["005930","000660","005935"],"dates":["2026-09-01","2026-09-05"]}""";

	@Autowired
	BacktestService backtest;

	@Autowired
	JdbcTemplate jdbc;

	@Autowired
	MockMvc mvc;

	@Test
	void 과거_기준일로_토론하고_결과까지_기록한다() throws Exception {
		mvc.perform(post("/ops/backtest").contentType(MediaType.APPLICATION_JSON).content(REQUEST))
				.andExpect(status().isAccepted())
				.andExpect(jsonPath("$.total").value(6));
		waitDone();

		// 우선주는 토론 불가라 실패로 센다. 토요일(9/5)은 금요일(9/4) 기준으로 돈다
		assertThat(backtest.progress().started()).isEqualTo(4);
		assertThat(backtest.progress().failed()).isEqualTo(2);
		assertThat(jdbc.queryForList(
				"select distinct trade_date from debates where origin = 'BACKTEST' and status = 'COMPLETED' order by 1",
				LocalDate.class)).containsExactly(LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 4));
		assertThat(jdbc.queryForObject("""
				select count(*) from debate_outcomes o join debates d on d.id = o.debate_id
				where d.origin = 'BACKTEST' and o.horizon_days = 7""", Integer.class)).isEqualTo(4);

		// 다시 보내면 새 토론 없이 재사용만 한다
		assertThat(backtest.start(new BacktestService.Request(List.of("005930", "000660"),
				List.of(LocalDate.of(2026, 9, 1))))).isTrue();
		waitDone();
		assertThat(backtest.progress().started()).isZero();
		assertThat(backtest.progress().reused()).isEqualTo(2);

		// 사용자 피드에는 안 보인다
		String token = JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(),
				"$.token");
		String feed = mvc.perform(get("/api/feed").header("Authorization", "Bearer " + token))
				.andReturn().getResponse().getContentAsString();
		assertThat(feed).doesNotContain("2026-09-01").doesNotContain("2026-09-04");
	}

	@Test
	void 오늘_이후_기준일은_받지_않는다() throws Exception {
		mvc.perform(post("/ops/backtest").contentType(MediaType.APPLICATION_JSON)
				.content("{\"tickers\":[\"005930\"],\"dates\":[\"2099-01-01\"]}"))
				.andExpect(status().isBadRequest());
	}

	private void waitDone() throws InterruptedException {
		Instant deadline = Instant.now().plus(Duration.ofSeconds(30));
		while (backtest.progress().running() && Instant.now().isBefore(deadline)) {
			Thread.sleep(20);
		}
		assertThat(backtest.progress().running()).isFalse();
	}
}

package com.bullbear.api.forwardrun;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.MutableClockConfiguration;
import com.bullbear.api.TestcontainersConfiguration;
import com.jayway.jsonpath.JsonPath;

/**
 * 전향 운용: 서버가 켜지면 밀린 회차를 돌고, 두 개씩만 동시에 돌리며, 다시 돌려도 토론이 늘지 않는다.
 * 만들어 둔 토론은 다음 날 장 마감 전까지(같은 기준일) 사용자가 기다림 없이 재사용한다.
 * 가짜 워커의 최신 종가 날짜는 10/22로 고정이다.
 */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=150ms",
		"bullbear.forward-run.enabled=true", "bullbear.forward-run.tickers=005930,000660,006400,005380",
		"bullbear.forward-run.max-concurrent=2", "bullbear.forward-run.poll-interval=20ms" })
@AutoConfigureMockMvc
class ForwardRunTest {

	@Autowired
	ForwardRunService forwardRun;

	@Autowired
	JdbcTemplate jdbc;

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Test
	void 고정_종목을_두_개씩_돌리고_다음_날_오전_사용자가_재사용한다() throws Exception {
		// 1. 서버가 켜질 때 밀린 회차가 돈다. 도는 동안 동시에 진행 중인 토론은 2개를 넘지 않는다
		int maxRunning = 0;
		Instant deadline = Instant.now().plus(Duration.ofSeconds(30));
		while ((forwardRun.isRunning() || running() > 0) && Instant.now().isBefore(deadline)) {
			maxRunning = Math.max(maxRunning, running());
			Thread.sleep(20);
		}
		assertThat(maxRunning).isLessThanOrEqualTo(2);
		assertThat(jdbc.queryForObject(
				"select count(*) from debates where origin = 'SCHEDULED' and status = 'COMPLETED'", Integer.class))
				.isEqualTo(4);

		// 2. 다시 돌려도 같은 기준일이라 새 토론이 생기지 않는다
		assertThat(forwardRun.runOnce()).isZero();

		// 3. 다음 날 오전: 아직 장 마감 전이라 최신 종가가 같다 → 사용자는 기다리지 않고, 횟수도 차감되지 않는다
		clock.set(LocalDateTime.of(2026, 10, 23, 9, 30));
		String token = JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(),
				"$.token");
		mvc.perform(get("/api/stocks/005930").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.existingDebate.status").value("COMPLETED"))
				.andExpect(jsonPath("$.existingDebate.dataDate").value("2026-10-22"));
		mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"005930\"}"))
				.andExpect(jsonPath("$.reused").value(true));
		mvc.perform(get("/api/stocks/000660").header("Authorization", "Bearer " + token))
				.andExpect(jsonPath("$.quota.left").value(5));
	}

	private int running() {
		return jdbc.queryForObject("select count(*) from debates where origin = 'SCHEDULED' and status = 'RUNNING'",
				Integer.class);
	}
}

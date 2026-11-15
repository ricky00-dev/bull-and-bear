package com.bullbear.api.ops;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Clock;
import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalTime;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.config.ClockConfig;

/**
 * 외부 감시(UptimeRobot 등)용 상태 확인. Caddy가 /healthz로 열어 준다.
 * 하나라도 문제면 503을 돌려 감시 서비스가 알림을 보내게 한다.
 *
 * actuator health와 따로 둔 이유: 워커나 전향 운용이 실패해도 API 컨테이너는 정상이라
 * 컨테이너 헬스체크(재시작·기동 순서)에 섞으면 안 된다.
 */
@RestController
public class OpsHealthController {

	/** 전향 운용(16:40, 재시도 18:40)이 끝났어야 하는 시각 */
	static final LocalTime FORWARD_RUN_DEADLINE = LocalTime.of(19, 30);

	private final JdbcClient jdbc;
	private final Clock clock;
	private final BullbearProperties.Worker worker;
	private final BullbearProperties.ForwardRun forwardRun;
	private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();

	OpsHealthController(JdbcClient jdbc, Clock clock, BullbearProperties properties) {
		this.jdbc = jdbc;
		this.clock = clock;
		this.worker = properties.worker();
		this.forwardRun = properties.forwardRun();
	}

	@GetMapping("/ops/health")
	public ResponseEntity<Map<String, Object>> health() {
		Map<String, Object> body = new LinkedHashMap<>();
		boolean ok = true;

		boolean db = db();
		body.put("db", db ? "UP" : "DOWN");
		ok &= db;

		if ("http".equals(worker.mode())) {
			boolean w = worker();
			body.put("worker", w ? "UP" : "DOWN");
			ok &= w;
		} else {
			body.put("worker", "FAKE");
		}

		if (forwardRun.enabled() && db) {
			Map<String, Object> fr = forwardRun();
			body.put("forwardRun", fr);
			ok &= !"DOWN".equals(fr.get("status"));
		}

		body.put("status", ok ? "UP" : "DOWN");
		return ResponseEntity.status(ok ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
	}

	private boolean db() {
		try {
			return jdbc.sql("select 1").query(Integer.class).single() == 1;
		} catch (RuntimeException e) {
			return false;
		}
	}

	private boolean worker() {
		try {
			HttpRequest req = HttpRequest.newBuilder(worker.baseUrl().resolve(URI.create("/health")))
					.timeout(Duration.ofSeconds(5)).GET().build();
			return http.send(req, HttpResponse.BodyHandlers.discarding()).statusCode() == 200;
		} catch (Exception e) {
			return false;
		}
	}

	/**
	 * 평일 19:30 이후 오늘 고정 종목이 모두 토론됐는지. 사용자가 같은 날 먼저 토론한 종목은 그 토론을 쓰므로
	 * 출처와 상관없이 종목 수로 센다. 휴장일에는 알림이 한 번 잘못 갈 수 있다 (11월에는 휴장일 없음).
	 */
	private Map<String, Object> forwardRun() {
		ZonedDateTime now = ZonedDateTime.now(clock.withZone(ClockConfig.KST));
		boolean weekday = now.getDayOfWeek() != DayOfWeek.SATURDAY && now.getDayOfWeek() != DayOfWeek.SUNDAY;
		int expected = forwardRun.tickers().size();
		int done = jdbc.sql("""
				select count(distinct ticker) from debates
				where debate_day = :day and status = 'COMPLETED' and ticker in (:tickers)
				""")
				.param("day", now.toLocalDate()).param("tickers", forwardRun.tickers())
				.query(Integer.class).single();
		Map<String, Object> fr = new LinkedHashMap<>();
		fr.put("expected", expected);
		fr.put("completed", done);
		boolean due = weekday && !now.toLocalTime().isBefore(FORWARD_RUN_DEADLINE);
		fr.put("status", !due ? "WAITING" : done >= expected ? "UP" : "DOWN");
		return fr;
	}
}

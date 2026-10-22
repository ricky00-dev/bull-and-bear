package com.bullbear.api.config;

import java.math.BigDecimal;
import java.net.URI;
import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("bullbear")
public record BullbearProperties(Cors cors, Worker worker, Scoring scoring) {

	public record Cors(List<String> allowedOrigins) {
	}

	/**
	 * @param mode fake(가짜 워커) 또는 http(실제 Python 워커)
	 * @param fakeDelay 가짜 워커가 이벤트 사이에 쉬는 시간. 테스트에서는 0
	 */
	public record Worker(String mode, URI baseUrl, String token, Duration fakeDelay) {
	}

	/**
	 * @param holdBand 보류 적중 구간 (±%p). 매수·매도는 이 구간을 넘어야 적중
	 * @param index 비교 지수 코드
	 * @param cron 채점 실행 시각 (KST)
	 */
	public record Scoring(BigDecimal holdBand, String index, String cron) {
	}
}

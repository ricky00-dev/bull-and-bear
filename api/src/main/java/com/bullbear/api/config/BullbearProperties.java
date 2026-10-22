package com.bullbear.api.config;

import java.net.URI;
import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("bullbear")
public record BullbearProperties(Cors cors, Worker worker) {

	public record Cors(List<String> allowedOrigins) {
	}

	/**
	 * @param mode fake(가짜 워커) 또는 http(실제 Python 워커)
	 * @param fakeDelay 가짜 워커가 이벤트 사이에 쉬는 시간. 테스트에서는 0
	 */
	public record Worker(String mode, URI baseUrl, String token, Duration fakeDelay) {
	}
}

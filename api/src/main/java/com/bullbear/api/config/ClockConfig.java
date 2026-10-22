package com.bullbear.api.config;

import java.time.Clock;
import java.time.Duration;
import java.time.ZoneId;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** "오늘"은 항상 한국 시간. 테스트에서는 시계를 바꿔 채점일을 앞당긴다. */
@Configuration
public class ClockConfig {

	public static final ZoneId KST = ZoneId.of("Asia/Seoul");

	/**
	 * @param devOffset 개발·QA용. "오늘"을 앞당겨 채점 화면을 미리 볼 때만 쓴다 (예: P11D). 운영에서는 0
	 */
	@Bean
	Clock clock(@Value("${bullbear.dev.clock-offset:PT0S}") Duration devOffset) {
		Clock system = Clock.system(KST);
		return devOffset.isZero() ? system : Clock.offset(system, devOffset);
	}
}

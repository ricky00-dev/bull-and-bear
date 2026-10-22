package com.bullbear.api.config;

import java.time.Clock;
import java.time.ZoneId;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** "오늘"은 항상 한국 시간. 테스트에서는 시계를 바꿔 채점일을 앞당긴다. */
@Configuration
public class ClockConfig {

	public static final ZoneId KST = ZoneId.of("Asia/Seoul");

	@Bean
	Clock clock() {
		return Clock.system(KST);
	}
}

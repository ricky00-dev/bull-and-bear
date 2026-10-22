package com.bullbear.api;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

import com.bullbear.api.config.ClockConfig;

/** 테스트에서 "오늘"을 옮길 수 있는 시계. */
@TestConfiguration(proxyBeanMethods = false)
public class MutableClockConfiguration {

	public static class MutableClock extends Clock {
		private Instant now;

		MutableClock(Instant now) {
			this.now = now;
		}

		public void set(LocalDateTime kst) {
			this.now = kst.atZone(ClockConfig.KST).toInstant();
		}

		@Override
		public ZoneId getZone() {
			return ClockConfig.KST;
		}

		@Override
		public Clock withZone(ZoneId zone) {
			return this;
		}

		@Override
		public Instant instant() {
			return now;
		}
	}

	@Bean
	@Primary
	MutableClock mutableClock() {
		return new MutableClock(LocalDateTime.of(2026, 10, 23, 10, 0).atZone(ClockConfig.KST).toInstant());
	}
}

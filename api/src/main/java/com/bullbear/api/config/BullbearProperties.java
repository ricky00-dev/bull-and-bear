package com.bullbear.api.config;

import java.math.BigDecimal;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("bullbear")
public record BullbearProperties(Cors cors, Worker worker, Scoring scoring, Budget budget) {

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

	/**
	 * LLM 비용 상한. 월 $200 크레딧 안에서 끝내기 위함 (docs/ROADMAP.md 비용 계획).
	 *
	 * @param userDailyUsd 사용자가 시작한 토론의 하루(KST) 비용 상한. 넘으면 새 토론을 막고 오늘 토론만 재사용
	 * @param perUserDailyDebates 사용자 한 명이 하루에 새로 시작할 수 있는 토론 수
	 * @param estimateUsd 아직 사용량을 모르는 토론(진행 중·실패)을 이 값으로 셈
	 * @param prices 모델별 단가 (USD / 100만 토큰). 워커가 cost_usd를 안 보낼 때 쓴다
	 */
	public record Budget(BigDecimal userDailyUsd, int perUserDailyDebates, BigDecimal estimateUsd,
			Map<String, Price> prices) {

		public record Price(BigDecimal input, BigDecimal output, BigDecimal cacheRead, BigDecimal cacheWrite) {
		}
	}
}

package com.bullbear.api.config;

import java.math.BigDecimal;
import java.net.URI;
import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("bullbear")
public record BullbearProperties(Cors cors, Worker worker, Scoring scoring, Budget budget,
		ForwardRun forwardRun, Experiment experiment, Backtest backtest) {

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

	/**
	 * 전향 운용: 고정 종목을 장 마감 뒤 매일 토론해 실험 데이터와 퀴즈 문제를 쌓는다 (docs/experiment.md).
	 * 만들어 둔 토론은 다음 날 장 마감 전까지 사용자도 기다림 없이 재사용한다.
	 *
	 * @param maxConcurrent 동시에 돌리는 토론 수. 워커·API 속도 제한을 넘지 않게
	 * @param dailyUsd 전향 운용 하루 비용 상한 (사용자 상한과 별도)
	 */
	public record ForwardRun(boolean enabled, List<String> tickers, String cron, int maxConcurrent,
			BigDecimal dailyUsd, Duration pollInterval) {
	}

	/**
	 * 실험 "토론 vs 단일" (docs/experiment.md).
	 *
	 * @param start 정식 운용 시작일. 이 날 이후 전향 운용 토론만 실험에 센다 (그 전은 예비 운용, 퀴즈·시연용)
	 * @param singleEnabled 정식 운용 토론마다 단일 판정(조건 B)을 요청할지. 워커가 단일 모드를 지원하면 켠다
	 * @param maxAttempts 단일 판정이 실패하면 이만큼까지 다시 시도
	 */
	public record Experiment(LocalDate start, boolean singleEnabled, int maxAttempts) {
	}

	/**
	 * 백테스트: 과거 기준일 토론 (docs/experiment.md). 서버 안에서 POST /ops/backtest로 시작한다.
	 *
	 * @param dailyUsd 하루에 시작한 백테스트 토론 비용 상한. 전향 운용·사용자 상한과 따로 센다
	 */
	public record Backtest(int maxConcurrent, BigDecimal dailyUsd, Duration pollInterval) {
	}
}

package com.bullbear.api.scoring;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;

/**
 * 채점 규칙 (팀 합의 전 초안, docs/worker-api.md "채점 규칙").
 *
 * 초과수익 = 종목 수익률 − 코스피 수익률. 시장 전체가 움직인 효과를 뺀다.
 * BUY는 +band 초과, SELL은 −band 미만, HOLD는 ±band 이내면 적중.
 */
public final class ScoreRule {

	private static final MathContext MC = MathContext.DECIMAL64;

	private ScoreRule() {
	}

	public static boolean hit(String decision, BigDecimal excessPct, BigDecimal band) {
		return switch (decision) {
			case "BUY" -> excessPct.compareTo(band) > 0;
			case "SELL" -> excessPct.compareTo(band.negate()) < 0;
			case "HOLD" -> excessPct.abs().compareTo(band) <= 0;
			default -> throw new IllegalArgumentException("알 수 없는 판정: " + decision);
		};
	}

	/** (to / from − 1) × 100, 소수 넷째 자리 */
	public static BigDecimal returnPct(BigDecimal from, BigDecimal to) {
		return to.divide(from, MC).subtract(BigDecimal.ONE).movePointRight(2).setScale(4, RoundingMode.HALF_UP);
	}

	/** 화면 안내용 예상일. 주말만 건너뛴다 (휴장일은 모름). */
	public static LocalDate estimateTradingDay(LocalDate from, int tradingDays) {
		LocalDate d = from;
		int left = tradingDays;
		while (left > 0) {
			d = d.plusDays(1);
			if (d.getDayOfWeek() != DayOfWeek.SATURDAY && d.getDayOfWeek() != DayOfWeek.SUNDAY) {
				left--;
			}
		}
		return d;
	}
}

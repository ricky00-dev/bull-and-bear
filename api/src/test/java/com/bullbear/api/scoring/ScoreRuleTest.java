package com.bullbear.api.scoring;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;

class ScoreRuleTest {

	static final BigDecimal BAND = new BigDecimal("2.0");

	@Test
	void 매수는_구간을_넘어야_적중() {
		assertThat(ScoreRule.hit("BUY", new BigDecimal("2.01"), BAND)).isTrue();
		assertThat(ScoreRule.hit("BUY", new BigDecimal("2.00"), BAND)).isFalse();
		assertThat(ScoreRule.hit("BUY", new BigDecimal("-5"), BAND)).isFalse();
	}

	@Test
	void 매도는_음의_구간을_넘어야_적중() {
		assertThat(ScoreRule.hit("SELL", new BigDecimal("-2.01"), BAND)).isTrue();
		assertThat(ScoreRule.hit("SELL", new BigDecimal("-2.00"), BAND)).isFalse();
	}

	@Test
	void 보류는_구간_안이면_적중_경계_포함() {
		assertThat(ScoreRule.hit("HOLD", new BigDecimal("2.00"), BAND)).isTrue();
		assertThat(ScoreRule.hit("HOLD", new BigDecimal("-2.00"), BAND)).isTrue();
		assertThat(ScoreRule.hit("HOLD", new BigDecimal("2.01"), BAND)).isFalse();
	}

	@Test
	void 수익률은_퍼센트_소수_넷째_자리() {
		assertThat(ScoreRule.returnPct(new BigDecimal("214500"), new BigDecimal("220000"))).isEqualByComparingTo("2.5641");
		assertThat(ScoreRule.returnPct(new BigDecimal("100"), new BigDecimal("97"))).isEqualByComparingTo("-3.0000");
	}

	@Test
	void 예상_채점일은_주말을_건너뛴다() {
		LocalDate thu = LocalDate.of(2026, 10, 22);
		assertThat(ScoreRule.estimateTradingDay(thu, 3)).isEqualTo(LocalDate.of(2026, 10, 27)); // 금, 월, 화
		assertThat(ScoreRule.estimateTradingDay(thu, 7)).isEqualTo(LocalDate.of(2026, 11, 2));
	}
}

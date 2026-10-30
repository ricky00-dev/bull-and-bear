package com.bullbear.api.quiz;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/** 퀴즈 공개 전 가리기: 이름뿐 아니라 가격·금액만 봐도 종목을 알 수 있다. */
class QuizHintsTest {

	@Test
	void 종목명과_금액을_가리고_비율은_남긴다() {
		String text = "삼성전자 종가는 242,000원이고 반기 영업이익은 146,725,209,000,000원, 146.7조 원이에요. "
				+ "PER 9.39배, 1개월 -15.24%, 2026년 상반기 기준.";
		assertThat(QuizHints.mask(text, "삼성전자", "005930"))
				.isEqualTo("이 회사 종가는 ○○원이고 반기 영업이익은 ○○원, ○○원이에요. "
						+ "PER 9.39배, 1개월 -15.24%, 2026년 상반기 기준.");
		assertThat(QuizHints.mask("(원, 178,964,931,000,000) 값 146725209000000.0", "삼성전자", "005930"))
				.isEqualTo("(원, ○○) 값 ○○");
	}

	@Test
	void 가격_수준과_큰_금액_근거만_값을_가린다() {
		assertThat(QuizHints.revealing("PX.CLOSE", 242000)).isTrue();
		assertThat(QuizHints.revealing("PX.MA120", 270000)).isTrue();
		assertThat(QuizHints.revealing("VAL.OPERATING_INCOME_TTM", 1.78e14)).isTrue();
		assertThat(QuizHints.revealing("VAL.PER_TTM", 9.39)).isFalse();
		assertThat(QuizHints.revealing("FIN.2026H1.OPERATING_INCOME_YOY", 1191.44)).isFalse();
	}
}

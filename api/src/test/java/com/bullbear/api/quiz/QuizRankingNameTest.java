package com.bullbear.api.quiz;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;

import org.junit.jupiter.api.Test;

class QuizRankingNameTest {

	private static final UUID ID = UUID.fromString("ab12cd34-0000-0000-0000-000000000000");

	@Test
	void 닉네임이_없으면_게스트와_가입자를_구분한다() {
		assertThat(QuizRanking.displayName(null, true, ID)).isEqualTo("게스트 #ab12");
		assertThat(QuizRanking.displayName(null, false, ID)).isEqualTo("회원 #ab12");
		assertThat(QuizRanking.displayName("불개미", false, ID)).isEqualTo("불개미");
	}
}

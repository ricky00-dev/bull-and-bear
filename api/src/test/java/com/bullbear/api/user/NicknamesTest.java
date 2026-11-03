package com.bullbear.api.user;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

import com.bullbear.api.common.ApiException;

class NicknamesTest {

	@Test
	void 앞뒤_공백을_빼고_연속_공백은_하나로() {
		assertThat(Nicknames.validate("  불  개미 ")).isEqualTo("불 개미");
		assertThat(Nicknames.validate("Bull_99")).isEqualTo("Bull_99");
	}

	@Test
	void 길이_문자_욕설을_막는다() {
		for (String bad : new String[] { null, "가", "열한글자가넘는닉네임이다", "이모지😀", "<script>", "ㅅ ㅂ왕", "Admin" }) {
			assertThatThrownBy(() -> Nicknames.validate(bad)).as(bad).isInstanceOf(ApiException.class);
		}
	}
}

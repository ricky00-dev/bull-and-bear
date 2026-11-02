package com.bullbear.api.user;

import java.util.List;
import java.util.regex.Pattern;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;

/**
 * 랭킹에 공개되는 닉네임 검사. 전시장 화면에 그대로 뜨므로 길이·문자·욕설을 막는다.
 * 욕설 목록은 흔한 것만 막는 최소한이다. 운영 중 발견되면 여기에 더한다.
 */
public final class Nicknames {

	private static final Pattern ALLOWED = Pattern.compile("[가-힣a-zA-Z0-9_ ]{2,10}");
	private static final List<String> BANNED = List.of("시발", "씨발", "ㅅㅂ", "병신", "ㅂㅅ", "좆", "개새", "새끼", "fuck",
			"shit", "운영자", "관리자", "admin");

	private Nicknames() {
	}

	/** @return 앞뒤 공백을 뺀 닉네임 */
	public static String validate(String raw) {
		String name = raw == null ? "" : raw.strip().replaceAll("\\s+", " ");
		if (!ALLOWED.matcher(name).matches()) {
			throw new ApiException(ErrorCode.INVALID_REQUEST, "닉네임은 한글·영문·숫자 2~10자로 지어 주세요");
		}
		String compact = name.replace(" ", "").toLowerCase();
		if (BANNED.stream().anyMatch(compact::contains)) {
			throw new ApiException(ErrorCode.INVALID_REQUEST, "쓸 수 없는 닉네임이에요");
		}
		return name;
	}
}

package com.bullbear.api.worker;

/** 한글 초성 추출. "삼성전자" → "ㅅㅅㅈㅈ" */
public final class Choseong {

	private static final char[] CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ".toCharArray();

	private Choseong() {
	}

	public static String of(String text) {
		StringBuilder sb = new StringBuilder(text.length());
		for (char ch : text.toCharArray()) {
			int code = ch - 0xAC00;
			sb.append(code >= 0 && code < 11172 ? CHO[code / 588] : ch);
		}
		return sb.toString();
	}
}

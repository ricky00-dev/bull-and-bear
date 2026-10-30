package com.bullbear.api.quiz;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 퀴즈에서 종목·날짜를 가릴 때 대신 보여줄 힌트.
 * 이름을 알면 결과를 찾아볼 수 있으니 공개 전까지 업종과 "몇 월 몇째 주"만 보여준다.
 */
final class QuizHints {

	/** 전향 운용 종목 업종 (docs/experiment.md). 그 밖의 종목은 업종을 모른다. */
	private static final Map<String, String> SECTOR = Map.ofEntries(
			Map.entry("005930", "반도체"), Map.entry("000660", "반도체"), Map.entry("373220", "2차전지"),
			Map.entry("207940", "바이오"), Map.entry("105560", "금융"), Map.entry("005380", "자동차"),
			Map.entry("035420", "인터넷"), Map.entry("051910", "화학"), Map.entry("017670", "통신"),
			Map.entry("012450", "방산"));

	/** 본문에 정식 이름 대신 나올 수 있는 이름. 긴 것부터 바꾼다. */
	private static final Map<String, List<String>> ALIASES = Map.ofEntries(
			Map.entry("005930", List.of("삼성전자")), Map.entry("000660", List.of("하이닉스")),
			Map.entry("373220", List.of("LG에너지솔루션", "LG엔솔", "엔솔")),
			Map.entry("207940", List.of("삼성바이오로직스", "삼성바이오", "삼바")),
			Map.entry("105560", List.of("KB금융지주", "KB금융")), Map.entry("005380", List.of("현대자동차")),
			Map.entry("035420", List.of("네이버")), Map.entry("051910", List.of("LG화학")),
			Map.entry("017670", List.of("SK텔레콤", "SKT")),
			Map.entry("012450", List.of("한화에어로스페이스", "한화에어로")));

	/** 값만 봐도 종목이 드러나는 근거: 가격 수준, 주식 수, 시가총액 */
	private static final Set<String> REVEALING = Set.of("PX.CLOSE", "PX.HIGH_52W", "PX.LOW_52W", "PX.MA20",
			"PX.MA60", "PX.MA120", "PX.AVG_VOLUME_20D", "VAL.MKTCAP", "VAL.SHARES");

	/** 본문 속 금액("242,000원", "146.7조 원")과 큰 숫자("146,725,209,000,000")도 종목을 드러낸다 */
	private static final Pattern AMOUNT = Pattern
			.compile("\\d[\\d,]*(?:\\.\\d+)?\\s*(?:조|억|만)?\\s*원|\\d{1,3}(?:,\\d{3}){2,}(?:\\.\\d+)?|\\d{7,}(?:\\.\\d+)?");

	private static final String[] NTH = { "첫째", "둘째", "셋째", "넷째", "다섯째" };

	private QuizHints() {
	}

	static String sector(String ticker) {
		String s = SECTOR.get(ticker);
		return s == null ? "국내 상장사" : s + " 업종 대형주";
	}

	/** 2026-11-04 → "2026년 11월 첫째 주" */
	static String period(LocalDate d) {
		return d.getYear() + "년 " + d.getMonthValue() + "월 " + NTH[(d.getDayOfMonth() - 1) / 7] + " 주";
	}

	/** 본문에서 종목명·종목코드를 "이 회사"로, 금액·큰 숫자를 "○○"로 바꾼다. */
	static String mask(String text, String stockName, String ticker) {
		if (text == null) {
			return null;
		}
		String out = text.replace(stockName, "이 회사").replace(ticker, "••••••");
		for (String alias : ALIASES.getOrDefault(ticker, List.of())) {
			out = out.replace(alias, "이 회사");
		}
		return AMOUNT.matcher(out).replaceAll(m -> m.group().endsWith("원") ? "○○원" : "○○");
	}

	/** 근거 값을 공개 전에 가려야 하는지. 비율·배수는 두고, 가격 수준과 금액(1억 이상)은 가린다. */
	static boolean revealing(String sourceId, double value) {
		return REVEALING.contains(sourceId) || Math.abs(value) >= 1e8;
	}
}

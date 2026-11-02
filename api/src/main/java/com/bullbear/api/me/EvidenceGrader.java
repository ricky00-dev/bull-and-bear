package com.bullbear.api.me;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 내가 고른 근거가 실제 결과와 같은 방향이었는지 채점한다.
 *
 * 근거 자체에는 방향이 없다. 그 근거를 인용한 토론자(매수 측·매도 측)가 방향을 준다.
 * 초과수익이 +band를 넘으면 매수 측 근거가, −band 밑이면 매도 측 근거가 맞은 것이고,
 * 그 사이면 어느 쪽 근거도 결정적이지 않았던 것(FLAT)이다.
 */
public final class EvidenceGrader {

	public enum Result {
		/** 근거를 인용한 쪽으로 주가가 움직였다 */
		RIGHT,
		/** 반대쪽으로 움직였다 */
		WRONG,
		/** 코스피와 비슷하게 움직여 어느 쪽 근거도 결정적이지 않았다 */
		FLAT,
		/** 아직 채점 전 */
		PENDING,
		/** 토론에서 인용된 적 없는 근거 (방향을 알 수 없다) */
		UNKNOWN
	}

	/** @param sides 이 근거를 인용한 쪽 (bull, bear) */
	public record Pick(String sourceId, List<String> sides, Result result) {
	}

	private EvidenceGrader() {
	}

	/** statement_accepted 이벤트 원본들 → 근거 ID별 인용한 쪽 */
	static Map<String, Set<String>> sidesBySource(List<String> statementPayloads, ObjectMapper json) {
		Map<String, Set<String>> sides = new LinkedHashMap<>();
		for (String payload : statementPayloads) {
			JsonNode event = json.readTree(payload);
			String side = event.path("side").asString();
			for (JsonNode e : event.path("statement").path("evidence")) {
				sides.computeIfAbsent(e.path("source_id").asString(), k -> new LinkedHashSet<>()).add(side);
			}
		}
		return sides;
	}

	/** @param excess 초과수익(%p). 채점 전이면 null */
	static List<Pick> grade(List<String> picks, Map<String, Set<String>> sidesBySource, BigDecimal excess,
			BigDecimal band) {
		List<Pick> out = new ArrayList<>();
		for (String id : picks) {
			Set<String> sides = sidesBySource.getOrDefault(id, Set.of());
			out.add(new Pick(id, List.copyOf(sides), result(sides, excess, band)));
		}
		return out;
	}

	private static Result result(Set<String> sides, BigDecimal excess, BigDecimal band) {
		if (sides.isEmpty()) {
			return Result.UNKNOWN;
		}
		if (excess == null) {
			return Result.PENDING;
		}
		String winner = excess.compareTo(band) > 0 ? "bull" : excess.compareTo(band.negate()) < 0 ? "bear" : null;
		if (winner == null) {
			return Result.FLAT;
		}
		return sides.contains(winner) ? Result.RIGHT : Result.WRONG;
	}
}

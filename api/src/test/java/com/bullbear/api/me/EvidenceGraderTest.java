package com.bullbear.api.me;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;

import com.bullbear.api.me.EvidenceGrader.Result;

import tools.jackson.databind.json.JsonMapper;

class EvidenceGraderTest {

	static final BigDecimal BAND = new BigDecimal("2.0");
	static final Map<String, Set<String>> SIDES = Map.of(
			"PX.RET_1Y", Set.of("bull"),
			"PX.VOL_20D", Set.of("bear"),
			"PX.VS_MA20", Set.of("bull", "bear"));
	static final List<String> PICKS = List.of("PX.RET_1Y", "PX.VOL_20D", "PX.VS_MA20", "VAL.PER");

	@Test
	void 오르면_매수_측_근거가_맞다() {
		assertThat(results(new BigDecimal("3.5")))
				.containsExactly(Result.RIGHT, Result.WRONG, Result.RIGHT, Result.UNKNOWN);
	}

	@Test
	void 내리면_매도_측_근거가_맞다() {
		assertThat(results(new BigDecimal("-2.01")))
				.containsExactly(Result.WRONG, Result.RIGHT, Result.RIGHT, Result.UNKNOWN);
	}

	@Test
	void 코스피와_비슷하면_판가름_안_난다() {
		assertThat(results(new BigDecimal("2.0")))
				.containsExactly(Result.FLAT, Result.FLAT, Result.FLAT, Result.UNKNOWN);
		assertThat(results(null)).containsExactly(Result.PENDING, Result.PENDING, Result.PENDING, Result.UNKNOWN);
	}

	@Test
	void 발언에서_근거별로_인용한_쪽을_모은다() {
		var json = JsonMapper.builder().build();
		var sides = EvidenceGrader.sidesBySource(List.of(
				"{\"side\":\"bull\",\"statement\":{\"evidence\":[{\"source_id\":\"PX.RET_1Y\"}]}}",
				"{\"side\":\"bear\",\"statement\":{\"evidence\":[{\"source_id\":\"PX.RET_1Y\"},{\"source_id\":\"PX.VOL_20D\"}]}}"),
				json);
		assertThat(sides.get("PX.RET_1Y")).containsExactly("bull", "bear");
		assertThat(sides.get("PX.VOL_20D")).containsExactly("bear");
	}

	private static List<Result> results(BigDecimal excess) {
		return EvidenceGrader.grade(PICKS, SIDES, excess, BAND).stream().map(EvidenceGrader.Pick::result).toList();
	}
}

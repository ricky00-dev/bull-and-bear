package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.bullbear.api.config.BullbearProperties;

import tools.jackson.databind.JsonNode;

/**
 * 워커 이벤트의 usage를 토큰 수와 비용(USD)으로 바꾼다.
 *
 * 워커가 cost_usd를 보내면 그 값을, 없으면 모델별 단가로 계산한다.
 * v0.3 형식({calls: [...], cost_usd?})과 v0.2 형식({model, input_tokens, output_tokens})을 모두 받는다.
 */
@Component
class LlmUsage {

	record Usage(long inputTokens, long outputTokens, BigDecimal costUsd) {
	}

	private static final BigDecimal MILLION = BigDecimal.valueOf(1_000_000);
	private static final Logger log = LoggerFactory.getLogger(LlmUsage.class);

	private final BullbearProperties.Budget budget;

	LlmUsage(BullbearProperties properties) {
		this.budget = properties.budget();
	}

	Optional<Usage> parse(JsonNode usage) {
		if (usage == null || !usage.isObject()) {
			return Optional.empty();
		}
		long input = 0;
		long output = 0;
		BigDecimal cost = BigDecimal.ZERO;
		Iterable<JsonNode> calls = usage.has("calls") ? usage.path("calls") : List.of(usage);
		for (JsonNode c : calls) {
			long in = c.path("input_tokens").asLong();
			long out = c.path("output_tokens").asLong();
			long cacheRead = c.path("cache_read_input_tokens").asLong();
			long cacheWrite = c.path("cache_creation_input_tokens").asLong();
			input += in + cacheRead + cacheWrite;
			output += out;
			cost = cost.add(price(c.path("model").asString(), in, out, cacheRead, cacheWrite));
		}
		if (usage.path("cost_usd").isNumber()) {
			cost = usage.path("cost_usd").decimalValue();
		}
		return Optional.of(new Usage(input, output, cost.setScale(4, RoundingMode.HALF_UP)));
	}

	private BigDecimal price(String model, long in, long out, long cacheRead, long cacheWrite) {
		BullbearProperties.Budget.Price p = budget.prices().get(model);
		if (p == null) {
			if (in + out > 0) {
				log.warn("단가를 모르는 모델 {} — 추정치 ${}로 셈", model, budget.estimateUsd());
				return budget.estimateUsd();
			}
			return BigDecimal.ZERO; // 가짜 워커 등 사용량 없음
		}
		return p.input().multiply(BigDecimal.valueOf(in))
				.add(p.output().multiply(BigDecimal.valueOf(out)))
				.add(p.cacheRead().multiply(BigDecimal.valueOf(cacheRead)))
				.add(p.cacheWrite().multiply(BigDecimal.valueOf(cacheWrite)))
				.divide(MILLION, 6, RoundingMode.HALF_UP);
	}
}

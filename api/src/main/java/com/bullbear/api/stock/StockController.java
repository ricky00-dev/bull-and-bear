package com.bullbear.api.stock;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerStock;
import com.bullbear.api.worker.WorkerStockDetail;

import jakarta.validation.constraints.Pattern;

@RestController
@RequestMapping("/api/stocks")
public class StockController {

	public record SearchResponse(List<StockItem> items) {
	}

	/** 브라우저용 검색 결과 (camelCase). 워커 형식(snake_case)을 그대로 내보내지 않는다. */
	public record StockItem(String ticker, String name, String market, long close, double changePct,
			boolean eligible, String blockReason) {

		static StockItem of(WorkerStock s) {
			return new StockItem(s.ticker(), s.name(), s.market(), s.close(), s.changePct(), s.eligible(),
					s.blockReason());
		}
	}

	/** @param todayDebate 오늘 이미 진행된 토론. 있으면 기다리지 않고 바로 볼 수 있다 */
	public record StockResponse(String ticker, String name, String market, long close, double changePct,
			LocalDate asOf, boolean eligible, List<String> reasons, List<Long> sparkline, TodayDebate todayDebate) {
	}

	public record TodayDebate(UUID id, Debate.Status status, Instant createdAt) {
	}

	private final WorkerClient worker;
	private final DebateService debates;

	StockController(WorkerClient worker, DebateService debates) {
		this.worker = worker;
		this.debates = debates;
	}

	/** 종목명, 6자리 코드, 초성으로 검색. 토론 불가 종목도 이유와 함께 돌려준다. */
	@GetMapping("/search")
	public SearchResponse search(@RequestParam String q, @RequestParam(defaultValue = "20") int limit) {
		return new SearchResponse(worker.search(q, Math.min(limit, 50)).stream().map(StockItem::of).toList());
	}

	@GetMapping("/{ticker}")
	public StockResponse get(@PathVariable @Pattern(regexp = "\\d{6}") String ticker) {
		WorkerStockDetail s = worker.stock(ticker);
		TodayDebate today = debates.findToday(ticker)
				.map(d -> new TodayDebate(d.getId(), d.getStatus(), d.getCreatedAt()))
				.orElse(null);
		return new StockResponse(s.ticker(), s.name(), s.market(), s.close(), s.changePct(), s.asOf(), s.eligible(),
				s.reasons(), s.sparkline(), today);
	}
}

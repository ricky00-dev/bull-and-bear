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

import com.bullbear.api.auth.CurrentUser;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateQuota;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.user.User;
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

	/**
	 * @param existingDebate 같은 데이터(최신 종가)로 이미 진행된 토론. 있으면 기다리지 않고 바로 볼 수 있다
	 * @param quota 이 사용자가 오늘 새 토론을 더 시작할 수 있는지
	 */
	public record StockResponse(String ticker, String name, String market, long close, double changePct,
			LocalDate asOf, boolean eligible, List<String> reasons, List<Long> sparkline, ExistingDebate existingDebate,
			DebateQuota.Status quota) {
	}

	public record ExistingDebate(UUID id, Debate.Status status, Instant createdAt, LocalDate dataDate) {
	}

	private final WorkerClient worker;
	private final DebateService debates;
	private final DebateQuota quota;

	StockController(WorkerClient worker, DebateService debates, DebateQuota quota) {
		this.worker = worker;
		this.debates = debates;
		this.quota = quota;
	}

	/** 종목명, 6자리 코드, 초성으로 검색. 토론 불가 종목도 이유와 함께 돌려준다. */
	@GetMapping("/search")
	public SearchResponse search(@RequestParam String q, @RequestParam(defaultValue = "20") int limit) {
		return new SearchResponse(worker.search(q, Math.min(limit, 50)).stream().map(StockItem::of).toList());
	}

	@GetMapping("/{ticker}")
	public StockResponse get(@CurrentUser User user, @PathVariable @Pattern(regexp = "\\d{6}") String ticker) {
		WorkerStockDetail s = worker.stock(ticker);
		ExistingDebate existing = debates.findReusable(ticker, s.asOf())
				.map(d -> new ExistingDebate(d.getId(), d.getStatus(), d.getCreatedAt(), d.getDataDate()))
				.orElse(null);
		return new StockResponse(s.ticker(), s.name(), s.market(), s.close(), s.changePct(), s.asOf(), s.eligible(),
				s.reasons(), s.sparkline(), existing, quota.status(user.getId()));
	}
}

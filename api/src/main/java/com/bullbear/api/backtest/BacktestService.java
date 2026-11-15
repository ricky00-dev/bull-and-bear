package com.bullbear.api.backtest;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateQuota;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.quiz.OutcomeRecorder;
import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerStockDetail;

/**
 * 백테스트: 지정한 종목 × 과거 기준일마다 토론을 한 번씩 돌린다 (워커 계약 v0.7 as_of).
 *
 * - 기준일 이후 데이터가 섞이지 않는 건 워커 책임이다. 워커가 as_of를 모르고 최신 종가로 답하면
 *   (돌려준 기준일이 요청보다 뒤) 비용을 쓰기 전에 전체를 멈춘다.
 * - 토론 생성은 멱등이라 같은 요청을 다시 보내면 실패한 칸만 새로 돈다.
 * - 다 끝나면 3·7거래일 결과를 바로 기록한다. 과거 기준일이라 결과가 이미 있어서 퀴즈 문제가 곧바로 생긴다.
 * - 전향 운용처럼 maxConcurrent개씩, 전용 스레드 하나에서 돈다. 한 번에 한 회차만.
 */
@Service
public class BacktestService implements DisposableBean {

	private static final Logger log = LoggerFactory.getLogger(BacktestService.class);

	/** 과거 기준일 시세는 워커가 처음 계산하는 데 수십 초 걸릴 수 있다. 5초 간격으로 1분까지 기다린다 */
	private static final int QUOTE_ATTEMPTS = 12;
	private static final Duration QUOTE_RETRY = Duration.ofSeconds(5);

	/** @param tickers 종목 코드 @param dates 기준일. 휴장일이면 워커가 그 전 거래일로 맞춘다 */
	public record Request(List<String> tickers, List<LocalDate> dates) {
	}

	/**
	 * @param total 요청한 칸 수 (종목 × 기준일)
	 * @param stopReason 끝까지 못 돌고 멈춘 이유. 정상 종료면 null
	 */
	public record Progress(boolean running, int total, int done, int started, int reused, int failed,
			String stopReason) {
	}

	private final DebateService debates;
	private final DebateQuota quota;
	private final WorkerClient worker;
	private final OutcomeRecorder outcomes;
	private final BullbearProperties.Backtest config;
	private final Clock clock;
	private final ExecutorService runner = Executors.newSingleThreadExecutor(r -> new Thread(r, "backtest"));
	private final AtomicBoolean running = new AtomicBoolean();
	private volatile Progress progress = new Progress(false, 0, 0, 0, 0, 0, null);

	BacktestService(DebateService debates, DebateQuota quota, WorkerClient worker, OutcomeRecorder outcomes,
			BullbearProperties properties, Clock clock) {
		this.debates = debates;
		this.quota = quota;
		this.worker = worker;
		this.outcomes = outcomes;
		this.config = properties.backtest();
		this.clock = clock;
	}

	/** @return 새로 시작했으면 true. 이미 돌고 있으면 false */
	public boolean start(Request request) {
		LocalDate today = LocalDate.now(clock);
		if (request.tickers().isEmpty() || request.dates().isEmpty()
				|| request.dates().stream().anyMatch(d -> !d.isBefore(today))) {
			throw new IllegalArgumentException("종목과 오늘 이전 기준일이 하나 이상 필요해요");
		}
		if (!running.compareAndSet(false, true)) {
			return false;
		}
		progress = new Progress(true, request.tickers().size() * request.dates().size(), 0, 0, 0, 0, null);
		runner.submit(() -> {
			try {
				run(request);
			} catch (RuntimeException e) {
				log.error("백테스트 중단", e);
				stop(e.getMessage());
			} finally {
				progress = with(progress.done(), progress.started(), progress.reused(), progress.failed(),
						progress.stopReason(), false);
				running.set(false);
			}
		});
		return true;
	}

	public Progress progress() {
		return progress;
	}

	private void run(Request request) {
		List<LocalDate> dates = request.dates().stream().sorted().toList();
		for (LocalDate date : dates) {
			for (String ticker : request.tickers()) {
				if (!waitUntil(() -> debates.running(Debate.Origin.BACKTEST) < config.maxConcurrent())) {
					return;
				}
				if (!quota.backtestBudgetOpen(config.dailyUsd())) {
					stop("하루 백테스트 비용 상한($" + config.dailyUsd() + ") 도달");
					return;
				}
				Progress p = progress;
				try {
					WorkerStockDetail stock = worker.stockWhenReady(ticker, date, QUOTE_ATTEMPTS, QUOTE_RETRY);
					if (stock.asOf().isAfter(date)) {
						stop("워커가 기준일(as_of)을 지원하지 않아요: " + date + " 요청에 " + stock.asOf() + " 응답");
						return;
					}
					var created = debates.createBacktest(stock);
					progress = created.reused() ? with(p.done() + 1, p.started(), p.reused() + 1, p.failed(), null, true)
							: with(p.done() + 1, p.started() + 1, p.reused(), p.failed(), null, true);
					log.info("백테스트 {}: {} 기준일 {}", created.reused() ? "재사용" : "시작", ticker, stock.asOf());
				} catch (ApiException e) {
					progress = with(p.done() + 1, p.started(), p.reused(), p.failed() + 1, null, true);
					log.warn("백테스트 토론 실패: {} {} {}", ticker, date, e.getMessage());
				}
			}
		}
		// 마지막 토론들이 끝나야 결과를 기록할 수 있다
		if (waitUntil(() -> debates.running(Debate.Origin.BACKTEST) == 0)) {
			log.info("백테스트 끝. 토론 결과 {}건 기록", outcomes.recordDue());
		}
	}

	private void stop(String reason) {
		log.warn("백테스트 멈춤: {}", reason);
		Progress p = progress;
		progress = with(p.done(), p.started(), p.reused(), p.failed(), reason, true);
	}

	private Progress with(int done, int started, int reused, int failed, String stopReason, boolean running) {
		return new Progress(running, progress.total(), done, started, reused, failed, stopReason);
	}

	private boolean waitUntil(java.util.function.BooleanSupplier condition) {
		Duration poll = config.pollInterval();
		while (!condition.getAsBoolean()) {
			try {
				Thread.sleep(poll.toMillis());
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				return false;
			}
		}
		return true;
	}

	@Override
	public void destroy() {
		runner.shutdownNow();
	}
}

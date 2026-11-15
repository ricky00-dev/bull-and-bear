package com.bullbear.api.forwardrun;

import java.time.Duration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateQuota;
import com.bullbear.api.debate.DebateService;

/**
 * 전향 운용: 고정 종목을 장 마감 뒤 매일 토론한다.
 *
 * - 토론 생성은 멱등이다 (같은 종목·같은 기준일이면 재사용). 그래서 하루에 여러 번 돌려도 되고,
 *   두 번째 회차는 첫 회차에서 실패한 종목만 다시 시도하는 셈이 된다. 서버가 꺼져 있었으면 켜질 때 한 번 돈다.
 * - 한꺼번에 띄우지 않고 maxConcurrent개씩 돌린다. 워커와 Anthropic API 속도 제한을 넘지 않게.
 * - 스케줄러 스레드를 막지 않도록 전용 스레드에서 돈다. 이미 돌고 있으면 새 회차는 건너뛴다.
 */
@Service
public class ForwardRunService implements DisposableBean {

	private static final Logger log = LoggerFactory.getLogger(ForwardRunService.class);

	private final DebateService debates;
	private final DebateQuota quota;
	private final BullbearProperties.ForwardRun config;
	private final ExecutorService runner = Executors.newSingleThreadExecutor(r -> new Thread(r, "forward-run"));
	private final AtomicBoolean running = new AtomicBoolean();

	ForwardRunService(DebateService debates, DebateQuota quota, BullbearProperties properties) {
		this.debates = debates;
		this.quota = quota;
		this.config = properties.forwardRun();
	}

	@Scheduled(cron = "${bullbear.forward-run.cron}", zone = "Asia/Seoul")
	public void scheduled() {
		trigger();
	}

	@EventListener(ApplicationReadyEvent.class)
	public void catchUp() {
		trigger();
	}

	/** @return 이번에 새로 돌리기 시작했으면 true (이미 돌고 있거나 꺼져 있으면 false) */
	public boolean trigger() {
		if (!config.enabled() || !running.compareAndSet(false, true)) {
			return false;
		}
		runner.submit(() -> {
			try {
				runOnce();
			} finally {
				running.set(false);
			}
		});
		return true;
	}

	/** @return 새로 시작한 토론 수 */
	int runOnce() {
		int started = 0;
		for (String ticker : config.tickers()) {
			if (!waitForSlot()) {
				return started;
			}
			if (!quota.scheduledBudgetOpen(config.dailyUsd())) {
				log.warn("전향 운용 하루 비용 상한(${}) 도달 — {}부터 건너뜀", config.dailyUsd(), ticker);
				return started;
			}
			try {
				var created = debates.create(ticker, null, Debate.Origin.SCHEDULED);
				if (!created.reused()) {
					started++;
					log.info("전향 운용 토론 시작: {} 기준일 {}", ticker, created.debate().getDataDate());
				}
			} catch (ApiException e) {
				log.warn("전향 운용 토론 실패: {} {}", ticker, e.getMessage());
			}
		}
		return started;
	}

	/** 진행 중인 전향 운용 토론이 maxConcurrent 밑으로 내려갈 때까지 기다린다. */
	private boolean waitForSlot() {
		Duration poll = config.pollInterval();
		while (debates.runningScheduled() >= config.maxConcurrent()) {
			try {
				Thread.sleep(poll.toMillis());
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				return false;
			}
		}
		return true;
	}

	boolean isRunning() {
		return running.get();
	}

	@Override
	public void destroy() {
		runner.shutdownNow();
	}
}

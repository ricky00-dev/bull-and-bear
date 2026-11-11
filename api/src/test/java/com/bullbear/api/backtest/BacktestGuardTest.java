package com.bullbear.api.backtest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import org.junit.jupiter.api.Test;

import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.config.ClockConfig;
import com.bullbear.api.debate.DebateQuota;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.quiz.OutcomeRecorder;
import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerStockDetail;

/** 워커가 as_of를 모르고 최신 종가로 답하면, 미래 데이터로 토론하기 전에(비용을 쓰기 전에) 멈춘다. */
class BacktestGuardTest {

	@Test
	void 워커가_기준일을_무시하면_토론을_만들지_않고_멈춘다() throws Exception {
		WorkerClient worker = mock(WorkerClient.class);
		DebateService debates = mock(DebateService.class);
		DebateQuota quota = mock(DebateQuota.class);
		when(quota.backtestBudgetOpen(any())).thenReturn(true);
		when(worker.stock("005930", LocalDate.of(2026, 9, 1))).thenReturn(new WorkerStockDetail("005930", "삼성전자",
				"KOSPI", 100, 0, LocalDate.of(2026, 11, 10), true, List.of(), List.of()));
		var properties = new BullbearProperties(null, null, null, null, null, null,
				new BullbearProperties.Backtest(2, BigDecimal.TEN, Duration.ofMillis(10)));
		var service = new BacktestService(debates, quota, worker, mock(OutcomeRecorder.class), properties,
				Clock.fixed(Instant.parse("2026-11-11T00:00:00Z"), ClockConfig.KST));

		service.start(new BacktestService.Request(List.of("005930"), List.of(LocalDate.of(2026, 9, 1))));
		Instant deadline = Instant.now().plusSeconds(5);
		while (service.progress().running() && Instant.now().isBefore(deadline)) {
			Thread.sleep(10);
		}

		assertThat(service.progress().stopReason()).contains("as_of");
		verify(debates, never()).createBacktest(any());
		service.destroy();
	}
}

package com.bullbear.api.worker;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.CALLS_REAL_METHODS;

import java.time.Duration;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;

/** 워커가 시세를 준비하는 동안(503) 스케줄러·백테스트는 기다렸다 다시 묻는다. 다른 오류는 바로 올린다. */
class StockWhenReadyTest {

	static final LocalDate DAY = LocalDate.of(2026, 10, 15);

	@Test
	void 준비_중이면_다시_묻는다() {
		WorkerClient worker = mock(WorkerClient.class, CALLS_REAL_METHODS);
		WorkerStockDetail detail = mock(WorkerStockDetail.class);
		ApiException preparing = new ApiException(ErrorCode.WORKER_UNAVAILABLE, "워커 오류 503");
		when(worker.stock("005930", DAY)).thenThrow(preparing, preparing).thenReturn(detail);

		assertThat(worker.stockWhenReady("005930", DAY, 5, Duration.ZERO)).isSameAs(detail);
		verify(worker, times(3)).stock("005930", DAY);
	}

	@Test
	void 횟수를_넘기거나_다른_오류면_그대로_올린다() {
		WorkerClient worker = mock(WorkerClient.class, CALLS_REAL_METHODS);
		when(worker.stock(any(), any())).thenThrow(new ApiException(ErrorCode.WORKER_UNAVAILABLE, "워커 오류 503"));
		assertThatThrownBy(() -> worker.stockWhenReady("005930", DAY, 3, Duration.ZERO)).isInstanceOf(ApiException.class);
		verify(worker, times(3)).stock("005930", DAY);

		WorkerClient other = mock(WorkerClient.class, CALLS_REAL_METHODS);
		when(other.stock(any(), any())).thenThrow(new ApiException(ErrorCode.NOT_ELIGIBLE, "코스피만"));
		assertThatThrownBy(() -> other.stockWhenReady("005930", DAY, 3, Duration.ZERO)).isInstanceOf(ApiException.class);
		verify(other, times(1)).stock("005930", DAY);
	}
}

package com.bullbear.api.chart;

import java.time.Clock;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Service;

import com.bullbear.api.worker.DailyClose;
import com.bullbear.api.worker.WorkerClient;

/**
 * 차트용 종가 조회. 확정 종가는 하루에 한 번만 바뀌므로 (종목, 기간)별로 그날 하루 캐시한다.
 * 같은 토론 결과 화면을 여러 사람이 열어도 워커는 하루 한 번만 부른다.
 */
@Service
public class PriceHistory {

	private record Key(String code, boolean index, LocalDate from, LocalDate to) {
	}

	private final WorkerClient worker;
	private final Clock clock;
	private final Map<Key, List<DailyClose>> cache = new ConcurrentHashMap<>();
	private volatile LocalDate cacheDay;

	public PriceHistory(WorkerClient worker, Clock clock) {
		this.worker = worker;
		this.clock = clock;
	}

	public List<DailyClose> stock(String ticker, LocalDate from, LocalDate to) {
		return get(new Key(ticker, false, from, to));
	}

	public List<DailyClose> index(String code, LocalDate from, LocalDate to) {
		return get(new Key(code, true, from, to));
	}

	private List<DailyClose> get(Key key) {
		LocalDate today = LocalDate.now(clock);
		if (!today.equals(cacheDay)) {
			cache.clear();
			cacheDay = today;
		}
		return cache.computeIfAbsent(key, k -> k.index()
				? worker.indexCloses(k.code(), k.from(), k.to())
				: worker.dailyCloses(k.code(), k.from(), k.to()));
	}
}

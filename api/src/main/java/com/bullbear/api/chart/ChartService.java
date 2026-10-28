package com.bullbear.api.chart;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.scoring.ScoreRule;
import com.bullbear.api.worker.DailyClose;

/**
 * 판정일 전후 주가 차트. 종목과 코스피를 판정일 종가 대비 수익률(%)로 같은 축에 놓는다.
 * 두 선의 차이가 곧 채점에 쓰는 초과수익이라, 왜 적중·빗나감인지 눈으로 보인다.
 * 확정 종가만 쓴다 (실시간 시세 없음).
 */
@Service
public class ChartService {

	/** 판정일 앞으로 보여줄 기간 (달력일, 약 20거래일) */
	static final int LOOKBACK_DAYS = 30;
	static final int[] HORIZONS = { 3, 7 };

	public record Point(LocalDate date, BigDecimal close, BigDecimal stockPct, BigDecimal indexPct) {
	}

	/** @param date 실제 n번째 거래일 (시세가 아직 없으면 주말만 뺀 예상일) */
	public record Mark(int horizonDays, LocalDate date, boolean reached) {
	}

	public record ChartResponse(String ticker, LocalDate baseDate, BigDecimal holdBand, List<Point> points,
			List<Mark> marks) {
	}

	private final PriceHistory prices;
	private final BullbearProperties.Scoring scoring;
	private final Clock clock;

	public ChartService(PriceHistory prices, BullbearProperties properties, Clock clock) {
		this.prices = prices;
		this.scoring = properties.scoring();
		this.clock = clock;
	}

	public ChartResponse build(Debate d) {
		LocalDate base = d.getTradeDate();
		if (base == null) {
			throw new ApiException(ErrorCode.NOT_FOUND, "아직 스냅샷이 없는 토론입니다");
		}
		LocalDate today = LocalDate.now(clock);
		LocalDate last = ScoreRule.estimateTradingDay(base, HORIZONS[HORIZONS.length - 1] + 2);
		LocalDate to = last.isAfter(today) ? today : last;
		LocalDate from = base.minusDays(LOOKBACK_DAYS);

		List<DailyClose> stock = prices.stock(d.getTicker(), from, to);
		Map<LocalDate, BigDecimal> index = prices.index(scoring.index(), from, to).stream()
				.collect(Collectors.toMap(DailyClose::date, DailyClose::close, (a, b) -> b));
		BigDecimal baseClose = stock.stream().filter(c -> c.date().equals(base)).map(DailyClose::close).findFirst()
				.orElse(d.getBasePrice());
		BigDecimal baseIndex = index.get(base);

		List<Point> points = new ArrayList<>();
		List<LocalDate> after = new ArrayList<>();
		for (DailyClose c : stock) {
			BigDecimal idx = index.get(c.date());
			if (idx == null || baseIndex == null) {
				continue; // 지수가 없는 날은 비교할 수 없어 뺀다
			}
			points.add(new Point(c.date(), c.close(), ScoreRule.returnPct(baseClose, c.close()),
					ScoreRule.returnPct(baseIndex, idx)));
			if (c.date().isAfter(base)) {
				after.add(c.date());
			}
		}

		List<Mark> marks = new ArrayList<>();
		for (int h : HORIZONS) {
			marks.add(after.size() >= h ? new Mark(h, after.get(h - 1), true)
					: new Mark(h, ScoreRule.estimateTradingDay(base, h), false));
		}
		return new ChartResponse(d.getTicker(), base, scoring.holdBand(), points, marks);
	}
}

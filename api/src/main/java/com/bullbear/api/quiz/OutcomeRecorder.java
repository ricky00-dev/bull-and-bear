package com.bullbear.api.quiz;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.scoring.ScoreRule;
import com.bullbear.api.worker.DailyClose;
import com.bullbear.api.worker.WorkerClient;

/**
 * 끝난 토론마다 3·7거래일 뒤 실제 결과를 한 번씩 기록한다 (사용자 판정과 무관).
 * 퀴즈 문제는 7거래일 결과가 있는 토론에서만 낸다. AI 성적표는 둘 다 쓴다. 채점과 같은 시각에 돈다.
 */
@Service
public class OutcomeRecorder {

	public static final int HORIZON = 7;
	static final int[] HORIZONS = { 3, 7 };
	private static final Logger log = LoggerFactory.getLogger(OutcomeRecorder.class);

	private final JdbcClient jdbc;
	private final WorkerClient worker;
	private final BullbearProperties.Scoring config;
	private final Clock clock;

	public OutcomeRecorder(JdbcClient jdbc, WorkerClient worker, BullbearProperties properties, Clock clock) {
		this.jdbc = jdbc;
		this.worker = worker;
		this.config = properties.scoring();
		this.clock = clock;
	}

	private record Pending(UUID id, String ticker, LocalDate tradeDate, BigDecimal basePrice) {
	}

	@Scheduled(cron = "${bullbear.scoring.cron}", zone = "Asia/Seoul")
	public void scheduled() {
		int n = recordDue();
		if (n > 0) {
			log.info("토론 결과 {}건 기록", n);
		}
	}

	@EventListener(ApplicationReadyEvent.class)
	public void catchUp() {
		scheduled();
	}

	/** @return 이번에 기록한 건수 (기간별로 센다) */
	public int recordDue() {
		int recorded = 0;
		for (int horizon : HORIZONS) {
			recorded += recordDue(horizon);
		}
		return recorded;
	}

	private int recordDue(int horizon) {
		LocalDate today = LocalDate.now(clock);
		List<Pending> due = jdbc.sql("""
				select d.id, d.ticker, d.trade_date, d.base_price
				from debates d
				left join debate_outcomes o on o.debate_id = d.id and o.horizon_days = :h
				where d.status = 'COMPLETED' and d.trade_date is not null and o.debate_id is null
				""")
				.param("h", horizon)
				.query((rs, i) -> new Pending(rs.getObject("id", UUID.class), rs.getString("ticker"),
						rs.getObject("trade_date", LocalDate.class), rs.getBigDecimal("base_price")))
				.list().stream()
				// 주말만 뺀 예상일도 안 지났으면 시세를 부를 필요가 없다
				.filter(p -> !ScoreRule.estimateTradingDay(p.tradeDate(), horizon).isAfter(today))
				.toList();
		int recorded = 0;
		for (Pending p : due) {
			try {
				recorded += record(p, horizon, today) ? 1 : 0;
			} catch (ApiException e) {
				log.warn("토론 결과 보류 (시세 조회 실패): debate={} {}", p.id(), e.getMessage());
			}
		}
		return recorded;
	}

	private boolean record(Pending p, int horizon, LocalDate today) {
		List<DailyClose> after = worker.dailyCloses(p.ticker(), p.tradeDate(), today).stream()
				.filter(c -> c.date().isAfter(p.tradeDate())).toList();
		if (after.size() < horizon) {
			return false;
		}
		DailyClose day = after.get(horizon - 1);
		Map<LocalDate, BigDecimal> index = worker.indexCloses(config.index(), p.tradeDate(), day.date()).stream()
				.collect(Collectors.toMap(DailyClose::date, DailyClose::close, (a, b) -> b));
		BigDecimal baseIndex = index.get(p.tradeDate());
		BigDecimal dayIndex = index.get(day.date());
		if (baseIndex == null || dayIndex == null) {
			return false;
		}
		BigDecimal stockRet = ScoreRule.returnPct(p.basePrice(), day.close());
		BigDecimal indexRet = ScoreRule.returnPct(baseIndex, dayIndex);
		jdbc.sql("""
				insert into debate_outcomes (debate_id, horizon_days, scored_trade_date, stock_return, index_return, excess_return)
				values (:id, :h, :day, :s, :i, :e)
				on conflict (debate_id, horizon_days) do nothing
				""")
				.param("id", p.id()).param("h", horizon).param("day", day.date()).param("s", stockRet)
				.param("i", indexRet).param("e", stockRet.subtract(indexRet))
				.update();
		return true;
	}
}

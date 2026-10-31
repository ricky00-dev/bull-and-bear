package com.bullbear.api.experiment;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.scoring.ScoreRule;

/**
 * AI 성적표: 전향 운용 토론의 실제 결과로 토론 판정(조건 A)과 단일 판정(조건 B), 기준선을 같은 규칙으로 채점한다.
 * 기본은 정식 운용(experiment.start 이후)만 센다. 예비 운용은 엔진이 달라 실험 숫자에 섞지 않는다.
 */
@Service
public class ReportService {

	/** 맞힌 수 / 채점된 수 */
	public record Rate(int hits, int n) {
	}

	public record Distribution(int buy, int hold, int sell) {
	}

	/**
	 * @param debate 토론 판정, 채점된 전체
	 * @param debatePaired 단일 판정이 있는 토론만 (단일과 같은 문제로 비교)
	 * @param single 단일 판정
	 */
	public record Horizon(int days, Rate debate, Rate debatePaired, Rate single, Rate alwaysHold, Rate alwaysBuy,
			Rate alwaysSell, Distribution debateDecisions, Distribution singleDecisions) {
	}

	/** 사람 판정과 그 토론의 AI 판정을 같은 7거래일 결과로 채점한 것 */
	public record Visitors(int n, int userHits, int aiHits) {
	}

	/**
	 * @param official true면 정식 운용만, false면 예비 운용 포함
	 * @param from 집계에 들어간 첫 토론일 (없으면 null)
	 * @param to 마지막 채점일 (없으면 null)
	 */
	public record Report(boolean official, LocalDate start, LocalDate from, LocalDate to, int stocks,
			BigDecimal holdBand, List<Horizon> horizons, Visitors visitors) {
	}

	private record Row(BigDecimal excess, String debate, String single) {
	}

	private final JdbcClient jdbc;
	private final LocalDate start;
	private final BigDecimal band;

	ReportService(JdbcClient jdbc, BullbearProperties properties) {
		this.jdbc = jdbc;
		this.start = properties.experiment().start();
		this.band = properties.scoring().holdBand();
	}

	public Report report(boolean official) {
		LocalDate since = official ? start : LocalDate.of(2000, 1, 1);
		List<Horizon> horizons = new ArrayList<>();
		for (int days : new int[] { 7, 3 }) {
			horizons.add(horizon(days, since));
		}
		var range = jdbc.sql("""
				select min(d.trade_date), max(o.scored_trade_date), count(distinct d.ticker)
				from debates d join debate_outcomes o on o.debate_id = d.id
				where d.origin = 'SCHEDULED' and d.trade_date >= :since
				""")
				.param("since", since)
				.query((rs, i) -> new Object[] { rs.getObject(1, LocalDate.class), rs.getObject(2, LocalDate.class),
						rs.getInt(3) })
				.single();
		return new Report(official, start, (LocalDate) range[0], (LocalDate) range[1], (int) range[2], band, horizons,
				visitors(since));
	}

	private Horizon horizon(int days, LocalDate since) {
		List<Row> rows = jdbc.sql("""
				select o.excess_return, v.decision, s.decision
				from debates d
				join debate_outcomes o on o.debate_id = d.id and o.horizon_days = :h
				join moderator_verdicts v on v.debate_id = d.id
				left join single_verdicts s on s.debate_id = d.id and s.status = 'COMPLETED'
				where d.origin = 'SCHEDULED' and d.trade_date >= :since
				""")
				.param("h", days).param("since", since)
				.query((rs, i) -> new Row(rs.getBigDecimal(1), rs.getString(2), rs.getString(3)))
				.list();
		List<Row> paired = rows.stream().filter(r -> r.single() != null).toList();
		return new Horizon(days,
				rate(rows, Row::debate), rate(paired, Row::debate), rate(paired, Row::single),
				rate(rows, r -> "HOLD"), rate(rows, r -> "BUY"), rate(rows, r -> "SELL"),
				distribution(rows, Row::debate), distribution(paired, Row::single));
	}

	private Rate rate(List<Row> rows, java.util.function.Function<Row, String> decision) {
		int hits = (int) rows.stream().filter(r -> ScoreRule.hit(decision.apply(r), r.excess(), band)).count();
		return new Rate(hits, rows.size());
	}

	private static Distribution distribution(List<Row> rows, java.util.function.Function<Row, String> decision) {
		return new Distribution(count(rows, decision, "BUY"), count(rows, decision, "HOLD"), count(rows, decision, "SELL"));
	}

	private static int count(List<Row> rows, java.util.function.Function<Row, String> decision, String value) {
		return (int) rows.stream().filter(r -> value.equals(decision.apply(r))).count();
	}

	private Visitors visitors(LocalDate since) {
		return jdbc.sql("""
				select count(*), count(*) filter (where s.user_hit), count(*) filter (where s.moderator_hit)
				from judgment_scores s
				join judgments j on j.id = s.judgment_id
				join debates d on d.id = j.debate_id
				where s.status = 'SCORED' and s.horizon_days = 7 and d.trade_date >= :since
				""")
				.param("since", since)
				.query((rs, i) -> new Visitors(rs.getInt(1), rs.getInt(2), rs.getInt(3)))
				.single();
	}
}

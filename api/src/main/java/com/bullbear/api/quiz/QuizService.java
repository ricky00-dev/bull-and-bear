package com.bullbear.api.quiz;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.bullbear.api.chart.ChartService;
import com.bullbear.api.chart.ChartService.ChartResponse;
import com.bullbear.api.chart.ChartService.Mark;
import com.bullbear.api.chart.ChartService.Point;
import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.judgment.Decision;
import com.bullbear.api.scoring.ScoreRule;
import com.bullbear.api.user.User;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * 타임머신 퀴즈. 7거래일 결과가 이미 나온 토론을 종목·날짜를 가린 채 다시 보여주고, 답하면 바로 공개한다.
 *
 * 문제는 결과를 보고 고르지 않는다 (AI가 맞힌 문제만 내면 관람객을 속이는 것). 무작위로 내되,
 * 이미 풀었거나 실제로 판정했던 토론은 뒤로 미룬다. 기록은 실제 판정 통계와 섞지 않는다.
 */
@Service
public class QuizService {

	static final int ROUND_SIZE = 5;

	/** 문제 상태. 답하기 전에는 decision 등이 null */
	public record QuestionStatus(int idx, Decision decision, Boolean userHit, Boolean moderatorHit) {
	}

	/** 답하기 전 문제. 종목명·날짜·가격은 가린다 */
	public record Question(int idx, String sector, String period, List<JsonNode> statements, ChartResponse chart) {
	}

	/** @param current 아직 안 푼 첫 문제. 다 풀었으면 null */
	public record RoundView(UUID id, int total, int userScore, int aiScore, List<QuestionStatus> questions,
			Question current) {
	}

	public record Answer(int idx, String stockName, String ticker, LocalDate baseDate, Decision decision,
			Decision correct, boolean userHit, Decision moderatorDecision, String moderatorReasoning,
			boolean moderatorHit, BigDecimal stockReturn, BigDecimal indexReturn, BigDecimal excessReturn,
			BigDecimal holdBand, ChartResponse chart, boolean last) {
	}

	private record Row(int idx, UUID debateId, String decision, Boolean userHit, Boolean moderatorHit) {
	}

	private final JdbcClient jdbc;
	private final DebateService debates;
	private final ChartService charts;
	private final ObjectMapper json;
	private final BigDecimal holdBand;
	private final Clock clock;

	public QuizService(JdbcClient jdbc, DebateService debates, ChartService charts, ObjectMapper json,
			BullbearProperties properties, Clock clock) {
		this.jdbc = jdbc;
		this.debates = debates;
		this.charts = charts;
		this.json = json;
		this.holdBand = properties.scoring().holdBand();
		this.clock = clock;
	}

	@Transactional
	public RoundView start(User user) {
		List<UUID> picked = jdbc.sql("""
				select d.id
				from debates d
				join debate_outcomes o on o.debate_id = d.id
				join moderator_verdicts v on v.debate_id = d.id
				where d.status = 'COMPLETED'
				order by (exists (select 1 from quiz_questions q join quiz_rounds r on r.id = q.round_id
				                  where r.user_id = :userId and q.debate_id = d.id)
				          or exists (select 1 from judgments j where j.user_id = :userId and j.debate_id = d.id)),
				         random()
				limit :n
				""")
				.param("userId", user.getId()).param("n", ROUND_SIZE)
				.query(UUID.class).list();
		if (picked.isEmpty()) {
			throw new ApiException(ErrorCode.QUIZ_EMPTY, "아직 결과가 나온 토론이 없어요. 토론 7거래일 뒤부터 퀴즈가 열려요");
		}
		UUID id = UUID.randomUUID();
		jdbc.sql("insert into quiz_rounds (id, user_id, created_at) values (:id, :u, :t)")
				.param("id", id).param("u", user.getId()).param("t", java.sql.Timestamp.from(clock.instant()))
				.update();
		for (int i = 0; i < picked.size(); i++) {
			jdbc.sql("insert into quiz_questions (round_id, idx, debate_id) values (:r, :i, :d)")
					.param("r", id).param("i", i).param("d", picked.get(i)).update();
		}
		return round(user, id);
	}

	public RoundView round(User user, UUID roundId) {
		List<Row> rows = rows(user, roundId);
		List<QuestionStatus> statuses = rows.stream()
				.map(r -> new QuestionStatus(r.idx(), r.decision() == null ? null : Decision.valueOf(r.decision()),
						r.userHit(), r.moderatorHit()))
				.toList();
		int mine = (int) rows.stream().filter(r -> Boolean.TRUE.equals(r.userHit())).count();
		int ai = (int) rows.stream().filter(r -> Boolean.TRUE.equals(r.moderatorHit())).count();
		Question current = rows.stream().filter(r -> r.decision() == null).findFirst().map(this::question).orElse(null);
		return new RoundView(roundId, rows.size(), mine, ai, statuses, current);
	}

	@Transactional
	public Answer answer(User user, UUID roundId, int idx, Decision decision) {
		Row row = rows(user, roundId).stream().filter(r -> r.idx() == idx).findFirst()
				.orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "문제를 찾을 수 없습니다"));
		Debate d = debates.get(row.debateId());
		var outcome = jdbc.sql("""
				select o.stock_return, o.index_return, o.excess_return, v.decision, v.reasoning
				from debate_outcomes o join moderator_verdicts v on v.debate_id = o.debate_id
				where o.debate_id = :id
				""")
				.param("id", d.getId())
				.query((rs, i) -> new Object[] { rs.getBigDecimal(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
						rs.getString(4), rs.getString(5) })
				.single();
		BigDecimal excess = (BigDecimal) outcome[2];
		String moderator = (String) outcome[3];
		boolean userHit = ScoreRule.hit(decision.name(), excess, holdBand);
		boolean moderatorHit = ScoreRule.hit(moderator, excess, holdBand);

		int updated = jdbc.sql("""
				update quiz_questions set decision = :dec, user_hit = :uh, moderator_hit = :mh, answered_at = :t
				where round_id = :r and idx = :i and decision is null
				""")
				.param("dec", decision.name()).param("uh", userHit).param("mh", moderatorHit)
				.param("t", java.sql.Timestamp.from(clock.instant())).param("r", roundId).param("i", idx)
				.update();
		if (updated == 0) {
			throw new ApiException(ErrorCode.ALREADY_ANSWERED, "이미 답한 문제예요");
		}
		boolean last = rows(user, roundId).stream().noneMatch(r -> r.decision() == null);
		return new Answer(idx, d.getStockName(), d.getTicker(), d.getTradeDate(), decision, correct(excess), userHit,
				Decision.valueOf(moderator), (String) outcome[4], moderatorHit, (BigDecimal) outcome[0],
				(BigDecimal) outcome[1], excess, holdBand, charts.build(d), last);
	}

	private Decision correct(BigDecimal excess) {
		if (excess.compareTo(holdBand) > 0) {
			return Decision.BUY;
		}
		return excess.compareTo(holdBand.negate()) < 0 ? Decision.SELL : Decision.HOLD;
	}

	private List<Row> rows(User user, UUID roundId) {
		List<Row> rows = jdbc.sql("""
				select q.idx, q.debate_id, q.decision, q.user_hit, q.moderator_hit
				from quiz_questions q join quiz_rounds r on r.id = q.round_id
				where q.round_id = :r and r.user_id = :u
				order by q.idx
				""")
				.param("r", roundId).param("u", user.getId())
				.query((rs, i) -> new Row(rs.getInt(1), rs.getObject(2, UUID.class), rs.getString(3),
						(Boolean) rs.getObject(4), (Boolean) rs.getObject(5)))
				.list();
		if (rows.isEmpty()) {
			throw new ApiException(ErrorCode.NOT_FOUND, "퀴즈를 찾을 수 없습니다");
		}
		return rows;
	}

	/** 답하기 전 문제: 종목명·종목코드는 "이 회사"로, 차트는 판정일까지만, 가격·날짜는 뺀다 */
	private Question question(Row row) {
		Debate d = debates.get(row.debateId());
		List<JsonNode> statements = debates.acceptedStatements(d.getId()).stream()
				.map(payload -> mask(json.readTree(payload), d))
				.toList();
		ChartResponse full = charts.build(d);
		List<Point> before = full.points().stream()
				.filter(p -> !p.date().isAfter(full.baseDate()))
				.map(p -> new Point(null, null, p.stockPct(), p.indexPct()))
				.toList();
		List<Mark> marks = full.marks().stream().map(m -> new Mark(m.horizonDays(), null, false)).toList();
		return new Question(row.idx(), QuizHints.sector(d.getTicker()), QuizHints.period(d.getTradeDate()), statements,
				new ChartResponse(null, null, full.holdBand(), before, marks));
	}

	private JsonNode mask(JsonNode event, Debate d) {
		ObjectNode st = (ObjectNode) event.path("statement");
		for (String field : List.of("claim", "argument")) {
			if (st.has(field)) {
				st.put(field, QuizHints.mask(st.get(field).asString(), d.getStockName(), d.getTicker()));
			}
		}
		for (JsonNode e : st.path("evidence")) {
			if (e.has("interpretation")) {
				((ObjectNode) e).put("interpretation",
						QuizHints.mask(e.get("interpretation").asString(), d.getStockName(), d.getTicker()));
			}
		}
		return event;
	}
}

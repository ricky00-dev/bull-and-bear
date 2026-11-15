package com.bullbear.api.admin;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;
import com.bullbear.api.ops.OpsHealthController;

/**
 * 관리자 화면 숫자. 운영 중 "지금 돈이 얼마나 나가는지, 토론이 잘 끝나는지"를 한눈에 보려는 용도라
 * 테이블을 직접 집계한다. 날짜는 모두 KST(debate_day 기준).
 *
 * 비용은 확정된 값(cost_usd)만 더한다. 진행 중이거나 사용량 없이 실패한 토론은 unknown으로 따로 센다.
 */
@Service
@Transactional(readOnly = true)
public class AdminService {

	private final JdbcClient jdbc;
	private final Clock clock;
	private final BullbearProperties properties;
	private final OpsHealthController health;

	AdminService(JdbcClient jdbc, Clock clock, BullbearProperties properties, OpsHealthController health) {
		this.jdbc = jdbc;
		this.clock = clock;
		this.properties = properties;
		this.health = health;
	}

	public Map<String, Object> overview(int days) {
		LocalDate today = LocalDate.now(clock);
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("today", today.toString());
		out.put("health", health.health().getBody());
		out.put("workerMode", properties.worker().mode());
		out.put("budget", budget(today));
		out.put("periods", List.of(
				period("오늘", today, today),
				period("최근 7일", today.minusDays(6), today),
				period("이번 달", today.withDayOfMonth(1), today),
				period("전체", LocalDate.of(2000, 1, 1), today)));
		out.put("daily", daily(today.minusDays(days - 1L), today));
		out.put("models", models(today.minusDays(29)));
		out.put("failures", failures(today.minusDays(6)));
		out.put("stocks", stocks());
		out.put("users", users(today));
		out.put("scoring", scoring());
		return out;
	}

	/** 오늘 비용 상한별 사용량. 상한 판단과 똑같이 사용량 모르는 토론은 추정치로 센다 */
	private Map<String, Object> budget(LocalDate today) {
		var b = properties.budget();
		BigDecimal e = b.estimateUsd();
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("estimateUsd", e);
		out.put("perUserDailyDebates", b.perUserDailyDebates());
		out.put("user", cap(spent(today, "USER", e), b.userDailyUsd()));
		BigDecimal singles = jdbc.sql("select coalesce(sum(coalesce(cost_usd, :e)), 0) from single_verdict_attempts where run_day = :d")
				.param("e", e).param("d", today).query(BigDecimal.class).single();
		Map<String, Object> scheduled = cap(spent(today, "SCHEDULED", e).add(singles), properties.forwardRun().dailyUsd());
		scheduled.put("enabled", properties.forwardRun().enabled());
		out.put("scheduled", scheduled);
		out.put("backtest", cap(spent(today, "BACKTEST", e), properties.backtest().dailyUsd()));
		return out;
	}

	private BigDecimal spent(LocalDate day, String origin, BigDecimal estimate) {
		return jdbc.sql("""
				select coalesce(sum(coalesce(cost_usd, :e)), 0) from debates
				where debate_day = :d and origin = :o and worker_debate_id is not null
				""").param("e", estimate).param("d", day).param("o", origin).query(BigDecimal.class).single();
	}

	private static Map<String, Object> cap(BigDecimal spent, BigDecimal limit) {
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("spentUsd", spent);
		m.put("limitUsd", limit);
		return m;
	}

	private Map<String, Object> period(String label, LocalDate from, LocalDate to) {
		Map<String, Object> m = new LinkedHashMap<>(jdbc.sql("""
				select count(*) as "debates",
				       count(*) filter (where status = 'COMPLETED') as "completed",
				       count(*) filter (where status = 'FAILED') as "failed",
				       count(*) filter (where status = 'RUNNING') as "running",
				       coalesce(sum(cost_usd), 0) as "costUsd",
				       count(*) filter (where cost_usd is null and worker_debate_id is not null) as "unknownCost",
				       avg(cost_usd) filter (where status = 'COMPLETED' and cost_usd > 0) as "avgCostUsd",
				       avg(extract(epoch from completed_at - created_at)) filter (where status = 'COMPLETED') as "avgSeconds",
				       coalesce(sum(input_tokens), 0) as "inputTokens",
				       coalesce(sum(output_tokens), 0) as "outputTokens"
				from debates where debate_day between :f and :t
				""").param("f", from).param("t", to).query().singleRow());
		m.put("label", label);
		m.put("judgments", jdbc.sql("""
				select count(*) from judgments
				where (created_at at time zone 'Asia/Seoul')::date between :f and :t
				""").param("f", from).param("t", to).query(Long.class).single());
		return m;
	}

	private List<Map<String, Object>> daily(LocalDate from, LocalDate to) {
		return jdbc.sql("""
				select to_char(g.day, 'YYYY-MM-DD') as "day",
				       count(d.id) as "debates",
				       count(d.id) filter (where d.status = 'FAILED') as "failed",
				       coalesce(sum(d.cost_usd) filter (where d.origin = 'USER'), 0) as "userUsd",
				       coalesce(sum(d.cost_usd) filter (where d.origin = 'SCHEDULED'), 0) as "scheduledUsd",
				       coalesce(sum(d.cost_usd) filter (where d.origin = 'BACKTEST'), 0) as "backtestUsd",
				       (select count(*) from judgments j where (j.created_at at time zone 'Asia/Seoul')::date = g.day::date) as "judgments"
				from generate_series(cast(:f as date), cast(:t as date), interval '1 day') g(day)
				left join debates d on d.debate_day = g.day::date
				group by g.day order by g.day
				""").param("f", from).param("t", to).query().listOfRows();
	}

	/** 모델별 토큰과 캐시 적중. 워커가 완료·실패 이벤트에 실어 보낸 usage.calls 원본에서 센다 */
	private List<Map<String, Object>> models(LocalDate from) {
		return jdbc.sql("""
				select c->>'model' as "model",
				       count(distinct e.debate_id) as "debates",
				       sum(coalesce((c->>'input_tokens')::bigint, 0)) as "inputTokens",
				       sum(coalesce((c->>'output_tokens')::bigint, 0)) as "outputTokens",
				       sum(coalesce((c->>'cache_read_input_tokens')::bigint, 0)) as "cacheReadTokens",
				       sum(coalesce((c->>'cache_creation_input_tokens')::bigint, 0)) as "cacheWriteTokens"
				from debate_events e
				join debates d on d.id = e.debate_id
				cross join lateral jsonb_array_elements(case when jsonb_typeof(e.payload->'usage'->'calls') = 'array'
				                                             then e.payload->'usage'->'calls' else '[]'::jsonb end) c
				where e.type in ('debate_completed', 'debate_failed') and d.debate_day >= :f
				group by 1 order by 2 desc
				""").param("f", from).query().listOfRows();
	}

	private List<Map<String, Object>> failures(LocalDate from) {
		return jdbc.sql("""
				select coalesce(e.payload->'error'->>'code', '알 수 없음') as "code",
				       max(e.payload->'error'->>'message') as "message",
				       count(*) as "count", to_char(max(e.created_at) at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "lastAt"
				from debate_events e join debates d on d.id = e.debate_id
				where e.type = 'debate_failed' and d.debate_day >= :f
				group by 1 order by 3 desc
				""").param("f", from).query().listOfRows();
	}

	private List<Map<String, Object>> stocks() {
		return jdbc.sql("""
				select d.ticker as "ticker", max(d.stock_name) as "name", count(*) as "debates",
				       coalesce(sum(d.cost_usd), 0) as "costUsd",
				       (select count(*) from judgments j join debates x on x.id = j.debate_id where x.ticker = d.ticker) as "judgments",
				       to_char(max(d.created_at) at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "lastAt"
				from debates d group by d.ticker order by 3 desc, 6 desc limit 15
				""").query().listOfRows();
	}

	private Map<String, Object> users(LocalDate today) {
		Map<String, Object> m = new LinkedHashMap<>(jdbc.sql("""
				select count(*) as "total",
				       count(*) filter (where not guest) as "members",
				       count(*) filter (where guest) as "guests",
				       count(*) filter (where nickname is not null) as "withNickname",
				       count(*) filter (where (created_at at time zone 'Asia/Seoul')::date = :d) as "newToday"
				from users
				""").param("d", today).query().singleRow());
		m.put("activeToday", jdbc.sql("""
				select count(distinct user_id) from judgments where (created_at at time zone 'Asia/Seoul')::date = :d
				""").param("d", today).query(Long.class).single());
		m.put("top", jdbc.sql("""
				select u.id::text as "userId", u.nickname as "nickname", u.guest as "guest",
				       count(j.id) as "judgments",
				       count(s.id) filter (where s.status = 'SCORED' and s.horizon_days = 7) as "scored",
				       count(s.id) filter (where s.user_hit and s.horizon_days = 7) as "hits",
				       to_char(max(j.created_at) at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "lastAt"
				from users u join judgments j on j.user_id = u.id
				left join judgment_scores s on s.judgment_id = j.id
				group by u.id order by 4 desc, 7 desc limit 10
				""").query().listOfRows());
		return m;
	}

	/** 채점 끝난 판정의 적중. 같은 판정을 두고 사용자와 중재자를 나란히 센다 */
	private List<Map<String, Object>> scoring() {
		return jdbc.sql("""
				select horizon_days as "days",
				       count(*) filter (where status = 'SCORED') as "scored",
				       count(*) filter (where status = 'PENDING') as "pending",
				       count(*) filter (where user_hit) as "userHits",
				       count(*) filter (where moderator_hit) as "moderatorHits"
				from judgment_scores group by 1 order by 1
				""").query().listOfRows();
	}

	public List<Map<String, Object>> debates(int limit, String status, String origin) {
		return debates(limit, status, origin, null);
	}

	private List<Map<String, Object>> debates(int limit, String status, String origin, UUID id) {
		return jdbc.sql("""
				select d.id::text as "id", d.ticker as "ticker", d.stock_name as "name", d.origin as "origin",
				       d.status as "status", to_char(d.created_at at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "createdAt", to_char(d.completed_at at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "completedAt",
				       extract(epoch from d.completed_at - d.created_at) as "seconds",
				       to_char(d.data_date, 'YYYY-MM-DD') as "dataDate", d.cost_usd as "costUsd",
				       d.input_tokens as "inputTokens", d.output_tokens as "outputTokens",
				       v.decision as "verdict", v.confidence as "confidence",
				       (select count(*) from judgments j where j.debate_id = d.id) as "judgments",
				       u.nickname as "requesterNickname", u.guest as "requesterGuest", d.requested_by::text as "requesterId",
				       (select e.payload->'error'->>'message' from debate_events e
				        where e.debate_id = d.id and e.type = 'debate_failed' order by e.seq desc limit 1) as "error"
				from debates d
				left join moderator_verdicts v on v.debate_id = d.id
				left join users u on u.id = d.requested_by
				where (cast(:status as text) is null or d.status = :status)
				  and (cast(:origin as text) is null or d.origin = :origin)
				  and (cast(:id as uuid) is null or d.id = :id)
				order by d.created_at desc limit :limit
				""").param("status", status).param("origin", origin).param("id", id).param("limit", limit)
				.query().listOfRows();
	}

	/** 토론 한 건의 이벤트 흐름. 어느 단계에서 오래 걸렸는지, 몇 번 다시 썼는지 본다 */
	public Map<String, Object> debate(UUID id) {
		var rows = debates(1, null, null, id);
		if (rows.isEmpty()) {
			throw new ApiException(ErrorCode.NOT_FOUND, "토론을 찾을 수 없습니다");
		}
		Map<String, Object> out = new LinkedHashMap<>(rows.get(0));
		out.put("events", jdbc.sql("""
				select e.seq as "seq", e.type as "type", to_char(e.created_at at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "at",
				       e.payload->>'side' as "side", e.payload->>'round' as "round",
				       e.payload->>'attempt' as "attempt", e.payload->>'tool' as "tool"
				from debate_events e where e.debate_id = :id order by e.seq
				""").param("id", id).query().listOfRows());
		out.put("usage", jdbc.sql("""
				select (e.payload->'usage')::text from debate_events e
				where e.debate_id = :id and e.type in ('debate_completed', 'debate_failed') order by e.seq desc limit 1
				""").param("id", id).query(String.class).optional().orElse(null));
		out.put("judgmentList", jdbc.sql("""
				select j.decision as "decision", j.confidence as "confidence", to_char(j.created_at at time zone 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS') as "at", u.nickname as "nickname"
				from judgments j join users u on u.id = j.user_id where j.debate_id = :id order by j.created_at
				""").param("id", id).query().listOfRows());
		return out;
	}
}

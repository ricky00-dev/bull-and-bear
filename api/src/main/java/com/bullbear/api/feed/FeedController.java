package com.bullbear.api.feed;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.auth.CurrentUser;
import com.bullbear.api.user.User;

/**
 * 홈 "오늘의 토론": 검색 없이 바로 볼 수 있는 토론 목록.
 *
 * 가장 최근 데이터 기준일의 토론만 보여 준다. 이 토론들은 지금 새로 만들어도 같은 데이터라 재사용되므로
 * 누르면 기다리지 않는다 (docs/ARCHITECTURE.md ADR-1). 워커를 부르지 않고 DB 쿼리 한 번으로 만든다.
 * 중재자 판정은 봉인 대상이라 내보내지 않는다.
 */
@RestController
@RequestMapping("/api/feed")
public class FeedController {

	/**
	 * @param scheduled 매일 장 마감 뒤 자동으로 토론하는 종목 (전향 운용)
	 * @param judged 이 토론에 판정한 사람 수
	 * @param mine 내가 이미 판정했는지. true면 공개 화면으로 바로 간다
	 */
	public record FeedItem(UUID debateId, String ticker, String stockName, String status, boolean scheduled,
			LocalDate dataDate, Instant createdAt, int judged, boolean mine) {
	}

	public record FeedResponse(LocalDate dataDate, List<FeedItem> items) {
	}

	private static final String SQL = """
			with latest as (select max(data_date) as d from debates where status <> 'FAILED')
			select d.id, d.ticker, d.stock_name, d.status, d.origin = 'SCHEDULED' as scheduled, d.data_date,
			       d.created_at, count(j.id) as judged, coalesce(bool_or(j.user_id = :userId), false) as mine
			from debates d
			join latest on d.data_date = latest.d
			left join judgments j on j.debate_id = d.id
			where d.status <> 'FAILED'
			group by d.id
			order by (d.status = 'RUNNING') desc, count(j.id) desc, d.created_at desc
			limit 30
			""";

	private final JdbcClient jdbc;

	FeedController(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	/** 진행 중 → 많이 판정한 순 → 최신 순 */
	@GetMapping
	public FeedResponse feed(@CurrentUser User user) {
		List<FeedItem> items = jdbc.sql(SQL).param("userId", user.getId())
				.query((rs, i) -> new FeedItem(rs.getObject("id", UUID.class), rs.getString("ticker"),
						rs.getString("stock_name"), rs.getString("status"), rs.getBoolean("scheduled"),
						rs.getObject("data_date", LocalDate.class), rs.getTimestamp("created_at").toInstant(),
						rs.getInt("judged"), rs.getBoolean("mine")))
				.list();
		return new FeedResponse(items.isEmpty() ? null : items.get(0).dataDate(), items);
	}
}

package com.bullbear.api.quiz;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import com.bullbear.api.config.ClockConfig;
import com.bullbear.api.user.User;

/**
 * 타임머신 퀴즈 랭킹. 전시장에서 관람객끼리 겨루는 용도.
 *
 * 맞힌 문제 수로 줄 세우고, 같으면 덜 풀고 맞힌 사람(적중률이 높은 사람), 그래도 같으면 먼저 도달한 사람이 위.
 * 순위는 공동 순위(1, 1, 3)로 매긴다.
 */
@Service
public class QuizRanking {

	public static final int TOP = 20;

	public enum Scope {
		TODAY, ALL
	}

	/** @param name 닉네임, 없으면 "게스트 #abcd" (카카오 가입자는 "회원 #abcd") */
	public record Entry(int rank, String name, int hits, int answered, boolean me) {
	}

	/** @param mine 내가 한 문제도 안 풀었으면 null */
	public record Ranking(Scope scope, int players, List<Entry> top, Entry mine) {
	}

	private record Row(UUID userId, String nickname, boolean guest, int hits, int answered) {
	}

	private final JdbcClient jdbc;
	private final Clock clock;

	QuizRanking(JdbcClient jdbc, Clock clock) {
		this.jdbc = jdbc;
		this.clock = clock;
	}

	public Ranking ranking(User user, Scope scope) {
		Instant since = scope == Scope.TODAY
				? LocalDate.now(clock).atStartOfDay(ClockConfig.KST).toInstant()
				: Instant.EPOCH;
		List<Row> rows = jdbc.sql("""
				select r.user_id, u.nickname, u.guest,
				       count(*) filter (where q.user_hit) as hits,
				       count(*) as answered
				from quiz_questions q
				join quiz_rounds r on r.id = q.round_id
				join users u on u.id = r.user_id
				where q.decision is not null and q.answered_at >= :since
				group by r.user_id, u.nickname, u.guest
				order by hits desc, answered asc, max(q.answered_at) asc
				""")
				.param("since", Timestamp.from(since))
				.query((rs, i) -> new Row(rs.getObject(1, UUID.class), rs.getString(2), rs.getBoolean(3), rs.getInt(4), rs.getInt(5)))
				.list();

		List<Entry> top = new ArrayList<>();
		Entry mine = null;
		int rank = 0;
		Row prev = null;
		for (int i = 0; i < rows.size(); i++) {
			Row r = rows.get(i);
			if (prev == null || prev.hits() != r.hits() || prev.answered() != r.answered()) {
				rank = i + 1;
			}
			prev = r;
			boolean me = r.userId().equals(user.getId());
			Entry e = new Entry(rank, displayName(r.nickname(), r.guest(), r.userId()), r.hits(), r.answered(), me);
			if (i < TOP) {
				top.add(e);
			}
			if (me) {
				mine = e;
			}
		}
		return new Ranking(scope, rows.size(), top, mine);
	}

	static String displayName(String nickname, boolean guest, UUID userId) {
		if (nickname != null) {
			return nickname;
		}
		return (guest ? "게스트 #" : "회원 #") + userId.toString().substring(0, 4);
	}
}

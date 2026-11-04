package com.bullbear.api.auth;

import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.bullbear.api.user.AccountMerge;
import com.bullbear.api.user.User;
import com.bullbear.api.user.UserRepository;

/**
 * 카카오 로그인. 게스트 기록은 버리지 않는다.
 * <ul>
 * <li>처음 온 카카오 계정: 지금 게스트 계정에 카카오를 연결한다 (기록 그대로)</li>
 * <li>이미 가입한 카카오 계정 (다른 기기 등): 그 계정으로 들어가고, 지금 게스트의 기록을 옮긴 뒤 게스트를 지운다</li>
 * </ul>
 * 어느 경우든 이 기기용 새 토큰을 준다. 다른 기기의 토큰은 그대로 쓸 수 있다.
 */
@Service
public class KakaoLogin {

	public record Result(UUID userId, String token, boolean merged) {
	}

	private final UserRepository users;
	private final TokenService tokens;
	private final AccountMerge merge;
	private final JdbcClient jdbc;

	KakaoLogin(UserRepository users, TokenService tokens, AccountMerge merge, JdbcClient jdbc) {
		this.users = users;
		this.tokens = tokens;
		this.merge = merge;
		this.jdbc = jdbc;
	}

	@Transactional
	public Result login(User current, String kakaoId) {
		String token = tokens.newToken();
		var existing = users.findByKakaoId(kakaoId);
		if (existing.isEmpty()) {
			if (current.isGuest()) {
				current.linkKakao(kakaoId);
				users.saveAndFlush(current);
				addToken(current.getId(), token);
				return new Result(current.getId(), token, false);
			}
			// 다른 카카오 계정으로 로그인한 기기에서 새 카카오 계정으로 바꾼 경우
			User created = users.save(User.kakao(kakaoId, tokens.hash(token)));
			return new Result(created.getId(), token, false);
		}
		User target = existing.get();
		boolean merged = !target.getId().equals(current.getId()) && current.isGuest();
		if (merged) {
			merge.mergeGuest(current.getId(), target.getId());
		}
		addToken(target.getId(), token);
		return new Result(target.getId(), token, merged);
	}

	private void addToken(UUID userId, String token) {
		jdbc.sql("insert into auth_tokens (token_hash, user_id) values (:h, :u)")
				.param("h", tokens.hash(token)).param("u", userId).update();
	}
}

package com.bullbear.api.user;

import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 게스트로 쌓은 기록을 이미 가입한 계정으로 옮긴다 (다른 기기에서 가입한 뒤 이 기기에서 카카오 로그인).
 * 같은 토론을 양쪽에서 판정했으면 가입 계정의 판정을 남긴다. 판정은 봉인 뒤 바꿀 수 없기 때문.
 */
@Service
public class AccountMerge {

	private final JdbcClient jdbc;
	private final AccountDeletion deletion;

	AccountMerge(JdbcClient jdbc, AccountDeletion deletion) {
		this.jdbc = jdbc;
		this.deletion = deletion;
	}

	@Transactional
	public void mergeGuest(UUID guest, UUID into) {
		jdbc.sql("""
				update judgments set user_id = :to
				where user_id = :from and debate_id not in (select debate_id from judgments where user_id = :to)""")
				.param("from", guest).param("to", into).update();
		jdbc.sql("update quiz_rounds set user_id = :to where user_id = :from").param("from", guest).param("to", into).update();
		jdbc.sql("update debates set requested_by = :to where requested_by = :from").param("from", guest).param("to", into).update();
		jdbc.sql("update users set nickname = (select nickname from users where id = :from) where id = :to and nickname is null")
				.param("from", guest).param("to", into).update();
		// 옮기지 못한(겹친) 판정과 게스트 계정을 지운다
		deletion.delete(guest);
	}
}

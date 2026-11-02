package com.bullbear.api.user;

import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 내 기록 삭제 (개인정보 처리방침의 삭제 요청). 판정·채점·메모·퀴즈 기록·닉네임과 계정을 지운다.
 * 내가 요청한 토론은 다른 사람도 보는 공용 기록이라 남기고, 요청자만 비운다.
 */
@Service
public class AccountDeletion {

	private final JdbcClient jdbc;

	AccountDeletion(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	@Transactional
	public void delete(UUID userId) {
		jdbc.sql("delete from judgment_scores where judgment_id in (select id from judgments where user_id = :u)")
				.param("u", userId).update();
		jdbc.sql("delete from judgments where user_id = :u").param("u", userId).update();
		jdbc.sql("delete from quiz_questions where round_id in (select id from quiz_rounds where user_id = :u)")
				.param("u", userId).update();
		jdbc.sql("delete from quiz_rounds where user_id = :u").param("u", userId).update();
		jdbc.sql("update debates set requested_by = null where requested_by = :u").param("u", userId).update();
		jdbc.sql("delete from users where id = :u").param("u", userId).update();
	}
}

package com.bullbear.api.user;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "users")
public class User {

	@Id
	private UUID id;

	@Column(nullable = false)
	private boolean guest;

	@Column(name = "token_hash", nullable = false, unique = true)
	private String tokenHash;

	private String nickname;

	@Column(name = "kakao_id")
	private String kakaoId;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected User() {
	}

	public static User guest(String tokenHash) {
		User u = new User();
		u.id = UUID.randomUUID();
		u.guest = true;
		u.tokenHash = tokenHash;
		u.createdAt = Instant.now();
		return u;
	}

	/** 게스트를 거치지 않은 카카오 계정 (다른 카카오 계정으로 쓰던 기기에서 새로 로그인) */
	public static User kakao(String kakaoId, String tokenHash) {
		User u = guest(tokenHash);
		u.linkKakao(kakaoId);
		return u;
	}

	/** 게스트 계정에 카카오를 연결한다. 판정·퀴즈 기록은 같은 계정이라 그대로 이어진다 */
	public void linkKakao(String kakaoId) {
		this.kakaoId = kakaoId;
		this.guest = false;
	}

	public UUID getId() {
		return id;
	}

	public boolean isGuest() {
		return guest;
	}

	public String getNickname() {
		return nickname;
	}

	public void setNickname(String nickname) {
		this.nickname = nickname;
	}
}

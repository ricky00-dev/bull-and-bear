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

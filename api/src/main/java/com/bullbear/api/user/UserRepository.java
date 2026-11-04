package com.bullbear.api.user;

import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface UserRepository extends JpaRepository<User, UUID> {

	/** 처음 만든 기기의 토큰(users.token_hash) 또는 카카오 로그인으로 더 발급한 토큰(auth_tokens) */
	@Query(value = """
			select u.* from users u where u.token_hash = :h
			union
			select u.* from users u join auth_tokens t on t.user_id = u.id where t.token_hash = :h""", nativeQuery = true)
	Optional<User> findByTokenHash(@Param("h") String tokenHash);

	Optional<User> findByKakaoId(String kakaoId);
}

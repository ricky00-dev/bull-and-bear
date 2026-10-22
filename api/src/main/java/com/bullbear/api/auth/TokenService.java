package com.bullbear.api.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

import org.springframework.stereotype.Component;

/**
 * 불투명 접근 토큰. 원문은 클라이언트만 갖고 서버는 해시만 저장한다.
 * 카카오 로그인을 붙일 때 JWT로 바꿀 수 있게 인증은 이 클래스와 AuthInterceptor에만 둔다.
 */
@Component
public class TokenService {

	private final SecureRandom random = new SecureRandom();

	public String newToken() {
		byte[] bytes = new byte[32];
		random.nextBytes(bytes);
		return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
	}

	public String hash(String token) {
		try {
			byte[] digest = MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8));
			return HexFormat.of().formatHex(digest);
		} catch (NoSuchAlgorithmException e) {
			throw new IllegalStateException(e);
		}
	}
}

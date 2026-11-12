package com.bullbear.api.admin;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * 관리자 화면(/api/admin/**)은 사용자 토큰 대신 X-Admin-Token 헤더로 연다.
 * 서버 설정(ADMIN_TOKEN)이 비어 있으면 관리자 API 자체가 없는 것처럼 404.
 */
@Component
public class AdminInterceptor implements HandlerInterceptor {

	static final String HEADER = "X-Admin-Token";

	private final byte[] token;

	AdminInterceptor(@Value("${bullbear.admin.token:}") String token) {
		this.token = token.isBlank() ? null : token.getBytes(StandardCharsets.UTF_8);
	}

	@Override
	public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
		if (HttpMethod.OPTIONS.matches(request.getMethod())) {
			return true;
		}
		if (token == null) {
			throw new ApiException(ErrorCode.NOT_FOUND, "없는 경로입니다");
		}
		String given = request.getHeader(HEADER);
		// 길이·내용을 시간 차로 추측하지 못하게 상수 시간 비교
		if (given == null || !MessageDigest.isEqual(token, given.getBytes(StandardCharsets.UTF_8))) {
			throw new ApiException(ErrorCode.UNAUTHORIZED, "관리자 토큰이 맞지 않아요");
		}
		return true;
	}
}

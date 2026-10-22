package com.bullbear.api.auth;

import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.user.UserRepository;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Authorization: Bearer 토큰으로 사용자를 찾는다.
 * 브라우저 EventSource는 헤더를 못 붙이므로 SSE 경로에 한해 access_token 쿼리 파라미터도 받는다.
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

	static final String USER_ATTRIBUTE = AuthInterceptor.class.getName() + ".user";

	private final UserRepository users;
	private final TokenService tokens;

	public AuthInterceptor(UserRepository users, TokenService tokens) {
		this.users = users;
		this.tokens = tokens;
	}

	@Override
	public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
		if (HttpMethod.OPTIONS.matches(request.getMethod())) {
			return true; // CORS preflight
		}
		String token = extract(request);
		if (token == null) {
			throw new ApiException(ErrorCode.UNAUTHORIZED, "로그인이 필요합니다");
		}
		var user = users.findByTokenHash(tokens.hash(token))
				.orElseThrow(() -> new ApiException(ErrorCode.UNAUTHORIZED, "유효하지 않은 토큰입니다"));
		request.setAttribute(USER_ATTRIBUTE, user);
		return true;
	}

	private String extract(HttpServletRequest request) {
		String header = request.getHeader("Authorization");
		if (header != null && header.startsWith("Bearer ")) {
			return header.substring(7).trim();
		}
		if (request.getRequestURI().endsWith("/stream")) {
			return request.getParameter("access_token");
		}
		return null;
	}
}

package com.bullbear.api.auth;

import java.net.URI;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 카카오 로그인 (카카오 developers 앱). 키가 비어 있으면 로그인 버튼이 "준비 중"으로 보인다.
 *
 * @param restKey 앱의 REST API 키 (인가 요청의 client_id). 브라우저 주소에도 드러나는 값이라 비밀은 아니다
 * @param clientSecret 앱 보안 설정에서 클라이언트 시크릿을 켰을 때만. 이 값은 비밀이다
 * @param authUrl 토큰 발급 서버. 테스트에서만 바꾼다
 * @param apiUrl 사용자 정보 서버. 테스트에서만 바꾼다
 */
@ConfigurationProperties("bullbear.kakao")
public record KakaoProperties(String restKey, String clientSecret, URI authUrl, URI apiUrl) {

	public boolean enabled() {
		return restKey != null && !restKey.isBlank();
	}
}

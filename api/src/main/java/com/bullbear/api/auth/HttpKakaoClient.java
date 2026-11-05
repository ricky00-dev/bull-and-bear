package com.bullbear.api.auth;

import java.time.Duration;

import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.fasterxml.jackson.annotation.JsonProperty;

/** 카카오 REST API: 인가 코드 → 액세스 토큰 → 회원번호. 카카오 액세스 토큰은 쓰고 버린다 (저장하지 않음). */
@Component
class HttpKakaoClient implements KakaoClient {

	record TokenResponse(@JsonProperty("access_token") String accessToken) {
	}

	record UserResponse(Long id) {
	}

	private static final Duration TIMEOUT = Duration.ofSeconds(10);

	private final WebClient http;
	private final KakaoProperties properties;

	HttpKakaoClient(WebClient.Builder builder, KakaoProperties properties) {
		this.http = builder.build();
		this.properties = properties;
	}

	@Override
	public String userId(String code, String redirectUri) {
		var form = new LinkedMultiValueMap<String, String>();
		form.add("grant_type", "authorization_code");
		form.add("client_id", properties.restKey());
		form.add("redirect_uri", redirectUri);
		form.add("code", code);
		if (properties.clientSecret() != null && !properties.clientSecret().isBlank()) {
			form.add("client_secret", properties.clientSecret());
		}
		try {
			TokenResponse token = http.post().uri(properties.authUrl().resolve("/oauth/token"))
					.contentType(MediaType.APPLICATION_FORM_URLENCODED)
					.body(BodyInserters.fromFormData(form))
					.retrieve().bodyToMono(TokenResponse.class).block(TIMEOUT);
			if (token == null || token.accessToken() == null) {
				throw failed();
			}
			UserResponse user = http.get().uri(properties.apiUrl().resolve("/v2/user/me"))
					.header("Authorization", "Bearer " + token.accessToken())
					.retrieve().bodyToMono(UserResponse.class).block(TIMEOUT);
			if (user == null || user.id() == null) {
				throw failed();
			}
			return String.valueOf(user.id());
		} catch (WebClientResponseException e) {
			// 만료·재사용된 인가 코드, 등록되지 않은 Redirect URI 등
			throw failed();
		} catch (WebClientRequestException | IllegalStateException e) {
			throw new ApiException(ErrorCode.LOGIN_UNAVAILABLE, "카카오에 연결할 수 없어요. 잠시 후 다시 시도해 주세요");
		}
	}

	private static ApiException failed() {
		return new ApiException(ErrorCode.LOGIN_FAILED, "카카오 로그인을 다시 시도해 주세요");
	}
}

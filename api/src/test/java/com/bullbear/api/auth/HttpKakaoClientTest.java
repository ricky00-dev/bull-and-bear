package com.bullbear.api.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import com.bullbear.api.common.ApiException;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

/** 카카오 서버 대신 로컬 HTTP 서버. 요청 형식(폼·헤더)과 응답 읽기를 확인한다. */
class HttpKakaoClientTest {

	private HttpServer server;
	private String tokenForm;
	private String meAuthorization;
	private int tokenStatus = 200;

	@BeforeEach
	void setup() throws Exception {
		server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		server.createContext("/oauth/token", exchange -> {
			tokenForm = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
			respond(exchange, tokenStatus, tokenStatus == 200
					? "{\"token_type\":\"bearer\",\"access_token\":\"kakao-access\",\"expires_in\":21599}"
					: "{\"error\":\"invalid_grant\",\"error_code\":\"KOE320\"}");
		});
		server.createContext("/v2/user/me", exchange -> {
			meAuthorization = exchange.getRequestHeaders().getFirst("Authorization");
			respond(exchange, 200, "{\"id\":4021998765,\"connected_at\":\"2026-11-05T00:00:00Z\"}");
		});
		server.start();
	}

	@AfterEach
	void close() {
		server.stop(0);
	}

	@Test
	void 인가_코드로_회원번호를_얻는다() {
		assertThat(client("secret").userId("abc", "http://localhost:5173/auth/kakao")).isEqualTo("4021998765");
		assertThat(tokenForm).contains("grant_type=authorization_code", "client_id=rest-key", "code=abc",
				"redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fauth%2Fkakao", "client_secret=secret");
		assertThat(meAuthorization).isEqualTo("Bearer kakao-access");
	}

	@Test
	void 시크릿을_안_쓰면_보내지_않는다() {
		client("").userId("abc", "http://localhost:5173/auth/kakao");
		assertThat(tokenForm).doesNotContain("client_secret");
	}

	@Test
	void 만료된_코드는_로그인_실패() {
		tokenStatus = 400;
		assertThatThrownBy(() -> client(null).userId("old", "http://localhost:5173/auth/kakao"))
				.isInstanceOf(ApiException.class).hasMessageContaining("다시 시도");
	}

	private HttpKakaoClient client(String secret) {
		URI base = URI.create("http://127.0.0.1:" + server.getAddress().getPort());
		return new HttpKakaoClient(WebClient.builder(), new KakaoProperties("rest-key", secret, base, base));
	}

	private static void respond(HttpExchange exchange, int status, String body) throws IOException {
		byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
		exchange.getResponseHeaders().add("Content-Type", "application/json;charset=UTF-8");
		exchange.sendResponseHeaders(status, bytes.length);
		exchange.getResponseBody().write(bytes);
		exchange.close();
	}
}

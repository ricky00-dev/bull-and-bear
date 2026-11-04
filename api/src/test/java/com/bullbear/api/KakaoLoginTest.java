package com.bullbear.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.MockMvc;

import com.bullbear.api.auth.KakaoClient;
import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.jayway.jsonpath.JsonPath;

/** 카카오 로그인: 게스트 기록을 이어받고, 다른 기기에서 같은 계정으로 들어오면 기록을 합친다. 카카오 서버 대신 가짜. */
@Import({ TestcontainersConfiguration.class, MutableClockConfiguration.class, KakaoLoginTest.FakeKakao.class })
@SpringBootTest(properties = { "bullbear.worker.mode=fake", "bullbear.worker.fake-delay=0ms",
		"bullbear.kakao.rest-key=test-rest-key" })
@AutoConfigureMockMvc
class KakaoLoginTest {

	/** 인가 코드 "code-<회원번호>"를 그 회원번호로 바꿔 준다. "bad"는 카카오가 거절한 코드 */
	@TestConfiguration
	static class FakeKakao {
		@Bean
		@Primary
		KakaoClient fakeKakaoClient() {
			return (code, redirectUri) -> {
				if (!code.startsWith("code-")) {
					throw new ApiException(ErrorCode.LOGIN_FAILED, "카카오 로그인을 다시 시도해 주세요");
				}
				return code.substring(5);
			};
		}
	}

	@Autowired
	MockMvc mvc;

	@Autowired
	MutableClockConfiguration.MutableClock clock;

	@Autowired
	JdbcClient jdbc;

	@Test
	void 설정을_웹에_알려준다() throws Exception {
		mvc.perform(get("/api/auth/kakao/config").header("Authorization", "Bearer " + guest()))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.enabled").value(true))
				.andExpect(jsonPath("$.clientId").value("test-rest-key"));
	}

	@Test
	void 처음_로그인하면_게스트_계정에_카카오를_연결해_기록이_그대로다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String token = guest();
		String debateId = createAndFinish(token, "005930");
		judge(token, debateId, "BUY");
		UUID guestId = me(token);

		String login = login(token, "code-1001");
		String newToken = JsonPath.read(login, "$.token");

		assertThat(UUID.fromString(JsonPath.read(login, "$.userId"))).isEqualTo(guestId);
		assertThat((Boolean) JsonPath.read(login, "$.merged")).isFalse();
		mvc.perform(get("/api/me").header("Authorization", "Bearer " + newToken))
				.andExpect(jsonPath("$.guest").value(false));
		// 원래 게스트 토큰도 같은 계정이다
		assertThat(me(token)).isEqualTo(guestId);
		mvc.perform(get("/api/me/judgments").header("Authorization", "Bearer " + newToken))
				.andExpect(jsonPath("$.items.length()").value(1));
	}

	@Test
	void 다른_기기에서_같은_카카오로_들어오면_그_기기_게스트_기록을_합친다() throws Exception {
		clock.set(LocalDateTime.of(2026, 10, 23, 10, 0));
		String shared = createAndFinish(guest(), "000660");
		String other = createAndFinish(guest(), "035420");

		String phone = guest();
		judge(phone, shared, "BUY");
		String phoneLogin = login(phone, "code-2002");
		UUID account = UUID.fromString(JsonPath.read(phoneLogin, "$.userId"));
		mvc.perform(put("/api/me/nickname").header("Authorization", "Bearer " + phone)
				.contentType(MediaType.APPLICATION_JSON).content("{\"nickname\":\"폰주인\"}"))
				.andExpect(status().isOk());

		String laptop = guest();
		UUID laptopGuest = me(laptop);
		judge(laptop, shared, "SELL"); // 같은 토론 → 가입 계정의 판정이 남는다
		judge(laptop, other, "HOLD"); // 새 토론 → 옮겨진다
		String laptopLogin = login(laptop, "code-2002");
		String laptopToken = JsonPath.read(laptopLogin, "$.token");

		assertThat(UUID.fromString(JsonPath.read(laptopLogin, "$.userId"))).isEqualTo(account);
		assertThat((Boolean) JsonPath.read(laptopLogin, "$.merged")).isTrue();
		assertThat(count("select count(*) from users where id = :u", laptopGuest)).isZero();
		assertThat(count("select count(*) from judgments where user_id = :u", account)).isEqualTo(2);
		assertThat(jdbc.sql("select decision from judgments where user_id = :u and debate_id = :d")
				.param("u", account).param("d", UUID.fromString(shared)).query(String.class).single()).isEqualTo("BUY");
		mvc.perform(get("/api/me").header("Authorization", "Bearer " + laptopToken))
				.andExpect(jsonPath("$.nickname").value("폰주인"));
		// 지워진 게스트 토큰은 더 이상 쓸 수 없고, 폰 토큰은 그대로다
		mvc.perform(get("/api/me").header("Authorization", "Bearer " + laptop)).andExpect(status().isUnauthorized());
		assertThat(me(phone)).isEqualTo(account);
	}

	@Test
	void 카카오가_거절한_코드는_400() throws Exception {
		mvc.perform(post("/api/auth/kakao").header("Authorization", "Bearer " + guest())
				.contentType(MediaType.APPLICATION_JSON).content("{\"code\":\"bad\",\"redirectUri\":\"http://localhost:5173/auth/kakao\"}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.error.code").value("LOGIN_FAILED"));
	}

	private String login(String token, String code) throws Exception {
		return mvc.perform(post("/api/auth/kakao").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"code\":\"" + code + "\",\"redirectUri\":\"http://localhost:5173/auth/kakao\"}"))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
	}

	private void judge(String token, String debateId, String decision) throws Exception {
		mvc.perform(post("/api/debates/" + debateId + "/judgment").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"decision\":\"" + decision + "\",\"confidence\":70,\"evidencePicks\":[],\"memo\":null}"))
				.andExpect(status().isCreated());
	}

	private UUID me(String token) throws Exception {
		String body = mvc.perform(get("/api/me").header("Authorization", "Bearer " + token))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		return UUID.fromString(JsonPath.read(body, "$.userId"));
	}

	private long count(String sql, UUID userId) {
		return jdbc.sql(sql).param("u", userId).query(Long.class).single();
	}

	private String guest() throws Exception {
		return JsonPath.read(mvc.perform(post("/api/auth/guest")).andReturn().getResponse().getContentAsString(), "$.token");
	}

	private String createAndFinish(String token, String ticker) throws Exception {
		String body = mvc.perform(post("/api/debates").header("Authorization", "Bearer " + token)
				.contentType(MediaType.APPLICATION_JSON).content("{\"ticker\":\"" + ticker + "\"}"))
				.andReturn().getResponse().getContentAsString();
		String id = JsonPath.read(body, "$.id");
		Instant deadline = Instant.now().plus(Duration.ofSeconds(10));
		while (Instant.now().isBefore(deadline)) {
			String d = mvc.perform(get("/api/debates/" + id).header("Authorization", "Bearer " + token))
					.andReturn().getResponse().getContentAsString();
			if ("COMPLETED".equals(JsonPath.read(d, "$.status"))) {
				return id;
			}
			Thread.sleep(100);
		}
		throw new AssertionError("토론이 끝나지 않았습니다");
	}
}

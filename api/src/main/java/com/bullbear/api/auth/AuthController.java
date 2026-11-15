package com.bullbear.api.auth;

import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.user.AccountDeletion;
import com.bullbear.api.user.Nicknames;
import com.bullbear.api.user.User;
import com.bullbear.api.user.UserRepository;

@RestController
@RequestMapping("/api")
public class AuthController {

	public record GuestResponse(UUID userId, String token, boolean guest) {
	}

	public record MeResponse(UUID userId, boolean guest, String nickname) {
	}

	public record NicknameRequest(String nickname) {
	}

	public record KakaoConfig(boolean enabled, String clientId) {
	}

	public record KakaoLoginRequest(String code, String redirectUri) {
	}

	public record LoginResponse(UUID userId, String token, boolean guest, boolean merged) {
	}

	private final UserRepository users;
	private final TokenService tokens;
	private final AccountDeletion deletion;
	private final KakaoProperties kakao;
	private final KakaoClient kakaoClient;
	private final KakaoLogin kakaoLogin;

	public AuthController(UserRepository users, TokenService tokens, AccountDeletion deletion, KakaoProperties kakao,
			KakaoClient kakaoClient, KakaoLogin kakaoLogin) {
		this.users = users;
		this.tokens = tokens;
		this.deletion = deletion;
		this.kakao = kakao;
		this.kakaoClient = kakaoClient;
		this.kakaoLogin = kakaoLogin;
	}

	/** 첫 접속 시 게스트 계정을 만든다. 가입 없이 바로 판정할 수 있게 하기 위함. */
	@PostMapping("/auth/guest")
	@ResponseStatus(HttpStatus.CREATED)
	public GuestResponse createGuest() {
		String token = tokens.newToken();
		User user = users.save(User.guest(tokens.hash(token)));
		return new GuestResponse(user.getId(), token, true);
	}

	/** 웹이 카카오 인가 페이지 주소를 만들 때 쓴다. 키를 웹 빌드에 넣지 않아 배포 설정(.env)만 바꾸면 켜진다 */
	@GetMapping("/auth/kakao/config")
	public KakaoConfig kakaoConfig() {
		return new KakaoConfig(kakao.enabled(), kakao.enabled() ? kakao.restKey() : null);
	}

	/**
	 * 카카오 인가 코드로 로그인. 지금 토큰(게스트)의 기록을 이어받는다 ({@link KakaoLogin}).
	 * redirectUri는 인가 요청 때와 같아야 하고, 카카오 앱에 등록된 주소인지는 카카오가 확인한다.
	 */
	@PostMapping("/auth/kakao")
	public LoginResponse kakaoLogin(@CurrentUser User user, @RequestBody KakaoLoginRequest request) {
		if (!kakao.enabled()) {
			throw new ApiException(ErrorCode.LOGIN_UNAVAILABLE, "카카오 로그인을 준비 중이에요");
		}
		if (request.code() == null || request.code().isBlank() || request.redirectUri() == null) {
			throw new ApiException(ErrorCode.INVALID_REQUEST, "인가 코드가 없습니다");
		}
		String kakaoId = kakaoClient.userId(request.code(), request.redirectUri());
		var result = kakaoLogin.login(user, kakaoId);
		return new LoginResponse(result.userId(), result.token(), false, result.merged());
	}

	@GetMapping("/me")
	public MeResponse me(@CurrentUser User user) {
		return new MeResponse(user.getId(), user.isGuest(), user.getNickname());
	}

	/** 랭킹에 보일 닉네임. 게스트도 정할 수 있다. 중복은 허용 (게스트 번호로 구분할 필요 없음) */
	@PutMapping("/me/nickname")
	public MeResponse nickname(@CurrentUser User user, @RequestBody NicknameRequest request) {
		user.setNickname(Nicknames.validate(request.nickname()));
		users.save(user);
		return me(user);
	}

	/** 내 기록 모두 삭제. 이후 이 토큰은 401이 되고, 웹은 새 게스트로 시작한다 */
	@DeleteMapping("/me")
	@ResponseStatus(HttpStatus.NO_CONTENT)
	public void delete(@CurrentUser User user) {
		deletion.delete(user.getId());
	}
}

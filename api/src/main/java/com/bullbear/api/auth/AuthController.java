package com.bullbear.api.auth;

import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

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

	private final UserRepository users;
	private final TokenService tokens;

	public AuthController(UserRepository users, TokenService tokens) {
		this.users = users;
		this.tokens = tokens;
	}

	/** 첫 접속 시 게스트 계정을 만든다. 가입 없이 바로 판정할 수 있게 하기 위함. */
	@PostMapping("/auth/guest")
	@ResponseStatus(HttpStatus.CREATED)
	public GuestResponse createGuest() {
		String token = tokens.newToken();
		User user = users.save(User.guest(tokens.hash(token)));
		return new GuestResponse(user.getId(), token, true);
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
}

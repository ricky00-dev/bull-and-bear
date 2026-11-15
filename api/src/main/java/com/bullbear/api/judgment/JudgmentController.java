package com.bullbear.api.judgment;

import java.util.List;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.auth.CurrentUser;
import com.bullbear.api.user.User;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

@RestController
@RequestMapping("/api/debates/{debateId}")
public class JudgmentController {

	/**
	 * @param evidencePicks 가장 설득력 있던 근거의 Fact ID, 최대 2개. 뉴스 ID는 소문자 해시를 쓴다 (NEWS.0efa3366)
	 */
	public record SubmitRequest(
			@NotNull Decision decision,
			@Min(50) @Max(100) int confidence,
			@Size(max = 2) List<@Pattern(regexp = "[A-Za-z0-9_.\\-]{2,80}") String> evidencePicks,
			@Size(max = 200) String memo) {
	}

	private final JudgmentService service;

	JudgmentController(JudgmentService service) {
		this.service = service;
	}

	@PostMapping("/judgment")
	@ResponseStatus(HttpStatus.CREATED)
	public JudgmentService.Reveal submit(@CurrentUser User user, @PathVariable UUID debateId,
			@Valid @RequestBody SubmitRequest req) {
		return service.submit(user, debateId,
				new JudgmentService.Submit(req.decision(), req.confidence(), req.evidencePicks(), req.memo()));
	}

	/** 내 판정을 낸 뒤에만 열린다. 그 전에는 403 SEALED. */
	@GetMapping("/reveal")
	public JudgmentService.Reveal reveal(@CurrentUser User user, @PathVariable UUID debateId) {
		return service.reveal(user, debateId);
	}
}

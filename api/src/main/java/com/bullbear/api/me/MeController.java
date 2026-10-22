package com.bullbear.api.me;

import java.util.List;
import java.util.UUID;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.bullbear.api.auth.CurrentUser;
import com.bullbear.api.user.User;

@RestController
@RequestMapping("/api/me")
public class MeController {

	public record JudgmentsResponse(List<MeService.JudgmentView> items) {
	}

	private final MeService service;

	MeController(MeService service) {
		this.service = service;
	}

	/** 내 판정 목록, 최신순. 채점 상태(대기·완료)와 결과를 함께. */
	@GetMapping("/judgments")
	public JudgmentsResponse judgments(@CurrentUser User user) {
		return new JudgmentsResponse(service.list(user));
	}

	/** 채점 결과 화면: 내가 고른 근거, 중재자가 결정적이라 본 근거, 메모 포함. */
	@GetMapping("/judgments/{id}")
	public MeService.JudgmentDetail judgment(@CurrentUser User user, @PathVariable UUID id) {
		return service.detail(user, id);
	}

	/** 적중률, AI를 이긴 판정 수, 자주 고르는 근거 분류. */
	@GetMapping("/stats")
	public MeService.Stats stats(@CurrentUser User user) {
		return service.stats(user);
	}
}

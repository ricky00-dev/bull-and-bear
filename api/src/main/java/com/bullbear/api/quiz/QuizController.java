package com.bullbear.api.quiz;

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
import com.bullbear.api.judgment.Decision;
import com.bullbear.api.user.User;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;

/** 타임머신 퀴즈: 한 판 5문제, 답하면 실제 결과를 바로 공개 */
@RestController
@RequestMapping("/api/quiz")
public class QuizController {

	public record AnswerRequest(@NotNull Decision decision) {
	}

	private final QuizService quiz;

	QuizController(QuizService quiz) {
		this.quiz = quiz;
	}

	@PostMapping("/rounds")
	@ResponseStatus(HttpStatus.CREATED)
	public QuizService.RoundView start(@CurrentUser User user) {
		return quiz.start(user);
	}

	@GetMapping("/rounds/{id}")
	public QuizService.RoundView round(@CurrentUser User user, @PathVariable UUID id) {
		return quiz.round(user, id);
	}

	@PostMapping("/rounds/{id}/questions/{idx}/answer")
	public QuizService.Answer answer(@CurrentUser User user, @PathVariable UUID id, @PathVariable int idx,
			@Valid @RequestBody AnswerRequest request) {
		return quiz.answer(user, id, idx, request.decision());
	}

	@GetMapping("/stats")
	public QuizService.Stats stats(@CurrentUser User user) {
		return quiz.stats(user);
	}
}

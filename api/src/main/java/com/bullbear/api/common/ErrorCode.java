package com.bullbear.api.common;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
	INVALID_REQUEST(HttpStatus.BAD_REQUEST),
	UNAUTHORIZED(HttpStatus.UNAUTHORIZED),
	/** 사용자 판정 전에는 중재자 판정을 볼 수 없다. */
	SEALED(HttpStatus.FORBIDDEN),
	NOT_FOUND(HttpStatus.NOT_FOUND),
	DEBATE_NOT_FINISHED(HttpStatus.CONFLICT),
	/** 타임머신 퀴즈로 낼 토론(7거래일 결과가 나온 토론)이 아직 없다. */
	QUIZ_EMPTY(HttpStatus.CONFLICT),
	ALREADY_ANSWERED(HttpStatus.CONFLICT),
	NOT_ELIGIBLE(HttpStatus.UNPROCESSABLE_CONTENT),
	/** 사용자 한 명의 하루 새 토론 수를 넘었다. */
	DAILY_LIMIT(HttpStatus.TOO_MANY_REQUESTS),
	/** 오늘 LLM 비용 상한을 다 썼다. */
	BUDGET_EXHAUSTED(HttpStatus.SERVICE_UNAVAILABLE),
	WORKER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE);

	private final HttpStatus status;

	ErrorCode(HttpStatus status) {
		this.status = status;
	}

	public HttpStatus status() {
		return status;
	}
}

package com.bullbear.api.common;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
	INVALID_REQUEST(HttpStatus.BAD_REQUEST),
	UNAUTHORIZED(HttpStatus.UNAUTHORIZED),
	/** 사용자 판정 전에는 중재자 판정을 볼 수 없다. */
	SEALED(HttpStatus.FORBIDDEN),
	NOT_FOUND(HttpStatus.NOT_FOUND),
	DEBATE_NOT_FINISHED(HttpStatus.CONFLICT),
	NOT_ELIGIBLE(HttpStatus.UNPROCESSABLE_CONTENT),
	WORKER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE);

	private final HttpStatus status;

	ErrorCode(HttpStatus status) {
		this.status = status;
	}

	public HttpStatus status() {
		return status;
	}
}

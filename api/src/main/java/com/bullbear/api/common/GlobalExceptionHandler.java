package com.bullbear.api.common;

import java.util.stream.Collectors;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 모든 오류를 {"error": {"code", "message"}} 형식으로 돌려준다. */
@RestControllerAdvice
public class GlobalExceptionHandler {

	public record ErrorBody(String code, String message) {
	}

	public record ErrorResponse(ErrorBody error) {
		static ErrorResponse of(ErrorCode code, String message) {
			return new ErrorResponse(new ErrorBody(code.name(), message));
		}
	}

	@ExceptionHandler(ApiException.class)
	ResponseEntity<ErrorResponse> handle(ApiException e) {
		return ResponseEntity.status(e.code().status()).body(ErrorResponse.of(e.code(), e.getMessage()));
	}

	@ExceptionHandler(MethodArgumentNotValidException.class)
	ResponseEntity<ErrorResponse> handle(MethodArgumentNotValidException e) {
		String message = e.getBindingResult().getFieldErrors().stream()
				.map(f -> f.getField() + ": " + f.getDefaultMessage())
				.collect(Collectors.joining(", "));
		return ResponseEntity.badRequest().body(ErrorResponse.of(ErrorCode.INVALID_REQUEST, message));
	}
}

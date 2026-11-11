package com.bullbear.api.backtest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 백테스트 시작·진행 확인. /ops/*는 Caddy가 밖으로 열지 않으므로(/healthz만 예외) 서버 안에서만 부른다.
 * 사용법은 deploy/backtest.sh.
 */
@RestController
@RequestMapping("/ops/backtest")
public class BacktestController {

	private final BacktestService backtest;

	BacktestController(BacktestService backtest) {
		this.backtest = backtest;
	}

	/** 202: 시작함 / 409: 이미 도는 중 / 400: 종목·기준일이 비었거나 오늘 이후 날짜 */
	@PostMapping
	public ResponseEntity<?> start(@RequestBody BacktestService.Request request) {
		try {
			boolean started = backtest.start(request);
			return ResponseEntity.status(started ? HttpStatus.ACCEPTED : HttpStatus.CONFLICT).body(backtest.progress());
		} catch (IllegalArgumentException e) {
			return ResponseEntity.badRequest().body(java.util.Map.of("error", e.getMessage()));
		}
	}

	@GetMapping
	public BacktestService.Progress progress() {
		return backtest.progress();
	}
}

package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.bullbear.api.auth.CurrentUser;
import com.bullbear.api.user.User;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Pattern;

@RestController
@RequestMapping("/api/debates")
public class DebateController {

	public record CreateRequest(@Pattern(regexp = "\\d{6}", message = "6자리 종목코드") String ticker) {
	}

	public record DebateResponse(UUID id, String ticker, String stockName, Debate.Status status, boolean reused,
			String snapshotId, LocalDate tradeDate, BigDecimal basePrice, Instant createdAt) {

		static DebateResponse of(Debate d, boolean reused) {
			return new DebateResponse(d.getId(), d.getTicker(), d.getStockName(), d.getStatus(), reused,
					d.getSnapshotId(), d.getTradeDate(), d.getBasePrice(), d.getCreatedAt());
		}
	}

	private final DebateService service;
	private final DebateStreamHub hub;

	DebateController(DebateService service, DebateStreamHub hub) {
		this.service = service;
		this.hub = hub;
	}

	@PostMapping
	@ResponseStatus(HttpStatus.CREATED)
	public DebateResponse create(@CurrentUser User user, @Valid @RequestBody CreateRequest request) {
		var created = service.create(user, request.ticker());
		return DebateResponse.of(created.debate(), created.reused());
	}

	@GetMapping("/{id}")
	public DebateResponse get(@PathVariable UUID id) {
		return DebateResponse.of(service.get(id), false);
	}

	/**
	 * 토론 이벤트 스트림. 끊겼다 다시 붙으면 브라우저가 Last-Event-ID를 보내고, 그 뒤부터 이어 받는다.
	 * 중재자 판정은 debate_sealed로 가려서 보낸다.
	 */
	@GetMapping(path = "/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter stream(@PathVariable UUID id,
			@RequestHeader(name = "Last-Event-ID", required = false) Long lastEventId,
			@RequestParam(name = "after", required = false) Long after) {
		service.get(id); // 없는 토론이면 404
		long from = lastEventId != null ? lastEventId : after != null ? after : 0L;
		return hub.subscribe(id, from);
	}
}

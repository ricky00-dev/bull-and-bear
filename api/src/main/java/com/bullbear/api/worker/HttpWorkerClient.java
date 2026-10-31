package com.bullbear.api.worker;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import java.util.function.Supplier;
import java.util.concurrent.TimeoutException;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.config.BullbearProperties;

import reactor.core.publisher.Flux;

@Component
@ConditionalOnProperty(name = "bullbear.worker.mode", havingValue = "http")
public class HttpWorkerClient implements WorkerClient {

	private static final Duration TIMEOUT = Duration.ofSeconds(15);
	private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE = new ParameterizedTypeReference<>() {
	};

	private final WebClient http;

	public HttpWorkerClient(WebClient.Builder builder, BullbearProperties properties) {
		this.http = builder
				.baseUrl(properties.worker().baseUrl().toString())
				.defaultHeader("X-Worker-Token", properties.worker().token())
				.build();
	}

	@Override
	public List<WorkerStock> search(String query, int limit) {
		var body = call(() -> http.get()
				.uri(u -> u.path("/stocks/search").queryParam("q", query).queryParam("limit", limit).build())
				.retrieve().bodyToMono(WorkerModels.SearchResponse.class).block(TIMEOUT));
		return body == null ? List.of() : body.items();
	}

	@Override
	public WorkerStockDetail stock(String ticker) {
		return call(() -> http.get().uri("/stocks/{ticker}", ticker)
				.retrieve().bodyToMono(WorkerStockDetail.class).block(TIMEOUT));
	}

	@Override
	public WorkerDebateStarted startDebate(String ticker, String requestId) {
		return call(() -> http.post().uri("/debates")
				.bodyValue(new WorkerModels.StartDebateRequest(ticker, requestId, 1, null, null))
				.retrieve().bodyToMono(WorkerDebateStarted.class).block(TIMEOUT));
	}

	@Override
	public WorkerDebateStarted startSingle(String ticker, String snapshotId, String requestId) {
		return call(() -> http.post().uri("/debates")
				.bodyValue(new WorkerModels.StartDebateRequest(ticker, requestId, null, "single", snapshotId))
				.retrieve().bodyToMono(WorkerDebateStarted.class).block(TIMEOUT));
	}

	@Override
	public List<DailyClose> dailyCloses(String ticker, LocalDate from, LocalDate to) {
		return daily("/prices/daily", "ticker", ticker, from, to);
	}

	@Override
	public List<DailyClose> indexCloses(String code, LocalDate from, LocalDate to) {
		return daily("/indices/daily", "code", code, from, to);
	}

	private List<DailyClose> daily(String path, String key, String value, LocalDate from, LocalDate to) {
		var body = call(() -> http.get()
				.uri(u -> u.path(path).queryParam(key, value).queryParam("from", from).queryParam("to", to).build())
				.retrieve().bodyToMono(WorkerModels.DailyResponse.class).block(TIMEOUT));
		return body == null ? List.of() : body.items();
	}

	@Override
	public Flux<WorkerEvent> events(String workerDebateId, long afterSeq) {
		return http.get().uri("/debates/{id}/events", workerDebateId)
				.accept(MediaType.TEXT_EVENT_STREAM)
				.header("Last-Event-ID", Long.toString(afterSeq))
				.retrieve()
				.bodyToFlux(SSE)
				.timeout(Duration.ofSeconds(45))
				.filter(e -> e.id() != null && e.event() != null)
				.map(e -> new WorkerEvent(Long.parseLong(e.id()), e.event(), e.data() == null ? "{}" : e.data()))
				// A clean socket EOF without a terminal event must also trigger relay retry.
				.concatWith(Flux.error(new IllegalStateException("워커 스트림이 종료 이벤트 없이 닫혔습니다")))
				.takeUntil(WorkerEvent::isTerminal);
	}

	/** 동기 호출의 오류를 API 오류로 바꾼다. */
	private <T> T call(Supplier<T> request) {
		try {
			return request.get();
		} catch (WebClientResponseException e) {
			throw translate(e);
		} catch (WebClientRequestException e) {
			throw new ApiException(ErrorCode.WORKER_UNAVAILABLE, "워커에 연결할 수 없습니다");
		} catch (IllegalStateException e) {
			if (e.getCause() instanceof TimeoutException) {
				throw new ApiException(ErrorCode.WORKER_UNAVAILABLE, "워커 응답 시간이 초과되었습니다");
			}
			throw e;
		}
	}

	static ApiException translate(WebClientResponseException e) {
		return switch (e.getStatusCode().value()) {
			case 404 -> new ApiException(ErrorCode.NOT_FOUND, "워커: 대상을 찾을 수 없습니다");
			case 422 -> new ApiException(ErrorCode.NOT_ELIGIBLE, "워커: 토론할 수 없는 종목입니다");
			default -> new ApiException(ErrorCode.WORKER_UNAVAILABLE, "워커 오류 " + e.getStatusCode().value());
		};
	}
}

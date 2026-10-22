package com.bullbear.api.debate;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.user.User;
import com.bullbear.api.worker.WorkerClient;
import com.bullbear.api.worker.WorkerDebateStarted;
import com.bullbear.api.worker.WorkerStockDetail;

@Service
public class DebateService {

	private static final List<Debate.Status> REUSABLE = List.of(Debate.Status.RUNNING, Debate.Status.COMPLETED);

	public record Created(Debate debate, boolean reused) {
	}

	private final DebateRepository debates;
	private final WorkerClient worker;
	private final DebateRelay relay;
	private final Clock clock;

	DebateService(DebateRepository debates, WorkerClient worker, DebateRelay relay, Clock clock) {
		this.debates = debates;
		this.worker = worker;
		this.relay = relay;
		this.clock = clock;
	}

	/**
	 * 오늘(KST) 같은 종목 토론이 있으면 재사용하고, 없으면 워커에 새로 요청한다.
	 * 같은 날은 스냅샷 데이터가 같으므로 다시 돌릴 이유가 없다 (LLM 비용·대기 시간 절약).
	 */
	public Created create(User user, String ticker) {
		Optional<Debate> today = findToday(ticker);
		if (today.isPresent()) {
			return new Created(today.get(), true);
		}
		WorkerStockDetail stock = worker.stock(ticker);
		if (!stock.eligible()) {
			throw new ApiException(ErrorCode.NOT_ELIGIBLE, String.join(", ", stock.reasons()));
		}
		Debate debate = debates.save(Debate.start(ticker, stock.name(), user.getId()));
		try {
			// 우리 토론 ID를 멱등 키로 넘겨, 재시도해도 워커에 토론이 두 번 생기지 않게 한다
			WorkerDebateStarted started = worker.startDebate(ticker, debate.getId().toString());
			debate.attachWorker(started.debateId(), started.snapshotId());
			debate = debates.save(debate);
		} catch (ApiException e) {
			debate.finish(Debate.Status.FAILED);
			debates.save(debate);
			throw e;
		}
		relay.start(debate.getId());
		return new Created(debate, false);
	}

	public Optional<Debate> findToday(String ticker) {
		Instant startOfDay = LocalDate.now(clock).atStartOfDay(clock.getZone()).toInstant();
		return debates.findFirstByTickerAndStatusInAndCreatedAtAfterOrderByCreatedAtDesc(ticker, REUSABLE, startOfDay);
	}

	public List<Debate> getAll(Collection<UUID> ids) {
		return debates.findAllById(ids);
	}

	public Debate get(UUID id) {
		return debates.findById(id).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "토론을 찾을 수 없습니다"));
	}
}

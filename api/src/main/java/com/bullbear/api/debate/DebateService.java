package com.bullbear.api.debate;

import java.time.Clock;
import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.dao.DataIntegrityViolationException;
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
	private final DebateEventRepository events;
	private final WorkerClient worker;
	private final DebateRelay relay;
	private final DebateQuota quota;
	private final Clock clock;

	DebateService(DebateRepository debates, DebateEventRepository events, WorkerClient worker, DebateRelay relay,
			DebateQuota quota, Clock clock) {
		this.debates = debates;
		this.events = events;
		this.worker = worker;
		this.relay = relay;
		this.quota = quota;
		this.clock = clock;
	}

	/**
	 * 같은 종목·같은 데이터 기준일(최신 종가 날짜) 토론이 있으면 재사용하고, 없으면 워커에 새로 요청한다.
	 *
	 * 기준일이 같으면 스냅샷 데이터가 같으므로 다시 돌릴 이유가 없다. 장 마감 뒤 만든 토론은
	 * 다음 날 장 마감 전까지 재사용되므로, 스케줄러가 미리 돌려 둔 종목은 사용자가 기다리지 않는다.
	 */
	public Created create(User user, String ticker) {
		return create(ticker, user.getId(), Debate.Origin.USER);
	}

	/**
	 * @param requestedBy 시작한 사용자. 스케줄러가 시작하면 null
	 */
	public Created create(String ticker, UUID requestedBy, Debate.Origin origin) {
		WorkerStockDetail stock = worker.stock(ticker);
		Optional<Debate> existing = findReusable(ticker, stock.asOf());
		if (existing.isPresent()) {
			return new Created(existing.get(), true);
		}
		if (!stock.eligible()) {
			throw new ApiException(ErrorCode.NOT_ELIGIBLE, String.join(", ", stock.reasons()));
		}
		if (origin == Debate.Origin.USER) {
			quota.check(requestedBy);
		}
		Debate debate;
		try {
			debate = debates.saveAndFlush(Debate.start(ticker, stock.name(), stock.asOf(), requestedBy, origin, clock));
		} catch (DataIntegrityViolationException e) {
			// 같은 종목을 동시에 요청했다. 먼저 들어간 토론을 재사용한다
			return findReusable(ticker, stock.asOf()).map(d -> new Created(d, true))
					.orElseThrow(() -> new ApiException(ErrorCode.WORKER_UNAVAILABLE, "잠시 후 다시 시도해 주세요"));
		}
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

	/** @param dataDate 워커가 알려 준 최신 종가 날짜 ({@code GET /stocks/{ticker}}의 as_of) */
	public Optional<Debate> findReusable(String ticker, LocalDate dataDate) {
		return debates.findFirstByTickerAndDataDateAndStatusInOrderByCreatedAtDesc(ticker, dataDate, REUSABLE);
	}

	public long runningScheduled() {
		return debates.countByOriginAndStatus(Debate.Origin.SCHEDULED, Debate.Status.RUNNING);
	}

	public List<Debate> getAll(Collection<UUID> ids) {
		return debates.findAllById(ids);
	}

	public Debate get(UUID id) {
		return debates.findById(id).orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "토론을 찾을 수 없습니다"));
	}

	/** 확정된 발언 이벤트 원본(JSON) 순서대로. 퀴즈처럼 스트림 없이 한 번에 보여줄 때 쓴다. */
	public List<String> acceptedStatements(UUID debateId) {
		return events.findByDebateIdAndTypeOrderBySeq(debateId, "statement_accepted").stream()
				.map(DebateEvent::getPayload).toList();
	}
}

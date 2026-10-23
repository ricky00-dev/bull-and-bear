package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "debates")
public class Debate {

	public enum Status {
		RUNNING, COMPLETED, FAILED;

		public boolean isTerminal() {
			return this != RUNNING;
		}
	}

	/** USER: 사용자가 시작, SCHEDULED: 전향 운용 스케줄러. */
	public enum Origin {
		USER, SCHEDULED
	}

	@Id
	private UUID id;

	@Column(nullable = false)
	private String ticker;

	@Column(name = "stock_name", nullable = false)
	private String stockName;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false)
	private Status status;

	@Column(name = "worker_debate_id")
	private String workerDebateId;

	@Column(name = "snapshot_id")
	private String snapshotId;

	@Column(name = "trade_date")
	private LocalDate tradeDate;

	@Column(name = "base_price")
	private BigDecimal basePrice;

	@Column(name = "requested_by")
	private UUID requestedBy;

	@Column(name = "last_event_seq", nullable = false)
	private long lastEventSeq;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false)
	private Origin origin;

	/** 토론을 만든 날 (KST). 하루 비용 상한을 셀 때 쓴다. */
	@Column(name = "debate_day", nullable = false)
	private LocalDate debateDay;

	/** 토론 데이터의 기준일 (워커가 알려 준 최신 종가 날짜). 같은 종목·같은 기준일 토론은 하나만 (DB 유니크 인덱스). */
	@Column(name = "data_date", nullable = false)
	private LocalDate dataDate;

	@Column(name = "input_tokens")
	private Long inputTokens;

	@Column(name = "output_tokens")
	private Long outputTokens;

	@Column(name = "cost_usd")
	private BigDecimal costUsd;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	@Column(name = "completed_at")
	private Instant completedAt;

	protected Debate() {
	}

	static Debate start(String ticker, String stockName, LocalDate dataDate, UUID requestedBy, Origin origin,
			Clock clock) {
		Debate d = new Debate();
		d.id = UUID.randomUUID();
		d.ticker = ticker;
		d.stockName = stockName;
		d.status = Status.RUNNING;
		d.requestedBy = requestedBy;
		d.origin = origin;
		d.debateDay = LocalDate.now(clock);
		d.dataDate = dataDate;
		d.createdAt = clock.instant();
		return d;
	}

	void recordUsage(long inputTokens, long outputTokens, BigDecimal costUsd) {
		this.inputTokens = inputTokens;
		this.outputTokens = outputTokens;
		this.costUsd = costUsd;
	}

	void attachWorker(String workerDebateId, String snapshotId) {
		this.workerDebateId = workerDebateId;
		this.snapshotId = snapshotId;
	}

	void recordSnapshot(String snapshotId, LocalDate tradeDate, BigDecimal basePrice) {
		this.snapshotId = snapshotId;
		this.tradeDate = tradeDate;
		this.basePrice = basePrice;
	}

	void advanceTo(long seq) {
		this.lastEventSeq = Math.max(lastEventSeq, seq);
	}

	void finish(Status status) {
		this.status = status;
		this.completedAt = Instant.now();
	}

	public UUID getId() {
		return id;
	}

	public String getTicker() {
		return ticker;
	}

	public String getStockName() {
		return stockName;
	}

	public Status getStatus() {
		return status;
	}

	public String getWorkerDebateId() {
		return workerDebateId;
	}

	public String getSnapshotId() {
		return snapshotId;
	}

	public LocalDate getTradeDate() {
		return tradeDate;
	}

	public BigDecimal getBasePrice() {
		return basePrice;
	}

	public long getLastEventSeq() {
		return lastEventSeq;
	}

	public Origin getOrigin() {
		return origin;
	}

	public LocalDate getDebateDay() {
		return debateDay;
	}

	public LocalDate getDataDate() {
		return dataDate;
	}

	public BigDecimal getCostUsd() {
		return costUsd;
	}

	public Instant getCreatedAt() {
		return createdAt;
	}
}

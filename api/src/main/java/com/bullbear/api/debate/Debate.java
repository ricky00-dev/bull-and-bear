package com.bullbear.api.debate;

import java.math.BigDecimal;
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

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	@Column(name = "completed_at")
	private Instant completedAt;

	protected Debate() {
	}

	public static Debate start(String ticker, String stockName, UUID requestedBy) {
		Debate d = new Debate();
		d.id = UUID.randomUUID();
		d.ticker = ticker;
		d.stockName = stockName;
		d.status = Status.RUNNING;
		d.requestedBy = requestedBy;
		d.createdAt = Instant.now();
		return d;
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

	public Instant getCreatedAt() {
		return createdAt;
	}
}

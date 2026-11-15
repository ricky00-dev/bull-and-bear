package com.bullbear.api.scoring;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 판정 하나의 N거래일 채점. 판정마다 3일·7일 두 개가 생긴다. */
@Entity
@Table(name = "judgment_scores")
public class JudgmentScore {

	public enum Status {
		PENDING, SCORED
	}

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "judgment_id", nullable = false)
	private UUID judgmentId;

	@Column(name = "horizon_days", nullable = false)
	private short horizonDays;

	/** 주말만 뺀 예상일. 휴장일이 끼면 실제 채점일은 더 늦다 */
	@Column(name = "scheduled_date", nullable = false)
	private LocalDate scheduledDate;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false)
	private Status status;

	/** 아래 수익률은 모두 % 단위 (3.1234 = 3.1234%) */
	@Column(name = "stock_return")
	private BigDecimal stockReturn;

	@Column(name = "index_return")
	private BigDecimal indexReturn;

	/** 초과수익 = 종목 수익률 − 코스피 수익률 (%p) */
	@Column(name = "excess_return")
	private BigDecimal excessReturn;

	@Column(name = "user_hit")
	private Boolean userHit;

	@Column(name = "moderator_hit")
	private Boolean moderatorHit;

	@Column(name = "base_index")
	private BigDecimal baseIndex;

	@Column(name = "stock_close")
	private BigDecimal stockClose;

	@Column(name = "index_close")
	private BigDecimal indexClose;

	@Column(name = "scored_trade_date")
	private LocalDate scoredTradeDate;

	@Column(name = "scored_at")
	private Instant scoredAt;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected JudgmentScore() {
	}

	public static JudgmentScore pending(UUID judgmentId, int horizonDays, LocalDate scheduledDate) {
		JudgmentScore s = new JudgmentScore();
		s.judgmentId = judgmentId;
		s.horizonDays = (short) horizonDays;
		s.scheduledDate = scheduledDate;
		s.status = Status.PENDING;
		s.createdAt = Instant.now();
		return s;
	}

	void complete(ScoreResult r, Instant now) {
		this.stockReturn = r.stockReturn();
		this.indexReturn = r.indexReturn();
		this.excessReturn = r.excessReturn();
		this.userHit = r.userHit();
		this.moderatorHit = r.moderatorHit();
		this.baseIndex = r.baseIndex();
		this.stockClose = r.stockClose();
		this.indexClose = r.indexClose();
		this.scoredTradeDate = r.tradeDate();
		this.status = Status.SCORED;
		this.scoredAt = now;
	}

	public UUID getJudgmentId() {
		return judgmentId;
	}

	public int getHorizonDays() {
		return horizonDays;
	}

	public LocalDate getScheduledDate() {
		return scheduledDate;
	}

	public Status getStatus() {
		return status;
	}

	public BigDecimal getStockReturn() {
		return stockReturn;
	}

	public BigDecimal getIndexReturn() {
		return indexReturn;
	}

	public BigDecimal getExcessReturn() {
		return excessReturn;
	}

	public Boolean getUserHit() {
		return userHit;
	}

	public Boolean getModeratorHit() {
		return moderatorHit;
	}

	public BigDecimal getStockClose() {
		return stockClose;
	}

	public LocalDate getScoredTradeDate() {
		return scoredTradeDate;
	}
}

package com.bullbear.api.debate;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 중재자 판정. 사용자가 그 토론에 판정을 낸 뒤에만 API로 나간다 (JudgmentService). */
@Entity
@Table(name = "moderator_verdicts")
public class ModeratorVerdict {

	@Id
	@Column(name = "debate_id")
	private UUID debateId;

	@Column(nullable = false)
	private String decision;

	@Column(nullable = false)
	private BigDecimal confidence;

	@Column(nullable = false)
	private String reasoning;

	/** 기준표 점수, 결정적 근거 등 워커가 준 verdict 객체 원본 */
	@JdbcTypeCode(SqlTypes.JSON)
	@Column(nullable = false, columnDefinition = "jsonb")
	private String payload;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected ModeratorVerdict() {
	}

	public ModeratorVerdict(UUID debateId, String decision, BigDecimal confidence, String reasoning, String payload) {
		this.debateId = debateId;
		this.decision = decision;
		this.confidence = confidence;
		this.reasoning = reasoning;
		this.payload = payload;
		this.createdAt = Instant.now();
	}

	public UUID getDebateId() {
		return debateId;
	}

	public String getDecision() {
		return decision;
	}

	public String getPayload() {
		return payload;
	}
}

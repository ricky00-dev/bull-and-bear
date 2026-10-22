package com.bullbear.api.judgment;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "judgments")
public class Judgment {

	@Id
	private UUID id;

	@Column(name = "user_id", nullable = false)
	private UUID userId;

	@Column(name = "debate_id", nullable = false)
	private UUID debateId;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false)
	private Decision decision;

	@Column(nullable = false)
	private short confidence;

	@Column(name = "evidence_picks", nullable = false)
	private String[] evidencePicks;

	private String memo;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected Judgment() {
	}

	public Judgment(UUID userId, UUID debateId, Decision decision, int confidence, List<String> evidencePicks,
			String memo) {
		this.id = UUID.randomUUID();
		this.userId = userId;
		this.debateId = debateId;
		this.decision = decision;
		this.confidence = (short) confidence;
		this.evidencePicks = evidencePicks.toArray(String[]::new);
		this.memo = memo;
		this.createdAt = Instant.now();
	}

	public UUID getId() {
		return id;
	}

	public Decision getDecision() {
		return decision;
	}

	public int getConfidence() {
		return confidence;
	}

	public List<String> getEvidencePicks() {
		return List.of(evidencePicks);
	}

	public String getMemo() {
		return memo;
	}

	public Instant getCreatedAt() {
		return createdAt;
	}
}

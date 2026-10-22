package com.bullbear.api.debate;

import java.time.Instant;
import java.util.UUID;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** 워커 이벤트 원본. 판정이 들어 있는 이벤트도 그대로 저장하고, 내보낼 때 가린다. */
@Entity
@Table(name = "debate_events")
public class DebateEvent {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "debate_id", nullable = false)
	private UUID debateId;

	@Column(nullable = false)
	private long seq;

	@Column(nullable = false)
	private String type;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(nullable = false, columnDefinition = "jsonb")
	private String payload;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	protected DebateEvent() {
	}

	public DebateEvent(UUID debateId, long seq, String type, String payload) {
		this.debateId = debateId;
		this.seq = seq;
		this.type = type;
		this.payload = payload;
		this.createdAt = Instant.now();
	}

	public long getSeq() {
		return seq;
	}

	public String getType() {
		return type;
	}

	public String getPayload() {
		return payload;
	}
}

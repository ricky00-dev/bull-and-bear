package com.bullbear.api.worker;

import com.fasterxml.jackson.annotation.JsonProperty;

public record WorkerDebateStarted(
		@JsonProperty("debate_id") String debateId,
		@JsonProperty("snapshot_id") String snapshotId,
		String status,
		boolean reused) {
}

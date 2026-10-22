package com.bullbear.api.worker;

/**
 * 워커 SSE 이벤트 하나.
 *
 * @param seq SSE id. 토론 안에서 1부터 증가
 * @param type SSE event 이름 (statement_accepted 등)
 * @param data JSON 원문
 */
public record WorkerEvent(long seq, String type, String data) {

	public static final String SNAPSHOT_CREATED = "snapshot_created";
	public static final String DEBATE_COMPLETED = "debate_completed";
	public static final String DEBATE_FAILED = "debate_failed";

	public boolean isTerminal() {
		return DEBATE_COMPLETED.equals(type) || DEBATE_FAILED.equals(type);
	}
}

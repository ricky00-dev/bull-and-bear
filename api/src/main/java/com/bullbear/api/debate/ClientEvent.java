package com.bullbear.api.debate;

/**
 * 브라우저로 내보내는 토론 이벤트.
 * 중재자 판정이 담긴 debate_completed는 내용을 빼고 debate_sealed로 바꿔 보낸다.
 * 판정은 사용자가 자기 판정을 낸 뒤 /reveal로만 받을 수 있다.
 */
public record ClientEvent(long seq, String type, String data) {

	static final String SEALED = "debate_sealed";

	static ClientEvent from(long seq, String workerType, String workerData) {
		if ("debate_completed".equals(workerType)) {
			return new ClientEvent(seq, SEALED, "{}");
		}
		return new ClientEvent(seq, workerType, workerData);
	}

	static ClientEvent from(DebateEvent e) {
		return from(e.getSeq(), e.getType(), e.getPayload());
	}
}

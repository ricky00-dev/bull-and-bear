package com.bullbear.api.judgment;

import java.util.List;
import java.util.UUID;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import com.bullbear.api.common.ApiException;
import com.bullbear.api.common.ErrorCode;
import com.bullbear.api.debate.Debate;
import com.bullbear.api.debate.DebateService;
import com.bullbear.api.debate.ModeratorVerdict;
import com.bullbear.api.debate.ModeratorVerdictRepository;
import com.bullbear.api.user.User;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 사용자 판정과 중재자 판정 공개.
 * 중재자 판정은 그 사용자가 같은 토론에 판정을 낸 뒤에만 돌려준다 (판정 봉인).
 */
@Service
public class JudgmentService {

	public record Submit(Decision decision, int confidence, List<String> evidencePicks, String memo) {
	}

	public record MyJudgment(UUID id, Decision decision, int confidence, List<String> evidencePicks, String memo) {
		static MyJudgment of(Judgment j) {
			return new MyJudgment(j.getId(), j.getDecision(), j.getConfidence(), j.getEvidencePicks(), j.getMemo());
		}
	}

	/** 새 판정이 저장됐을 때. 채점 예약이 이 이벤트를 받는다. */
	public record JudgmentSubmitted(UUID judgmentId, UUID debateId) {
	}

	/** 이 토론을 본 사람들의 판정 분포. 내 판정 이후에만 보여 남의 판단에 끌려가지 않게 한다. */
	public record Crowd(long buy, long hold, long sell, long total) {
	}

	/** @param verdict 워커가 준 중재자 판정 원본 (decision, confidence, reasoning, decisive_evidence, scores) */
	public record Reveal(MyJudgment mine, JsonNode verdict, boolean agrees, Crowd crowd) {
	}

	private final JudgmentRepository judgments;
	private final DebateService debates;
	private final ModeratorVerdictRepository verdicts;
	private final ObjectMapper json;
	private final ApplicationEventPublisher events;

	JudgmentService(JudgmentRepository judgments, DebateService debates, ModeratorVerdictRepository verdicts,
			ObjectMapper json, ApplicationEventPublisher events) {
		this.judgments = judgments;
		this.debates = debates;
		this.verdicts = verdicts;
		this.json = json;
		this.events = events;
	}

	/** 판정은 한 번만. 이미 냈으면 (더블 탭 등) 기존 판정으로 공개 결과를 돌려준다. */
	public Reveal submit(User user, UUID debateId, Submit req) {
		Debate debate = debates.get(debateId);
		if (debate.getStatus() != Debate.Status.COMPLETED) {
			throw new ApiException(ErrorCode.DEBATE_NOT_FINISHED, "토론이 끝난 뒤에 판정할 수 있어요");
		}
		if (req.confidence() % 10 != 0) {
			throw new ApiException(ErrorCode.INVALID_REQUEST, "confidence는 10 단위입니다");
		}
		Judgment judgment = judgments.findByUserIdAndDebateId(user.getId(), debateId).orElseGet(() -> {
			try {
				Judgment saved = judgments.saveAndFlush(new Judgment(user.getId(), debateId, req.decision(),
						req.confidence(), req.evidencePicks() == null ? List.of() : req.evidencePicks(), req.memo()));
				events.publishEvent(new JudgmentSubmitted(saved.getId(), debateId));
				return saved;
			} catch (DataIntegrityViolationException e) {
				// 동시에 두 번 제출된 경우: 먼저 저장된 판정을 쓴다
				return judgments.findByUserIdAndDebateId(user.getId(), debateId).orElseThrow(() -> e);
			}
		});
		return reveal(judgment, debateId);
	}

	public Reveal reveal(User user, UUID debateId) {
		Judgment judgment = judgments.findByUserIdAndDebateId(user.getId(), debateId)
				.orElseThrow(() -> new ApiException(ErrorCode.SEALED, "내 판정을 먼저 내야 AI 판정을 볼 수 있어요"));
		return reveal(judgment, debateId);
	}

	private Reveal reveal(Judgment judgment, UUID debateId) {
		ModeratorVerdict verdict = verdicts.findById(debateId)
				.orElseThrow(() -> new ApiException(ErrorCode.DEBATE_NOT_FINISHED, "중재자 판정이 아직 없어요"));
		long buy = 0, hold = 0, sell = 0;
		for (var c : judgments.countByDecision(debateId)) {
			switch (c.getDecision()) {
				case BUY -> buy = c.getCount();
				case HOLD -> hold = c.getCount();
				case SELL -> sell = c.getCount();
			}
		}
		return new Reveal(MyJudgment.of(judgment), json.readTree(verdict.getPayload()),
				judgment.getDecision().name().equals(verdict.getDecision()),
				new Crowd(buy, hold, sell, buy + hold + sell));
	}
}

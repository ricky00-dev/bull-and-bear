"""토론 에이전트(매수·매도)와 중재자."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from . import prompts
from .llm import LLM, Conversation, EventHook, LLMError
from .schemas import MODERATOR_SCHEMA, STATEMENT_SCHEMA, ModeratorDecision, RoundKind, Side, Statement
from .snapshot import Snapshot
from .tools import TOOL_DEFINITIONS, SnapshotTools
from .verifier import VerificationResult
from .semantic import SemanticReviewer, horizon_issues, concept_issues
from .presentation import used_sources, statement_issues, moderator_issues

Verify = Callable[[Statement], VerificationResult]


@dataclass
class Attempt:
    statement: Statement
    verification: VerificationResult


class Debater:
    def __init__(self, llm: LLM, snapshot: Snapshot, *, effort: str = "medium", max_retries: int = 2):
        self.llm = llm
        self.snapshot = snapshot
        self.tools = SnapshotTools(snapshot)
        self.effort = effort
        self.max_retries = max_retries
        self.reviewer = SemanticReviewer(llm, snapshot)

    def speak(
        self,
        side: Side,
        round_kind: RoundKind,
        transcript: list[str],
        *,
        verify: Verify,
        question: str | None = None,
        on_event: EventHook | None = None,
    ) -> list[Attempt]:
        """발언을 생성하고 검증한다. 반려되면 피드백을 붙여 최대 max_retries번 다시 생성한다.

        마지막 시도까지 반려되면 시도 기록을 반환한다. 진행기는 로그를 남기고 중단한다.
        """
        snap = self.snapshot
        used = used_sources(transcript, snap)
        available = [f for key, f in snap.facts.items() if key not in used]
        if round_kind in ("rebuttal", "closing") and not available:
            raise LLMError("No unused evidence available for this round")
        preferred = sorted(available, key=lambda f: f.category not in ("news", "disclosure"))
        guidance = "\n정보 수집 시각: " + snap.created_at.isoformat()
        if round_kind in ("rebuttal", "closing"):
            guidance += "\n아직 인용하지 않은 근거 후보(조회 도구에서 원문 확인):\n" + "\n".join(
                f"{f.id}: {f.label} ({f.as_of})" for f in preferred[:30])
        conv = Conversation(
            system=prompts.debater_system(side, name=snap.name, ticker=snap.ticker, as_of=snap.as_of.isoformat()),
            messages=[{"role": "user", "content": prompts.debater_turn(side, round_kind, transcript, question) + guidance}],
        )
        attempts: list[Attempt] = []
        for _ in range(self.max_retries + 1):
            raw = self.llm.structured(
                conv, schema=STATEMENT_SCHEMA, effort=self.effort,
                tools=TOOL_DEFINITIONS, tool_handler=self.tools, on_event=on_event,
            )
            try:
                statement = Statement.model_validate(raw)
            except ValidationError as e:
                raise LLMError(f"발언 형식 오류: {e}") from e
            result = verify(statement)
            issues = list(result.issues) + horizon_issues(statement.claim)
            issues += statement_issues(statement, round_kind, used)
            issues += concept_issues("\n".join([statement.claim, statement.argument,
                                               *(e.interpretation for e in statement.evidence)]))
            if not any(i.severity == "error" for i in issues):
                issues += self.reviewer.check(statement, transcript, [e.source_id for e in statement.evidence])
            result = result.model_copy(update={"issues": issues,
                                              "passed": not any(i.severity == "error" for i in issues)})
            attempts.append(Attempt(statement, result))
            if result.passed:
                break
            conv.messages.append({"role": "user", "content": prompts.verifier_feedback(result.feedback())})
        return attempts


class Moderator:
    def __init__(self, llm: LLM, snapshot: Snapshot, *, effort: str = "high"):
        self.llm = llm
        self.snapshot = snapshot
        self.effort = effort
        self.reviewer = SemanticReviewer(llm, snapshot)

    def evaluate(self, transcript: list[str], stats: dict, *, extra_allowed: bool) -> ModeratorDecision:
        snap = self.snapshot
        conv = Conversation(
            system=prompts.MODERATOR_SYSTEM,
            messages=[{
                "role": "user",
                "content": prompts.moderator_turn(
                    name=snap.name, ticker=snap.ticker, as_of=snap.as_of.isoformat(),
                    transcript=transcript, stats=stats, extra_allowed=extra_allowed,
                ),
            }],
        )
        for _ in range(3):
            raw = self.llm.structured(conv, schema=MODERATOR_SCHEMA, effort=self.effort)
            decision = ModeratorDecision.model_validate(raw)
            issues = horizon_issues(decision.reasoning)
            issues += moderator_issues(decision)
            issues += concept_issues("\n".join([decision.reasoning, decision.bull.comment, decision.bear.comment]))
            if any(key not in snap.facts for key in decision.decisive_evidence):
                from .verifier import Issue
                issues.append(Issue(severity="error", code="unknown_source", message="판정 근거 ID가 스냅샷에 없습니다."))
            if not issues:
                # Include facts used in the transcript as well as decisive evidence.
                ids = set(decision.decisive_evidence) | {key for key in snap.facts if any(key in t for t in transcript)}
                issues += self.reviewer.check(decision, transcript, ids, stats=stats)
            if not issues:
                return decision
            conv.messages.append({"role": "user", "content": prompts.verifier_feedback(
                "\n".join(i.message for i in issues))})
        raise LLMError("Moderator failed semantic/horizon verification after 3 attempts")

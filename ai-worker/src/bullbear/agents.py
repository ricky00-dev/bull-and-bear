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

        마지막 시도까지 반려되면 그 시도를 그대로 돌려준다 (호출자가 표시·감점 처리).
        """
        snap = self.snapshot
        conv = Conversation(
            system=prompts.debater_system(side, name=snap.name, ticker=snap.ticker, as_of=snap.as_of.isoformat()),
            messages=[{"role": "user", "content": prompts.debater_turn(side, round_kind, transcript, question)}],
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
        raw = self.llm.structured(conv, schema=MODERATOR_SCHEMA, effort=self.effort)
        return ModeratorDecision.model_validate(raw)

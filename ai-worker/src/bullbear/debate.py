"""토론 진행기.

주장 → 반박 → 최종 변론 3라운드를 매수·매도 측이 번갈아 진행한다. 각 발언은 검증기를
통과해야 확정된다. 이후 중재자가 평가하고, 근거가 부족하다고 보면 추가 질문 라운드를 요청한다.
중재자 판정은 사용자가 판정을 내기 전까지 봉인된다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from . import prompts
from .agents import Attempt, Verify
from .events import EventLog
from .llm import EventHook, LLMError
from .schemas import Decision, ModeratorDecision, RoundKind, Side, Statement
from .snapshot import Snapshot
from .verifier import verify

ROUNDS: tuple[RoundKind, ...] = ("opening", "rebuttal", "closing")
ORDER = (Side.BULL, Side.BEAR)


class DebaterLike(Protocol):
    def speak(self, side: Side, round_kind: RoundKind, transcript: list[str], *, verify: Verify,
              question: str | None = None, on_event: EventHook | None = None) -> list[Attempt]: ...


class ModeratorLike(Protocol):
    def evaluate(self, transcript: list[str], stats: dict, *, extra_allowed: bool) -> ModeratorDecision: ...


@dataclass
class Turn:
    side: Side
    round_kind: RoundKind
    attempts: list[Attempt]

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]

    @property
    def statement(self) -> Statement:
        return self.final.statement


@dataclass
class DebateResult:
    debate_id: str
    snapshot: Snapshot
    turns: list[Turn] = field(default_factory=list)
    evaluations: list[ModeratorDecision] = field(default_factory=list)

    @property
    def verdict(self) -> ModeratorDecision:
        return self.evaluations[-1]

    def transcript(self) -> list[str]:
        return [prompts.render_statement(t.side, t.round_kind, t.statement) for t in self.turns]


def verification_stats(turns: list[Turn]) -> dict:
    """측별 검증 통계. 중재자 입력이자 평가 지표 '근거 수치 정확도'의 원천."""
    stats = {}
    for side in ORDER:
        mine = [t for t in turns if t.side is side]
        attempts = [a for t in mine for a in t.attempts]
        checked = sum(a.verification.checked for a in attempts)
        correct = sum(a.verification.correct for a in attempts)
        stats[side.value] = {
            "statements": len(mine),
            "first_try_pass_rate": round(sum(t.attempts[0].verification.passed for t in mine) / len(mine), 2) if mine else None,
            "rejected_attempts": sum(not a.verification.passed for a in attempts),
            "final_unverified_statements": sum(not t.final.verification.passed for t in mine),
            "evidence_accuracy": round(correct / checked, 2) if checked else None,
        }
    return stats


class Debate:
    def __init__(
        self,
        snapshot: Snapshot,
        debater: DebaterLike,
        moderator: ModeratorLike,
        log: EventLog,
        *,
        debate_id: str,
        max_extra_rounds: int = 1,
        first_side: Side = Side.BULL,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        self.snapshot = snapshot
        self.debater = debater
        self.moderator = moderator
        self.log = log
        self.max_extra_rounds = max_extra_rounds
        first_side = Side(first_side)
        self.order = (first_side, Side.BEAR if first_side == Side.BULL else Side.BULL)
        self.on_event = on_event or (lambda *_: None)
        self.result = DebateResult(debate_id=debate_id, snapshot=snapshot)

    def _verify(self, statement: Statement):
        return verify(statement, self.snapshot)

    def _emit(self, type_: str, **payload) -> None:
        self.log.append(type_, **payload)
        self.on_event(type_, payload)

    def _run_round(self, round_kind: RoundKind, question: str | None = None) -> None:
        for side in self.order:
            self.on_event("turn_started", {"side": side, "round": round_kind})
            attempts = self.debater.speak(
                side, round_kind, self.result.transcript(), verify=self._verify, question=question,
                on_event=lambda t, p, side=side: self.on_event(t, {**p, "side": side}),
            )
            for i, a in enumerate(attempts, 1):
                self.log.append("statement_attempt", side=side, round=round_kind, attempt=i,
                                statement=a.statement, verification=a.verification)
                if not a.verification.passed:
                    self.on_event("statement_rejected", {"side": side, "round": round_kind, "attempt": i,
                                                          "issues": a.verification.issues})
            turn = Turn(side, round_kind, attempts)
            if not turn.final.verification.passed:
                raise LLMError("Statement failed verification after retries")
            self.result.turns.append(turn)
            self._emit("statement_accepted", side=side, round=round_kind, attempts=len(attempts),
                       verified=turn.final.verification.passed, statement=turn.statement,
                       verification=turn.final.verification)

    def run(self) -> DebateResult:
        snap = self.snapshot
        self.log.append("debate_started", debate_id=self.result.debate_id, snapshot_id=snap.snapshot_id,
                        ticker=snap.ticker, name=snap.name, as_of=snap.as_of)
        for round_kind in ROUNDS:
            self._run_round(round_kind)

        extra_used = 0
        while True:
            extra_allowed = extra_used < self.max_extra_rounds
            stats = verification_stats(self.result.turns)
            self.on_event("moderator_started", {})
            decision = self.moderator.evaluate(self.result.transcript(), stats, extra_allowed=extra_allowed)
            if decision.action == "extra_round" and not extra_allowed:
                decision = decision.model_copy(update={"action": "verdict", "extra_question": None})
            self.result.evaluations.append(decision)
            # 판정 내용은 기록만 하고 화면에는 내보내지 않는다 (봉인)
            self.log.append("moderator_evaluated", stats=stats, decision=decision, extra_allowed=extra_allowed)
            if decision.action != "extra_round":
                break
            extra_used += 1
            self._emit("extra_round_requested", question=decision.extra_question)
            self._run_round("extra", question=decision.extra_question)

        self.log.append("verdict_sealed", decision=self.result.verdict.decision)
        return self.result

    def submit_user_verdict(self, decision: Decision, reason: str) -> ModeratorDecision:
        """사용자 판정을 기록한 뒤에야 중재자 판정을 공개한다."""
        self.log.append("user_verdict", decision=decision, reason=reason, submitted_at=datetime.now().astimezone())
        verdict = self.result.verdict
        self.log.append("verdict_revealed", decision=verdict.decision, confidence=verdict.confidence,
                        agrees_with_user=verdict.decision is decision)
        return verdict

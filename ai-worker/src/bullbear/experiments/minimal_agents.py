"""Role, snapshot tools and tone only: a free-text debate experiment.

Transport, tools, usage accounting and persistence are supplied by the caller.
This module neither validates investment claims nor retries generated speech.
It is deliberately separate from the production worker's event/API contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Literal, TypedDict

from ..snapshot import Snapshot

POLICY_VERSION = "minimal-role-tools-tone-v2-no-grading"
Role = Literal["bull", "bear", "moderator"]
RoundKind = Literal["opening", "rebuttal", "closing", "verdict"]
ROUNDS = ("opening", "rebuttal", "closing")


class Turn(TypedDict):
    role: Role
    round: RoundKind
    text: str


Completion = Callable[[Role, str, list[dict[str, str]]], str]

_ROLES = {
    "bull": "당신은 매수 측 분석가입니다. 이 종목의 상승 논거를 살피고 상대 반론에 답하세요.",
    "bear": "당신은 매도 측 분석가입니다. 이 종목의 하락 논거를 살피고 상대 반론에 답하세요.",
    "moderator": "당신은 중재자입니다. 양측 논거를 비교해 자신의 매수·보류·매도 판단과 이유를 설명하세요.",
}
_TASKS = {
    "opening": "첫 주장을 말씀해주세요.",
    "rebuttal": "상대의 첫 주장을 읽고 반박해주세요.",
    "closing": "토론을 마무리하는 최종 의견을 말씀해주세요.",
    "verdict": "양측 토론을 정리하고 판단과 이유를 말씀해주세요.",
}


def build_system(role: Role, snapshot: Snapshot) -> str:
    """Only role, tool use and tone; subject metadata belongs in the user input."""
    if role not in _ROLES:
        raise ValueError(f"Unknown role: {role}")
    return "\n".join((
        _ROLES[role],
        "필요한 정보는 제공된 조회 도구로 살펴보세요.",
        "주식 입문자에게 설명하듯 자연스러운 한국어 존댓말로 말하세요. "
        "핵심을 먼저 말하고 근거와 해석을 연결하며, 전문 용어는 쉬운 말로 풀어주세요.",
    ))


def build_messages(
    role: Role,
    round_kind: RoundKind,
    snapshot: Snapshot,
    history: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    """Project only completed earlier rounds into the model's conversation.

    The input envelope is JSON for unambiguous speaker/round boundaries; the
    model's output is ordinary text. No generated analysis or review fields are
    copied into history, and no raw snapshot facts are injected before tool use.
    """
    if role not in _ROLES:
        raise ValueError(f"Unknown role: {role}")
    if round_kind not in _TASKS or (role == "moderator") != (round_kind == "verdict"):
        raise ValueError(f"Invalid role/round combination: {role}/{round_kind}")
    cutoff = len(ROUNDS) if role == "moderator" else ROUNDS.index(round_kind)
    visible = [
        {key: entry[key] for key in ("role", "round", "text")}
        for entry in history
        if entry["role"] in ("bull", "bear") and entry["round"] in ROUNDS[:cutoff]
    ]
    payload = {
        "task": _TASKS[round_kind],
        "subject": {"name": snapshot.name, "ticker": snapshot.ticker},
        "snapshot_id": snapshot.snapshot_id,
        "price_as_of": snapshot.as_of.isoformat(),
        "information_cutoff": snapshot.information_cutoff.isoformat(),
        "history": visible,
    }
    return [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def run_debate(
    snapshot: Snapshot,
    complete: Completion,
    on_turn: Callable[[Turn], None] | None = None,
) -> dict:
    """Generate six speeches and one moderation, without quality regeneration.

    Calls are sequential so a caller can share a spend ledger. Both speakers in
    a round nevertheless receive exactly the same earlier-round history, as in
    the production graph's joined rounds. Total latency is therefore not directly
    comparable to a production run that dispatches the two speakers in parallel.
    """
    history: list[Turn] = []

    def generate(role: Role, round_kind: RoundKind) -> Turn:
        text = complete(role, build_system(role, snapshot),
                        build_messages(role, round_kind, snapshot, history))
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Empty or non-text completion: {role}/{round_kind}")
        turn: Turn = {"role": role, "round": round_kind, "text": text}
        if on_turn is not None:
            on_turn(dict(turn))
        return turn

    for round_kind in ROUNDS:
        # Do not expose the first speaker's current turn to the second speaker.
        current = [generate(role, round_kind) for role in ("bull", "bear")]
        history.extend(current)
    moderator = generate("moderator", "verdict")
    return {
        "profile": POLICY_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "turns": history,
        "moderator": moderator,
    }

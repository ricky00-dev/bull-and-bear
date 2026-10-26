"""내부 토론 이벤트 → 계약(docs/worker-api.md) 이벤트 형식.

토론 엔진(`bullbear.debate`)은 CLI와 서버가 같이 쓰므로 그대로 두고, 바깥으로 나가는 모양만 여기서 맞춘다.
계약이 바뀌면 이 파일만 고친다.
"""

from __future__ import annotations

import json
from typing import Any

from ..events import _default
from ..llm import Usage
from ..schemas import ModeratorDecision
from ..snapshot import Snapshot


def jsonable(obj: Any) -> Any:
    """pydantic 모델·Enum·날짜를 JSON 값으로."""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=_default))


def _side(payload: dict) -> str:
    side = payload.get("side")
    return getattr(side, "value", side)


def snapshot_created(snap: Snapshot) -> dict:
    close = snap.facts["PX.CLOSE"].value
    return {"snapshot_id": snap.snapshot_id, "ticker": snap.ticker, "name": snap.name,
            "as_of": snap.as_of.isoformat(), "close": close, "warnings": snap.warnings}


def from_engine(event: str, payload: dict) -> tuple[str, dict] | None:
    """토론 엔진의 on_event를 계약 이벤트로. 내보내지 않을 이벤트는 None (토큰 등)."""
    if event == "turn_started":
        return "turn_started", {"side": _side(payload), "round": payload["round"]}
    if event == "tool_call":
        return "tool_call", {"side": _side(payload), "tool": payload.get("name")}
    if event == "statement_accepted":
        verification = payload["verification"]
        return "statement_accepted", {
            "side": _side(payload), "round": payload["round"], "attempts": payload["attempts"],
            "verified": payload["verified"], "statement": jsonable(payload["statement"]),
            "warnings": [{"code": i.code, "message": i.message} for i in verification.issues if i.severity == "warning"],
        }
    if event == "extra_round_requested":
        return "extra_round_requested", {"question": payload["question"]}
    if event == "moderator_started":
        return "moderator_started", {}
    return None  # "token": 검증 전 토큰은 흘리지 않는다


def statement_rejected(record: dict) -> dict | None:
    """EventLog의 statement_attempt 기록 중 반려된 시도를 계약 이벤트로."""
    verification = record["verification"]
    if verification.passed:
        return None
    return {"side": _side(record), "round": record["round"], "attempt": record["attempt"],
            "issues": [{"code": i.code, "message": i.message, "ref": i.ref} for i in verification.errors]}


def usage(by_model: list[tuple[str, Usage]]) -> dict:
    """계약 v0.3: 모델별 사용량. 비용은 Spring이 단가표로 계산한다."""
    return {"calls": [
        {"model": model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
         "cache_read_input_tokens": u.cache_read_input_tokens,
         "cache_creation_input_tokens": u.cache_creation_input_tokens}
        for model, u in by_model if u.requests
    ]}


def debate_completed(debate_id: str, verdict: ModeratorDecision, stats: dict, usage_: dict) -> dict:
    return {
        "debate_id": debate_id,
        "verdict": {
            "decision": verdict.decision.value, "confidence": verdict.confidence, "reasoning": verdict.reasoning,
            "decisive_evidence": verdict.decisive_evidence,
            "scores": {"bull": jsonable(verdict.bull), "bear": jsonable(verdict.bear)},
        },
        "stats": stats,
        "usage": usage_,
    }


def debate_failed(code: str, message: str, usage_: dict | None = None) -> dict:
    data: dict = {"error": {"code": code, "message": message}}
    if usage_ is not None:
        data["usage"] = usage_
    return data

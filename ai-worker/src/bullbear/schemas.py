"""에이전트 발언·판정의 구조화 형식.

Pydantic 모델은 코드에서 쓰고, *_SCHEMA는 API의 structured outputs(output_config.format)에
넘기는 JSON Schema다. 둘의 필드는 같아야 한다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Side(str, Enum):
    BULL = "bull"
    BEAR = "bear"

    @property
    def label(self) -> str:
        return "매수" if self is Side.BULL else "매도"


class Decision(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"

    @property
    def label(self) -> str:
        return {"BUY": "매수", "HOLD": "보류", "SELL": "매도"}[self.value]


RoundKind = Literal["opening", "rebuttal", "closing", "extra"]
ROUND_LABELS = {"opening": "주장", "rebuttal": "반박", "closing": "최종 변론", "extra": "추가 질문"}


class Evidence(BaseModel):
    ref: str  # 본문에서 [E1]처럼 참조하는 표식
    source_id: str  # 스냅샷 Fact ID
    value: float | None  # 도구가 돌려준 값을 그대로. 공시처럼 값이 없으면 null
    interpretation: str  # 이 수치가 왜 근거가 되는지 (입문자용 설명)


class Statement(BaseModel):
    claim: str
    argument: str
    evidence: list[Evidence]


STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "description": "한 문장 핵심 주장"},
        "argument": {"type": "string", "description": "최대 3문장 본문. 근거는 [E1] 같은 표식으로 참조"},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "pattern": "^E[1-9][0-9]*$", "description": "E1, E2 등. 대괄호 없이 작성"},
                    "source_id": {"type": "string"},
                    "value": {"type": ["number", "null"]},
                    "interpretation": {"type": "string"},
                },
                "required": ["ref", "source_id", "value", "interpretation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["claim", "argument", "evidence"],
    "additionalProperties": False,
}


class SideScore(BaseModel):
    relevance: int = Field(ge=1, le=5)
    materiality: int = Field(ge=1, le=5)
    rebuttal: int = Field(ge=1, le=5)
    risk_awareness: int = Field(ge=1, le=5)
    comment: str

    @property
    def mean(self) -> float:
        return (self.relevance + self.materiality + self.rebuttal + self.risk_awareness) / 4


class ModeratorDecision(BaseModel):
    action: Literal["verdict", "extra_round"]
    extra_question: str | None
    bull: SideScore
    bear: SideScore
    decision: Decision
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    decisive_evidence: list[str]  # 판정에 결정적이었던 Fact ID


_SIDE_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "materiality": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "rebuttal": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "risk_awareness": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "comment": {"type": "string"},
    },
    "required": ["relevance", "materiality", "rebuttal", "risk_awareness", "comment"],
    "additionalProperties": False,
}

MODERATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["verdict", "extra_round"]},
        "extra_question": {"type": ["string", "null"]},
        "bull": _SIDE_SCORE_SCHEMA,
        "bear": _SIDE_SCORE_SCHEMA,
        "decision": {"type": "string", "enum": ["BUY", "HOLD", "SELL"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string", "description": "쉬운 말로 최대 3문장. [E1]은 decisive_evidence의 첫 번째 항목. 내부 ID·검증 통계·투자자별 권고 금지"},
        "decisive_evidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["action", "extra_question", "bull", "bear", "decision", "confidence", "reasoning", "decisive_evidence"],
    "additionalProperties": False,
}

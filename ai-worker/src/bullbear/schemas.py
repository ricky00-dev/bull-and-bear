"""에이전트 발언·판정의 구조화 형식.

Pydantic 모델은 기존 기록과 Worker가 부여한 식별자·관측 사본까지 읽는다.
*_SCHEMA는 모델 생성용이다. STRUCTURED_*는 analysis를 필수로 요청하며
Worker가 부여할 식별자·관측 사본은 모델에게 생성시키지 않는다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .snapshot import Fact


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
    interpretation_id: str | None = None  # Worker가 확정 발언에 부여
    observation: Fact | None = None  # 모델 생성이 아닌 고정 스냅샷의 사본


class StructuredPart(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretationContext(StructuredPart):
    evidence_ref: str = Field(pattern=r"^E[1-9][0-9]*$")
    expected_outcome: Decision
    assumptions: list[str] = Field(min_length=1, max_length=3)
    limitations: list[str] = Field(min_length=1, max_length=3)


class Rebuttal(StructuredPart):
    target_statement_id: str
    target_quote: str = Field(min_length=6)
    acknowledged: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    unresolved: list[str] = Field(min_length=1, max_length=3)


class Closing(StructuredPart):
    retained: list[str] = Field(min_length=1, max_length=3)
    conceded: list[str] = Field(min_length=1, max_length=3)
    outlook_reason: str = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1, max_length=3)
    change_conditions: list[str] = Field(min_length=1, max_length=3)
    stance_change: Literal["maintained", "weakened", "revised"]


class StatementAnalysis(StructuredPart):
    outlook: Decision
    interpretations: list[InterpretationContext] = Field(min_length=1, max_length=3)
    rebuttal: Rebuttal | None
    closing: Closing | None


class StatementReview(StructuredPart):
    statement_id: str
    assessment: Literal['no_issue_found', 'concern', 'uncertain']
    reason: str = Field(min_length=1)
    source_ids: list[str] = Field(max_length=3)


class ModeratorAnalysis(StructuredPart):
    common_ground: list[str] = Field(max_length=3)
    core_issues: list[str] = Field(min_length=1, max_length=3)
    disagreements: list[str] = Field(max_length=3)
    unverified: list[str] = Field(min_length=1, max_length=3)
    outlook_basis: list[str] = Field(min_length=1, max_length=3)
    outlook_limits: list[str] = Field(min_length=1, max_length=3)
    key_interpretation_ids: list[str] = Field(max_length=6)
    # Older verdicts remain readable; live generation requires all six statements.
    statement_reviews: list[StatementReview] = Field(default_factory=list, max_length=6)


class Statement(BaseModel):
    claim: str
    argument: str
    evidence: list[Evidence]
    statement_id: str | None = None
    analysis: StatementAnalysis | None = None


STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "description": "본문의 핵심 주장·근거와 주요 반박·조건·한계를 보존한 사용자용 두 문장 요약"},
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
    analysis: ModeratorAnalysis | None = None


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


def _with_analysis(schema: dict, model: type[BaseModel]) -> dict:
    """Legacy schemas remain usable by single/standalone graph producers."""
    from copy import deepcopy

    result = deepcopy(schema)
    analysis = model.model_json_schema()
    result["$defs"] = analysis.pop("$defs", {})
    # Defaults support old persisted data, not omission in newly generated output.
    analysis["required"] = list(analysis["properties"])
    result["properties"]["analysis"] = analysis
    result["required"].append("analysis")
    return result


STRUCTURED_STATEMENT_SCHEMA = _with_analysis(STATEMENT_SCHEMA, StatementAnalysis)
STRUCTURED_MODERATOR_SCHEMA = _with_analysis(MODERATOR_SCHEMA, ModeratorAnalysis)


def compact_schema(schema: dict) -> dict:
    """Remove presentation metadata and definitions unreachable from the root.

    Validation constraints, descriptions and required fields stay intact. The
    returned schema is independent of the canonical/public schema constants.
    """
    from copy import deepcopy

    result = deepcopy(schema)

    def clean(node):
        if isinstance(node, dict):
            node.pop('title', None)
            node.pop('default', None)
            for key, value in node.items():
                if key in ('properties', '$defs', 'definitions', 'patternProperties'):
                    for child in value.values():
                        clean(child)
                else:
                    clean(value)
        elif isinstance(node, list):
            for value in node:
                clean(value)

    def references(node):
        if isinstance(node, dict):
            ref = node.get('$ref', '')
            if isinstance(ref, str) and ref.startswith('#/$defs/'):
                yield ref.removeprefix('#/$defs/')
            for value in node.values():
                yield from references(value)
        elif isinstance(node, list):
            for value in node:
                yield from references(value)

    clean(result)
    definitions = result.pop('$defs', {})
    needed = set(references(result))
    pending = list(needed)
    while pending:
        name = pending.pop()
        for child in references(definitions.get(name, {})):
            if child not in needed:
                needed.add(child)
                pending.append(child)
    if needed:
        result['$defs'] = {key: value for key, value in definitions.items() if key in needed}
    return result

"""근거 검증기.

LLM 없이 결정론적으로 동작한다. 발언의 근거 목록을 스냅샷 원본과 대조한다.

반려 (error):
- 스냅샷에 없는 source_id
- 원본과 다른 값 (반올림 허용 범위 밖)
- 본문의 [E#] 표식이 근거 목록에 없음
- 근거가 하나도 없음

경고 (warning, 반려하지 않음):
- 근거 목록에 있지만 본문에서 참조하지 않은 근거
- 본문에 쓴 %·배 수치 중 어떤 근거 값과도 맞지 않는 것
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from .schemas import Statement
from .snapshot import Fact, Snapshot

_REF_PATTERN = re.compile(r"\[(E\d+)\]")
# "12.3%", "-4.5 %", "8.2배"
_NUMBER_PATTERN = re.compile(r"(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|배|퍼센트)")


class Issue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    ref: str | None = None
    message: str


class VerificationResult(BaseModel):
    passed: bool
    checked: int  # 검사한 근거 수
    correct: int  # 원본과 일치한 근거 수
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    def feedback(self) -> str:
        return "\n".join(f"- [{i.code}] {i.message}" for i in self.errors)


def values_match(claimed: float | None, fact: Fact) -> bool:
    if fact.value is None:
        return claimed is None
    if claimed is None:
        return False
    tol = abs(fact.value) * 0.005  # 0.5% 상대 오차
    if fact.unit in ("%", "x"):
        tol = max(tol, 0.051)  # 소수 첫째 자리 반올림 허용
    return abs(claimed - fact.value) <= tol


def verify(statement: Statement, snapshot: Snapshot) -> VerificationResult:
    issues: list[Issue] = []
    correct = 0

    if not statement.evidence:
        issues.append(Issue(severity="error", code="no_evidence", message="근거가 하나도 없습니다"))

    refs = set()
    for ev in statement.evidence:
        if ev.ref in refs:
            issues.append(Issue(severity="error", code="duplicate_ref", ref=ev.ref, message=f"{ev.ref} 표식이 중복됩니다"))
        refs.add(ev.ref)
        fact = snapshot.facts.get(ev.source_id)
        if fact is None:
            issues.append(Issue(
                severity="error", code="unknown_source", ref=ev.ref,
                message=f"{ev.ref}: source_id '{ev.source_id}'는 스냅샷에 없습니다. 도구가 돌려준 id만 쓰세요",
            ))
            continue
        if not values_match(ev.value, fact):
            expected = "null" if fact.value is None else f"{fact.value:g} ({fact.unit})"
            issues.append(Issue(
                severity="error", code="value_mismatch", ref=ev.ref,
                message=f"{ev.ref}: {ev.source_id} 값 {ev.value}은 원본 {expected}과 다릅니다. 원본 값을 그대로 쓰세요",
            ))
            continue
        correct += 1

    used = set(_REF_PATTERN.findall(statement.argument))
    for missing in sorted(used - refs):
        issues.append(Issue(severity="error", code="dangling_ref", ref=missing,
                            message=f"본문의 [{missing}]가 근거 목록에 없습니다"))
    for unused in sorted(refs - used):
        issues.append(Issue(severity="warning", code="unused_evidence", ref=unused,
                            message=f"{unused}는 본문에서 참조되지 않았습니다"))

    issues.extend(_unbacked_numbers(statement, snapshot))

    errors = [i for i in issues if i.severity == "error"]
    return VerificationResult(passed=not errors, checked=len(statement.evidence), correct=correct, issues=issues)


def _unbacked_numbers(statement: Statement, snapshot: Snapshot) -> list[Issue]:
    candidates = [
        snapshot.facts[ev.source_id]
        for ev in statement.evidence
        if ev.source_id in snapshot.facts and snapshot.facts[ev.source_id].unit in ("%", "x")
    ]
    issues = []
    for raw, unit in _NUMBER_PATTERN.findall(statement.argument):
        value = float(raw.replace(",", ""))
        want = "x" if unit == "배" else "%"
        if not any(
            f.unit == want and f.value is not None and (values_match(value, f) or values_match(-value, f))
            for f in candidates
        ):
            issues.append(Issue(severity="warning", code="unbacked_number",
                                message=f"본문 수치 '{raw}{unit}'과 맞는 근거가 없습니다"))
    return issues

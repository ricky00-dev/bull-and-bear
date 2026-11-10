"""Structured interpretation validation and immutable public identities."""
from .history import structured_record

from .presentation import error, knowledge_leakage_issues, money_issues
from .schemas import Side
from .semantic import concept_issues

def history_records(transcript):
    records = []
    for entry in transcript:
        record = structured_record(entry)
        if record is not None:
            records.append(record)
    return records


def prose(value):
    """Only model-authored prose, not source/statement identifiers."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in prose(item)]
    if isinstance(value, dict):
        return [s for key, item in value.items()
                if key not in {"evidence_ref", "target_statement_id", "key_interpretation_ids",
                               "outlook", "expected_outcome", "stance_change", "statement_id", "source_ids", "assessment"}
                for s in prose(item)]
    return []


def analysis_issues(candidate, *, transcript, side=None, round_kind=None):
    analysis = candidate.analysis
    if analysis is None:
        return [error("missing_analysis", "analysis의 구조화된 해석·쟁점 정보를 작성하세요.")]
    text = "\n".join(prose(analysis.model_dump(mode="json")))
    issues = knowledge_leakage_issues(text) + money_issues(text) + concept_issues(text)
    if any(not item.strip() for item in prose(analysis.model_dump(mode="json"))):
        issues.append(error("empty_analysis", "구조화된 설명에 빈 문장 대신 내용 또는 미확인 이유를 쓰세요."))
    records = history_records(transcript)
    if side is None:
        known = {e["interpretation_id"] for r in records for e in r.get("evidence", [])
                 if e.get("interpretation_id")}
        ids = analysis.key_interpretation_ids
        if len(ids) != len(set(ids)) or any(key not in known for key in ids):
            issues.append(error("interpretation_target", "중요 해석 ID는 토론 기록에 있는 서로 다른 ID만 사용하세요."))
        return issues
    refs = [i.evidence_ref for i in analysis.interpretations]
    if len(refs) != len(set(refs)) or set(refs) != {e.ref for e in candidate.evidence}:
        issues.append(error("interpretation_refs", "각 evidence.ref마다 해석의 방향·가정·한계를 정확히 한 번 작성하세요."))
    if round_kind == "rebuttal" and analysis.rebuttal is None:
        issues.append(error("missing_rebuttal", "반박 대상·인정·반박 이유·미해결 쟁점을 작성하세요."))
    if round_kind == "closing" and analysis.closing is None:
        issues.append(error("missing_closing", "유지·인정·전망 이유·불확실성·변경 조건을 작성하세요."))
    if round_kind != "closing" and analysis.closing is not None:
        issues.append(error("unexpected_closing", "최종 변론 이외 단계의 closing은 null입니다."))
    if round_kind == "opening" and analysis.rebuttal is not None:
        issues.append(error("unexpected_rebuttal", "첫 주장 단계의 rebuttal은 null입니다."))
    rebuttal = analysis.rebuttal
    if rebuttal:
        other = Side.BEAR if side == Side.BULL else Side.BULL
        target = next((r for r in records if r.get("statement_id") == rebuttal.target_statement_id
                       and r.get("side") == other.value), None)
        if target is None or not any(rebuttal.target_quote in target.get(k, "") for k in ("claim", "argument")):
            issues.append(error("structured_rebuttal_target", "반대편 실제 statement_id와 해당 주장·본문의 원문을 인용하세요."))
    return issues


def bind_statement(statement, snapshot, *, debate_id, turn_index):
    """IDs depend on accepted turn position, never source ID or retry count."""
    bound = statement.model_copy(deep=True)
    bound.statement_id = f"{debate_id}:t{turn_index}"
    for evidence in bound.evidence:
        evidence.interpretation_id = f"{bound.statement_id}:{evidence.ref}"
        evidence.observation = snapshot.facts[evidence.source_id].model_copy(deep=True)
    return bound

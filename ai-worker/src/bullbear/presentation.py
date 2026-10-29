"""Output limits and stable, verdict-local numbered references."""
import re

from .verifier import Issue


def error(code, message):
    return Issue(severity="error", code=code, message=message)


def sentence_count(text):
    text = re.sub(r"\[E\d+\]", "", text).strip()
    # Do not split decimals; citations may occur after the full stop.
    return len([s for s in re.split(r"[!?。]+|(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)|\n+", text) if s.strip()])


def money_issues(text):
    for match in re.finditer(r"(-?\d[\d,]*(?:\.\d+)?)\s*(억\s*)?원", text):
        amount = abs(float(match[1].replace(",", ""))) * (1e8 if match[2] else 1)
        if amount >= 1e12:
            return [error("money_unit", "1조 원 이상 금액은 본문에서 조 원 단위로 쓰세요. evidence.value의 원값은 유지하세요.")]
    return []


def used_sources(transcript, snapshot):
    # render_statement's evidence lines, not arbitrary mentions in prose.
    ids = set(re.findall(r"^\s+E\d+: (\S+) =", "\n".join(transcript), re.M))
    return ids & snapshot.facts.keys()


def statement_issues(statement, round_kind, used):
    issues = []
    if "\n" in statement.claim or sentence_count(statement.claim) > 1:
        issues.append(error("claim_length", "주장은 한 줄·한 문장 이내로 쓰세요."))
    if sentence_count(statement.argument) > 3:
        issues.append(error("argument_length", "본문은 최대 3문장으로 쓰세요."))
    ids = [e.source_id for e in statement.evidence]
    if len(ids) > 3 or len(ids) != len(set(ids)):
        issues.append(error("evidence_limit", "서로 다른 근거를 최대 3개만 쓰세요."))
    if round_kind in ("rebuttal", "closing") and not set(ids) - used:
        issues.append(error("no_new_evidence", "이전 전체 토론에서 쓰지 않은 source_id를 1개 이상 인용하세요. 뉴스·공시를 우선 확인하세요."))
    issues += money_issues("\n".join([statement.claim, statement.argument, *(e.interpretation for e in statement.evidence)]))
    return issues


def moderator_issues(decision):
    issues = []
    texts = [decision.reasoning, decision.bull.comment, decision.bear.comment, decision.extra_question or ""]
    text = "\n".join(texts)
    if sentence_count(decision.reasoning) > 3:
        issues.append(error("reasoning_length", "판정 이유는 최대 3문장으로 쓰세요."))
    if any(sentence_count(t) > 1 for t in texts[1:3]):
        issues.append(error("comment_length", "양측 평가는 각각 한 문장으로 쓰세요."))
    if re.search(r"\b(?:PX|VAL|FIN|NEWS|DISC|DART)\.[A-Za-z0-9_.]+|evidence_accuracy|first_try_pass_rate|rejected_attempts|검증\s*통계|반려\s*(?:횟수|시도|\d)|인용\s*(?:정확도|일치율)|통과율", text):
        issues.append(error("internal_details", "내부 근거 이름·검증 통계는 글에서 빼고 근거는 [E1] 번호로만 가리키세요."))
    if re.search(r"(?:단기|장기|중장기|위험회피)\s*(?:투자자|트레이더)|손절|분할\s*매수", text):
        issues.append(error("investor_advice", "투자자별 권고·손절·분할매수 권유를 빼고 공통 질문에만 답하세요."))
    ids = decision.decisive_evidence
    used = {int(n) for n in re.findall(r"\[E(\d+)\]", text)}
    if not 1 <= len(ids) <= 3 or len(ids) != len(set(ids)) or used != set(range(1, len(ids) + 1)):
        issues.append(error("verdict_refs", "서로 다른 decisive_evidence 1~3개와 글의 [E1]~[En]을 순서대로 일치시키세요."))
    if decision.decision.value == "HOLD" and not re.search(r"비슷|유사|±2|[−-]2", decision.reasoning):
        issues.append(error("hold_prediction", "보류는 애매함이 아닌 코스피와 비슷하게 움직일 것이라는 구간 예측으로 설명하세요."))
    return issues + money_issues(text)

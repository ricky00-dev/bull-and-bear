import pytest

from bullbear.agents import Debater, Moderator
from bullbear.llm import LLMError
from bullbear.schemas import Side
from bullbear.semantic import SemanticReviewer, horizon_issues
from bullbear.snapshot import build_snapshot
from bullbear.verifier import verify
from .fakes import FakeSource, NOW, statement, ScriptedModerator


class QueueLLM:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def structured(self, conv, **kwargs):
        self.calls.append((conv, kwargs))
        return next(self.outputs)


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def st(text):
    return statement(("E1", "PX.CLOSE", 399), argument=text).model_copy(
        update={"claim": "7거래일 코스피 대비 상승 가능성"})


def test_semantic_rejection_rewrites_and_keeps_numeric_stats(snap):
    bad = st("PER이 낮아서 수익은 보장된다. [E1]")
    good = st("7거래일 코스피 대비 상승은 불확실하다. [E1]")
    llm = QueueLLM([bad.model_dump(), {"issues": [{"code": "concept_error",
        "quote": "수익은 보장된다", "message": "근거 없는 수익 보장입니다."}]},
        good.model_dump(), {"issues": []}])
    attempts = Debater(llm, snap).speak(Side.BULL, "opening", [], verify=lambda s: verify(s, snap))
    assert len(attempts) == 2
    assert attempts[0].verification.correct == 1
    assert not attempts[0].verification.passed
    assert attempts[1].verification.passed
    assert "수익 보장" in llm.calls[2][0].messages[-1]["content"]
    assert llm.calls[1][0] is not llm.calls[0][0]


def test_wrong_horizon_rejected_before_paid_review(snap):
    bad = st("장기 매수 [E1]").model_copy(update={"claim": "중장기 매수"})
    llm = QueueLLM([bad.model_dump()])
    result = Debater(llm, snap, max_retries=0).speak(Side.BULL, "opening", [], verify=lambda s: verify(s, snap))
    assert not result[-1].verification.passed
    assert len(llm.calls) == 1


def test_reviewer_cannot_invent_offending_quote(snap):
    llm = QueueLLM([{"issues": [{"code": "concept_error", "quote": "없는 문구", "message": "오류"}]}] * 2)
    with pytest.raises(LLMError):
        SemanticReviewer(llm, snap).check(st("조건부 가설 [E1]"), [], ["PX.CLOSE"])


def test_reviewer_failure_does_not_become_pass(snap):
    class Broken:
        def structured(self, *a, **kw):
            raise LLMError("unavailable")
    with pytest.raises(LLMError):
        SemanticReviewer(Broken(), snap).check(st("가설 [E1]"), [], ["PX.CLOSE"])


def test_reviewer_quote_uses_text_not_json_escaping(snap):
    quote = '"수익 보장"이라는 주장'
    llm = QueueLLM([{"issues": [{"code": "unsupported_inference", "quote": quote, "message": "보장 불가"}]}])
    issues = SemanticReviewer(llm, snap).check(st(quote + " [E1]"), [], ["PX.CLOSE"])
    assert issues[0].code == "unsupported_inference"


def test_moderator_retries_concept_error(snap):
    d = ScriptedModerator([]).evaluate([], {}, extra_allowed=False)
    d.decisive_evidence = ["PX.CLOSE"]
    d.reasoning = "7거래일 코스피 대비 비슷할 것이다 [E1]. 수치 검증은 예측 정확성을 보장한다."
    good = d.model_copy(update={"reasoning": "7거래일 코스피 대비 비슷하게 움직일 것으로 보아 보류 [E1]."})
    llm = QueueLLM([d.model_dump(mode="json"), {"issues": [{"code": "unsupported_inference",
        "quote": "수치 검증은 예측 정확성을 보장한다", "message": "인용 일치는 예측 보장이 아닙니다."}]},
        good.model_dump(mode="json"), {"issues": []}])
    stats = {"bull": {"evidence_accuracy": 1.0}}
    assert Moderator(llm, snap).evaluate([], stats, extra_allowed=False).reasoning == good.reasoning
    import json
    assert json.loads(llm.calls[1][0].messages[0]['content'])['verification_stats'] == stats


def test_moderator_stops_after_failed_retries(snap):
    d = ScriptedModerator([]).evaluate([], {}, extra_allowed=False)
    with pytest.raises(LLMError):
        Moderator(QueueLLM([d.model_dump(mode="json")] * 3), snap).evaluate([], {}, extra_allowed=False)


def test_policy_applies_to_both_roles():
    from bullbear import prompts
    for side in Side:
        assert prompts.JUDGMENT_POLICY in prompts.debater_system(side, name="x", ticker="0", as_of="2026-10-28")
    assert prompts.JUDGMENT_POLICY in prompts.MODERATOR_SYSTEM
    assert not horizon_issues("7거래일 코스피 대비")


def test_debate_does_not_publish_failed_statement(snap, tmp_path):
    from bullbear.agents import Attempt
    from bullbear.debate import Debate
    from bullbear.events import EventLog
    class FailedDebater:
        def speak(self, *a, verify, **kw):
            bad = statement(("E1", "PX.CLOSE", -1))
            return [Attempt(bad, verify(bad))]
    log = EventLog(tmp_path / "failed.jsonl")
    debate = Debate(snap, FailedDebater(), ScriptedModerator([]), log, debate_id="failed")
    with pytest.raises(LLMError):
        debate.run()
    types = [e["type"] for e in EventLog.read(log.path)]
    assert "statement_attempt" in types
    assert "statement_accepted" not in types
    assert "verdict_sealed" not in types


@pytest.mark.parametrize("text,expected", [
    ("낮은 PER은 사실(시가총액 대비 이익이 상대적으로 작음)을 보여준다.", True),
    ("PER이 9.39배로 낮아(주가 대비 이익이 상대적으로 작음) 상승 여지가 있습니다.", True),
    ("낮은 PER은 시가총액 대비 이익이 크다는 뜻이다.", False),
    ("낮은 PER은 시가총액 대비 이익이 상대적으로 큰 상태이다.", False),
    ("낮은 PER은 이익 대비 시가총액이 작다는 뜻이다.", False),
    ("낮은 PER이 시가총액 대비 이익이 작다는 뜻은 아니다.", False),
    ("양측 근거 정확도는 1.0으로 보고되어 근거 자체의 사실관계 오류는 없음.", True),
    ("인용 정확도 1.0은 사실관계 오류가 없음을 의미하지 않는다.", False),
])
def test_known_per_regression(text, expected):
    from bullbear.semantic import concept_issues
    assert bool(concept_issues(text)) is expected


def test_bracketed_ref_feedback_is_actionable(snap):
    bad = statement(("[E1]", "PX.CLOSE", 399), argument="근거 [E1]")
    result = verify(bad, snap)
    assert not result.passed
    assert "대괄호 없이" in result.feedback()
    from bullbear.schemas import STATEMENT_SCHEMA
    import re
    pattern = STATEMENT_SCHEMA['properties']['evidence']['items']['properties']['ref']['pattern']
    assert re.fullmatch(pattern, 'E1') and not re.fullmatch(pattern, '[E1]')


def test_grounded_error_still_rejects_when_other_quote_is_invented(snap):
    llm = QueueLLM([{"issues": [
        {"code": "concept_error", "quote": "잘못된 설명", "message": "수정 필요"},
        {"code": "contradiction", "quote": "원문에 없는 합성 인용", "message": "오류"},
    ]}])
    reviewer = SemanticReviewer(llm, snap)
    issues = reviewer.check(st("잘못된 설명 [E1]"), [], ['PX.CLOSE'])
    assert len(issues) == 1 and issues[0].severity == 'error'
    assert reviewer.records[0]['grounded'] is False


def test_review_keeps_speakers_and_each_turn_reference_scope(snap):
    import json
    from bullbear.prompts import render_statement
    own = st("내가 앞서 말한 주장 [E1]")
    opponent = statement(('E1', 'PX.RET_1M', snap.facts['PX.RET_1M'].value))
    history = [render_statement(Side.BULL, 'opening', own),
               render_statement(Side.BEAR, 'opening', opponent)]
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(own, history, ['PX.CLOSE'], side=Side.BULL, round_kind='rebuttal')
    payload = json.loads(llm.calls[0][0].messages[0]['content'])
    assert payload['candidate_role'] == 'bull'
    assert payload['candidate_round'] == 'rebuttal'
    assert payload['reference_map'] == {'E1': 'PX.CLOSE'}
    assert [h['speaker'] for h in payload['history']] == ['bull', 'bear']
    assert payload['history'][0]['reference_map'] == {'E1': 'PX.CLOSE'}
    assert payload['history'][1]['reference_map'] == {'E1': 'PX.RET_1M'}
    assert payload['history'][1]['text'] == history[1]

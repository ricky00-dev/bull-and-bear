import pytest

from bullbear.llm import LLMError
from bullbear.schemas import Side
from bullbear.semantic import SemanticReviewer
from bullbear.snapshot import build_snapshot
from bullbear.verifier import verify
from .fakes import FakeSource, NOW, statement, ScriptedModerator
from .learning_fixtures import with_analysis


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
    return with_analysis(statement(("E1", "PX.CLOSE", 399), argument=text).model_copy(
        update={"claim": "7거래일 코스피 대비 상승 가능성"}))








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

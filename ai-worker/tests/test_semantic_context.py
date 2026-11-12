"""Offline context/guard tests; these do not measure an LLM's semantic accuracy."""

import csv
from io import StringIO

import pytest

from bullbear.events import EventLog
from bullbear.llm import LLMError
from bullbear.presentation import verdict_issues
from bullbear.semantic import SemanticReviewer
from bullbear.prompts import render_statement
from bullbear.schemas import Side
from bullbear.single import SingleAnalyst, SingleVerdict
from bullbear.snapshot import build_snapshot
from .prompt_helpers import initial_payload
from .fakes import FakeSource, NOW
from .test_semantic import QueueLLM
from .fakes import statement


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)


def candidate():
    # Synthetic context pair derived from the pilot's failure categories.
    return SingleVerdict(
        decision='SELL', confidence=0.35, decisive_evidence=['PX.CLOSE'],
        reasoning='기준 종가 이후의 낙폭이 유지된다면 7거래일 코스피 대비 −2%p 미만일 것으로 예상합니다 [E1]. '
                  '다만 코스피 등락과 당일 종가가 없어 상대 낙폭은 확인할 수 없습니다. '
                  '반등 가능성은 매도 판단을 약화시키므로 확신은 낮습니다.',
    )


def fact_rows(payload):
    return {row['source_id']: row for row in csv.DictReader(StringIO(payload['facts_csv']))}


def test_reviewer_receives_qualifiers_in_other_sentences_and_original_time_anchors(snap):
    verdict = candidate()
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(verdict, [], verdict.decisive_evidence)
    conv = llm.calls[0][0]
    payload = initial_payload(conv)
    assert payload['candidate']['reasoning'] == verdict.reasoning
    assert payload['candidate']['confidence'] == 0.35
    assert payload['price_as_of'] == str(snap.as_of)
    assert payload['snapshot_created_at'] == str(snap.created_at)
    assert payload['reference_map'] == {'E1': 'PX.CLOSE'}
    close = fact_rows(payload)['PX.CLOSE']
    assert float(close['value']) == snap.facts['PX.CLOSE'].value
    assert close['unit'] == snap.facts['PX.CLOSE'].unit
    assert close['as_of'] == str(snap.facts['PX.CLOSE'].as_of)
    assert close['source'] == snap.facts['PX.CLOSE'].source
    # Check the instructions delivered to the actual review boundary, not a separate prompt file.
    assert '판단 범위는 candidate 전체' in conv.system
    assert 'price_as_of는 가격 자료의 기준일' in conv.system
    assert '근거 인용 불일치·관측 사실 날조·확정 수익 보장은 반려한다' in conv.system


@pytest.mark.parametrize('code', [
    'unsupported_inference', 'horizon_mismatch', 'contradiction', 'concept_error',
])
def test_qualifiers_never_silently_waive_grounded_rejection(snap, tmp_path, code):
    verdict = candidate()
    finding = {'issues': [{'code': code, 'quote': '낙폭이 유지된다면',
                           'message': '대조군 검토에서 실제 오류가 확인되었다.'}]}
    llm = QueueLLM([item for _ in range(3) for item in
                    (verdict.model_dump(mode='json'), finding)])
    log = EventLog(tmp_path / 'attempts.jsonl')
    with pytest.raises(LLMError, match='after 3 attempts'):
        SingleAnalyst(llm, snap).evaluate(log)
    attempts = EventLog.read(log.path)
    assert len(attempts) == 3
    assert all(not event['passed'] for event in attempts)
    assert all(event['issues'][0]['code'] == code for event in attempts)
    assert len(llm.calls) == 6  # No extra review call or retry budget change.


@pytest.mark.parametrize('suffix,expected', [
    (' 추가 설명입니다.', 'reasoning_length'),
    ('', None),
])
def test_three_sentence_guard_still_counts_qualifiers(suffix, expected):
    verdict = candidate().model_copy(update={'reasoning': candidate().reasoning + suffix})
    codes = [issue.code for issue in verdict_issues(verdict)]
    assert ('reasoning_length' in codes) == (expected == 'reasoning_length')


def test_context_does_not_waive_reference_errors():
    verdict = candidate()
    broken = verdict.model_copy(update={'reasoning': verdict.reasoning.replace('[E1]', '[E2]')})
    assert 'verdict_refs' in [issue.code for issue in verdict_issues(broken)]


def test_single_accepts_reasoning_without_horizon_benchmark_or_hold_interval(snap, tmp_path):
    verdict = SingleVerdict(decision='HOLD', confidence=0.35, decisive_evidence=['PX.CLOSE'],
        reasoning='관측된 가격만으로 상승 방향을 확신하기 어려워 판단을 보류합니다 [E1].')
    llm = QueueLLM([verdict.model_dump(mode='json'), {'issues': []}])
    log = EventLog(tmp_path / 'unscored-single.jsonl')
    result = SingleAnalyst(llm, snap).evaluate(log)
    assert result == verdict
    assert len(llm.calls) == 2  # One generation and its ordinary source review; no rewrite.
    attempts = EventLog.read(log.path)
    assert len(attempts) == 1 and attempts[0]['passed']


def test_review_has_uncited_snapshot_facts_without_promoting_them_to_citations(snap):
    # Live pilot: CLOSE/VOL_20D were present, but the reviewer called them absent.
    verdict = candidate().model_copy(update={'decisive_evidence': ['VAL.PER_TTM']})
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(verdict, [], verdict.decisive_evidence)
    payload = initial_payload(llm.calls[0][0])
    facts = fact_rows(payload)
    assert facts.keys() == snap.facts.keys()
    assert payload['reference_map'] == {'E1': 'VAL.PER_TTM'}
    assert payload['selected_source_ids'] == ['VAL.PER_TTM']
    assert float(facts['PX.CLOSE']['value']) == snap.facts['PX.CLOSE'].value
    assert float(facts['PX.VOL_20D']['value']) == snap.facts['PX.VOL_20D'].value
    assert '전체 스냅샷에 존재하지만 인용하지 않은 사실' in llm.calls[0][0].system


def test_review_does_not_fill_missing_benchmark_or_volatility(snap):
    missing = snap.model_copy(update={'facts': {k: f for k, f in snap.facts.items()
                                               if not k.startswith('MKT.') and k != 'PX.VOL_20D'},
                                     'warnings': ['코스피 비교 자료 없음']})
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, missing).check(candidate(), [], ['PX.CLOSE'])
    payload = initial_payload(llm.calls[0][0])
    facts = fact_rows(payload)
    assert 'PX.VOL_20D' not in facts
    assert not any(k.startswith('MKT.') for k in facts)
    assert payload['warnings'] == ['코스피 비교 자료 없음']


@pytest.mark.parametrize('reasoning,quote,message', [
    ('7거래일 코스피 대비 비슷할 것으로 봅니다 [E1]. 양쪽 주장이 약하니 보류합니다.',
     '양쪽 주장이 약하니 보류합니다', '양측 근거 부족은 HOLD 구간의 근거가 아닙니다.'),
    ('7거래일 코스피 대비 상승을 예상합니다 [E1]. 자사주 취득·처분 합계는 모두 취득액입니다.',
     '합계는 모두 취득액입니다', '취득·처분 합계를 취득액으로 바꿀 수 없습니다.'),
    ('종가가 399원이므로 7거래일 코스피 대비 상승을 예상합니다 [E1].',
     '종가가 399원', '종가는 존재하지만 E1의 PER 근거에는 없습니다. 종가 Fact를 인용하세요.'),
])
def test_more_review_context_does_not_waive_hold_news_or_citation_rejections(snap, tmp_path, reasoning, quote, message):
    verdict = candidate().model_copy(update={'reasoning': reasoning,
                                             'decisive_evidence': ['VAL.PER_TTM']})
    finding = {'issues': [{'code': 'unsupported_inference', 'quote': quote, 'message': message}]}
    llm = QueueLLM([item for _ in range(3) for item in (verdict.model_dump(mode='json'), finding)])
    log = EventLog(tmp_path / 'rejected.jsonl')
    with pytest.raises(LLMError, match='after 3 attempts'):
        SingleAnalyst(llm, snap).evaluate(log)
    assert all(not event['passed'] for event in EventLog.read(log.path))
    assert len(llm.calls) == 6


def test_rebuttal_quote_maps_to_opponent_without_changing_candidate(snap):
    # v7 live failure: reviewer attributed the opponent's HOLD quote to the bear.
    quote = '현재 근거로는 보류 구간이 더 가능성 높다고 봅니다'
    opponent = statement(('E1', 'PX.CLOSE', 399), argument='조건부 설명입니다 [E1].').model_copy(
        update={'claim': quote + '.'})
    rebuttal = statement(('E1', 'PX.CLOSE', 399), argument=(
        f'"{quote}"라는 판단은 과거 관측에 기대지만 미래 결과를 정하지 못합니다. '
        '7거래일 코스피 대비 하락 가능성은 열려 있습니다 [E1].'))
    history = [render_statement(Side.BULL, 'rebuttal', opponent)]
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(rebuttal, history, ['PX.CLOSE'], side=Side.BEAR, round_kind='rebuttal')
    payload = initial_payload(llm.calls[0][0])
    assert payload['candidate'] == rebuttal.model_dump(mode='json')
    assert payload['candidate_role'] == 'bear'
    span, = payload['argument_quotes']
    assert rebuttal.argument[span['start']:span['end']] == quote
    assert span['source_matches'] == [{'history_index': 0, 'speaker': 'bull'}]
    assert payload['history'][0]['text'] == history[0]


@pytest.mark.parametrize('location,expected', [
    ('own', [{'history_index': 0, 'speaker': 'bear'}]),
    ('evidence', []),
    ('absent', []),
    ('both', [{'history_index': 0, 'speaker': 'bear'}, {'history_index': 1, 'speaker': 'bull'}]),
])
def test_quote_context_does_not_invent_opponent_ownership(snap, location, expected):
    quote = '현재 관측으로 보류가 더 가능성 높습니다'
    previous = statement(('E1', 'PX.CLOSE', 399), argument='원래 본문입니다 [E1].')
    if location in ('own', 'both'):
        previous.claim = quote
    elif location == 'evidence':
        previous.evidence[0].interpretation = quote
    history = [render_statement(Side.BEAR if location in ('own', 'both') else Side.BULL, 'opening', previous)]
    if location == 'both':
        history.append(render_statement(Side.BULL, 'opening', previous))
    rebuttal = previous.model_copy(update={'argument': f'"{quote}"라는 상대 주장에 반박합니다 [E1].'})
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(rebuttal, history, ['PX.CLOSE'], side=Side.BEAR, round_kind='rebuttal')
    payload = initial_payload(llm.calls[0][0])
    assert payload['argument_quotes'][0]['source_matches'] == expected


def test_quoting_opponent_does_not_silently_waive_actual_contradiction(snap):
    quote = '보류 구간이 더 가능성 높다고 봅니다'
    opponent = statement(('E1', 'PX.CLOSE', 399), argument=quote + ' [E1].')
    candidate = opponent.model_copy(update={
        'claim': '7거래일 코스피 대비 매도가 가장 가능성 높습니다.',
        'argument': f'"{quote}"에 동의하며 저도 보류가 가장 가능성 높습니다 [E1].'})
    finding = {'issues': [{'code': 'contradiction', 'quote': '저도 보류가 가장 가능성 높습니다',
                           'message': '자신의 claim과 동의한 판단이 양립하지 않습니다.'}]}
    llm = QueueLLM([finding])
    issues = SemanticReviewer(llm, snap).check(candidate,
        [render_statement(Side.BULL, 'opening', opponent)], ['PX.CLOSE'], side=Side.BEAR, round_kind='rebuttal')
    assert len(issues) == 1 and issues[0].code == 'contradiction'
    assert len(llm.calls) == 1  # No automatic pass or extra paid review.

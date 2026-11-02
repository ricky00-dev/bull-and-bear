"""Offline context/guard tests; these do not measure an LLM's semantic accuracy."""
import json

import pytest

from bullbear.events import EventLog
from bullbear.llm import LLMError
from bullbear.presentation import verdict_issues
from bullbear.semantic import SemanticReviewer, horizon_issues
from bullbear.single import SingleAnalyst, SingleVerdict
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW
from .test_semantic import QueueLLM


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


def test_reviewer_receives_qualifiers_in_other_sentences_and_original_time_anchors(snap):
    verdict = candidate()
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snap).check(verdict, [], verdict.decisive_evidence)
    conv = llm.calls[0][0]
    payload = json.loads(conv.messages[0]['content'])
    assert payload['candidate']['reasoning'] == verdict.reasoning
    assert payload['candidate']['confidence'] == 0.35
    assert payload['price_as_of'] == str(snap.as_of)
    assert payload['snapshot_created_at'] == str(snap.created_at)
    assert payload['reference_map'] == {'E1': 'PX.CLOSE'}
    assert payload['facts']['PX.CLOSE'] == snap.facts['PX.CLOSE'].model_dump(mode='json')
    # Check the instructions delivered to the actual review boundary, not a separate prompt file.
    assert '판단 범위는 candidate 전체' in conv.system
    assert '새 7거래일 구간을 시작하지 않는다' in conv.system
    assert '후자는 계속 반려한다' in conv.system


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


def test_context_does_not_waive_reference_or_horizon_errors():
    verdict = candidate()
    broken = verdict.model_copy(update={'reasoning': verdict.reasoning.replace('[E1]', '[E2]')})
    assert 'verdict_refs' in [issue.code for issue in verdict_issues(broken)]
    assert horizon_issues(verdict.reasoning.replace('7거래일', '17거래일'))

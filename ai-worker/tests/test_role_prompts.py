"""Inspect instructions at actual generation/review boundaries without API calls."""
import json

from bullbear import prompts
from bullbear.events import EventLog
from bullbear.schemas import Side
from bullbear.single import SingleAnalyst, SingleVerdict
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW
from .graph_fakes import GraphLLM
from .test_graph_runtime import runtime
from .test_semantic import QueueLLM


def test_moderator_receives_own_style_and_retry_instructions(tmp_path):
    snapshot = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)

    class Rewrite(GraphLLM):
        def structured(self, conv, **kwargs):
            assert 'claim은' not in conv.system
            assert '역할상 BUY/SELL' not in conv.system
            assert 'reasoning은 최대 3문장' in conv.system
            if self.count:
                feedback = conv.messages[-1]['content']
                assert '최대 3문장' in feedback and 'comment는 각각 한 문장' in feedback
                assert 'claim' not in feedback and 'analysis.rebuttal' not in feedback
            raw = super().structured(conv, **kwargs)
            if self.count == 1:
                raw['forecast']['reasoning'] += ' 추가 설명입니다.' * 4
            return raw

    moderator = Rewrite(snapshot)
    result = runtime(snapshot, tmp_path, moderator=moderator).run()
    assert moderator.count == 2
    assert result['graph_status'] == 'accepted'


def test_single_retry_and_review_use_single_fields_only(tmp_path):
    snapshot = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)
    good = SingleVerdict(decision='HOLD', confidence=0.35, decisive_evidence=['PX.CLOSE'],
                        reasoning='관측된 가격만으로 방향을 확신하기 어려워 보류합니다 [E1].')
    bad = good.model_copy(update={'reasoning': good.reasoning + ' 추가 설명입니다.' * 4})
    llm = QueueLLM([bad.model_dump(mode='json'), good.model_dump(mode='json'), {'issues': []}])
    assert SingleAnalyst(llm, snapshot).evaluate(EventLog(tmp_path / 'single.jsonl')) == good
    assert len(llm.calls) == 3  # Existing length guard, one rewrite, then ordinary review.
    feedback = llm.calls[1][0].messages[-1]['content']
    assert '최대 3문장' in feedback
    assert all(term not in feedback for term in ('claim', 'argument', 'rebuttal', 'comment', 'forecast'))
    review = llm.calls[2][0]
    assert json.loads(review.messages[0]['content'])['candidate_role'] == 'single'
    assert all(term not in review.system for term in ('claim', 'argument', 'analysis', 'comment', 'speaker'))
    assert '전체 스냅샷에 존재하지만 인용하지 않은 사실' in review.system
    assert '판단 범위는 candidate 전체' in review.system
    assert '조건부 가설을 확정 사실처럼 읽지 않는다' in review.system


def test_debater_keeps_existing_role_and_output_guidance():
    system = prompts.debater_system(Side.BULL, name='가짜전자', ticker='000000', as_of='2026-11-04')
    assert '두 문장 요약' in system and '최대 3문장' in system
    assert 'analysis.rebuttal' in system and '역할상 BUY/SELL' in system
    feedback = prompts.verifier_feedback('근거 오류')
    assert 'claim' in feedback and 'analysis.rebuttal' in feedback
    assert 'reasoning' not in feedback

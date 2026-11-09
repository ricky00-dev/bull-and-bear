import json
import threading
import time

import pytest

from bullbear.events import EventLog
from bullbear.llm import LLMError
from bullbear.statement_review import review_statement
from .graph_fakes import GraphLLM
from .test_graph_runtime import snapshot, runtime


class Reviewer:
    def __init__(self, *, reject_all=False, fabricated=False):
        self.calls = []
        self.reject_all = reject_all
        self.fabricated = fabricated

    def structured(self, conv, **kwargs):
        payload = json.loads(conv.messages[0]['content'])
        self.calls.append(payload)
        text = payload['statement']['argument']
        if '100조' in text or self.reject_all or self.fabricated:
            return {'issues': [dict(quote='없는 인용' if self.fabricated else text,
                kind='unsupported_fact', reason='제공된 자료에서 영업이익 수치가 확인되지 않습니다.',
                source_ids=['PX.CLOSE'], instruction='확인되지 않은 수치를 삭제하고 실제 자료로 논증하세요.')]}
        return {'issues': []}


def test_review_blocks_bad_draft_and_opponent_only_sees_revision(snapshot, tmp_path):
    class WrongMoney(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if self.count == 1:
                raw['argument'] = '분기 영업이익 100조 원으로 개선됐습니다 [E1].'
            return raw
    public = []
    run = runtime(snapshot, tmp_path, bull=WrongMoney(snapshot), emit=lambda e, p: public.append((e, p)))
    run.statement_reviewers = {'bull': Reviewer(), 'bear': Reviewer()}
    run.run()
    events = EventLog.read(run.log.path)
    reviews = [e for e in events if e['type'] == 'statement_reviewed']
    assert len(reviews) == 7 and sum(bool(e['review']['issues']) for e in reviews) == 1
    assert all('100조' not in e['statement']['argument'] for e in events if e['type'] == 'statement_accepted')
    assert all('100조' not in json.dumps(payload['history'], ensure_ascii=False) for payload in run.statement_reviewers['bear'].calls)
    assert not any(e == 'statement_reviewed' for e, _ in public)
    assert '100조' not in json.dumps(public, ensure_ascii=False, default=str)


def test_review_failure_exhausts_bound_without_publishing_rejected_side(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    reviewer = Reviewer(reject_all=True)
    run.statement_reviewers = {'bull': reviewer}
    with pytest.raises(LLMError, match='failed verification'):
        run.run()
    assert len(reviewer.calls) == 3
    assert not any(e['type'] == 'statement_accepted' and e['side'] == 'bull' for e in EventLog.read(run.log.path))


def test_fabricated_review_quote_fails_closed(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    run.statement_reviewers = {'bull': Reviewer(fabricated=True)}
    with pytest.raises(LLMError, match='fabricated target'):
        run.run()


def test_review_is_opt_in(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    run.run()
    assert not any(e['type'] == 'statement_reviewed' for e in EventLog.read(run.log.path))


def test_reviewer_requests_are_serialized(snapshot, tmp_path):
    class CountActive(Reviewer):
        active = 0
        peak = 0
        lock = threading.Lock()

        def structured(self, *args, **kwargs):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.02)
                return super().structured(*args, **kwargs)
            finally:
                with self.lock:
                    self.active -= 1
    reviewer = CountActive()
    run = runtime(snapshot, tmp_path)
    run.statement_reviewers = {'bull': reviewer, 'bear': reviewer}
    run.run()
    assert len(reviewer.calls) == 6 and reviewer.peak == 1

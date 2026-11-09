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


class ReviewSequence:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def structured(self, conv, **kwargs):
        self.messages.append([dict(message) for message in conv.messages])
        return next(self.responses)


def review_candidate(snapshot):
    from .fakes import statement
    return statement(('E1', 'PX.CLOSE', snapshot.facts['PX.CLOSE'].value),
                     argument='확인되지 않은 수치로 상승을 단정했습니다 [E1].')


def concern(quote, *, sources=('PX.CLOSE',)):
    return dict(quote=quote, kind='unsupported_inference', reason='자료로 단정할 수 없습니다.',
                source_ids=list(sources), instruction='단정 표현을 조건부 설명으로 고치세요.')


def test_invalid_quote_then_valid_review_recovers_once(snapshot):
    candidate = review_candidate(snapshot)
    reviewer = ReviewSequence([{'issues': [concern('원문에 없는 인용')]}, {'issues': []}])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert result.issues == [] and len(reviewer.messages) == 2
    assert reviewer.messages[0][0] == reviewer.messages[1][0]
    assert '연속된 문구' in reviewer.messages[1][-1]['content']
    assert 'facts의 키' in reviewer.messages[1][-1]['content']


def test_valid_concern_rejects_immediately_even_with_an_invalid_other_finding(snapshot):
    candidate = review_candidate(snapshot)
    valid = concern(candidate.argument)
    reviewer = ReviewSequence([{'issues': [valid, concern('원문에 없는 인용')]}])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 1
    assert len(result.issues) == 1 and result.issues[0].quote == candidate.argument


def test_unknown_review_source_gets_one_repair_then_fails_closed(snapshot):
    candidate = review_candidate(snapshot)
    invalid = {'issues': [concern(candidate.argument, sources=('UNKNOWN',))]}
    reviewer = ReviewSequence([invalid, invalid])
    with pytest.raises(LLMError, match='unknown source'):
        review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2


def test_unknown_review_source_can_be_corrected_without_losing_concern(snapshot):
    candidate = review_candidate(snapshot)
    reviewer = ReviewSequence([
        {'issues': [concern(candidate.argument, sources=('UNKNOWN',))]},
        {'issues': [concern(candidate.argument)]},
    ])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2
    assert len(result.issues) == 1 and result.issues[0].source_ids == ['PX.CLOSE']

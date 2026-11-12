from copy import deepcopy
import json
import threading
import time

import pytest

from bullbear import prompts
from bullbear.events import EventLog
from bullbear.llm import LLMError
from bullbear.schemas import Decision
from bullbear.statement_review import review_statement
from .prompt_helpers import initial_payload
from .graph_fakes import GraphLLM
from .test_graph_runtime import snapshot, runtime


CORRECTED = '관측된 가격을 배경으로 전망을 유지하지만 향후 흐름은 불확실해요 [E1].'


def wire_statement(candidate):
    result = deepcopy(candidate if isinstance(candidate, dict) else candidate.model_dump(mode='json'))
    result.pop('statement_id', None)
    for evidence in result['evidence']:
        evidence.pop('interpretation_id', None)
        evidence.pop('observation', None)
    return result


def concern(quote, *, sources=('PX.CLOSE',)):
    return dict(quote=quote, kind='unsupported_inference', reason='자료로 단정할 수 없습니다.',
                source_ids=list(sources), instruction='단정 표현을 조건부 설명으로 고치세요.')


def revised_review(candidate, *, quote=None, sources=('PX.CLOSE',)):
    original = wire_statement(candidate)['argument']
    return {'issues': [concern(original if quote is None else quote, sources=sources)],
            'edits': [{'path': 'argument', 'value': CORRECTED}]}


class Reviewer:
    def __init__(self, *, fabricated=False, invalid_revision=False):
        self.calls = []
        self.fabricated = fabricated
        self.invalid_revision = invalid_revision

    def structured(self, conv, **kwargs):
        payload = initial_payload(conv)
        assert {'read_snapshot', 'get_news_body'} <= {tool['name'] for tool in kwargs.get('tools', [])}
        assert '해당 스냅샷 도구를 호출' not in conv.system
        assert prompts.NEWS_CITATION_RULES in conv.system
        assert 'statement_output_instructions' not in payload
        self.calls.append(payload)
        text = payload['statement']['argument']
        if '100조' in text or self.fabricated or self.invalid_revision:
            result = revised_review(payload['statement'], quote='없는 인용' if self.fabricated else None)
            if self.invalid_revision:
                result['edits'] = [{'path': 'evidence.0.value', 'value': '-1'}]
            return result
        return {'issues': [], 'edits': []}


class WrongMoney(GraphLLM):
    def structured(self, conv, **kwargs):
        raw = super().structured(conv, **kwargs)
        if self.count == 1:
            raw['argument'] = '분기 영업이익 100조 원으로 개선됐습니다 [E1].'
        return raw


def test_reviewer_edits_bad_draft_without_regeneration_and_only_revision_is_public(snapshot, tmp_path):
    public = []
    bull = WrongMoney(snapshot)
    run = runtime(snapshot, tmp_path, bull=bull, emit=lambda e, p: public.append((e, p)))
    run.statement_reviewers = {'bull': Reviewer(), 'bear': Reviewer()}
    result = run.run()
    events = EventLog.read(run.log.path)
    reviews = [e for e in events if e['type'] == 'statement_reviewed']
    assert bull.count == 3 and run.bear.count == 3
    assert len(reviews) == 6 and sum(bool(e['review']['issues']) for e in reviews) == 1
    original = next(e for e in reviews if e['review']['issues'])
    assert '100조' in original['statement']['argument']
    assert original['review']['revised_statement']['argument'] == CORRECTED
    assert original.get('original_verification') is None
    assert result['stats']['bull']['first_try_pass_rate'] is None
    assert result['stats']['bull']['evidence_accuracy'] is None
    assert result['stats']['bull']['rejected_attempts'] == 0
    assert result['stats']['bear']['first_try_pass_rate'] is None
    assert result['stats']['bear']['rejected_attempts'] == 0
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert len(accepted) == 6 and all(e['attempts'] == 1 for e in accepted)
    assert all(e['verified'] is False and e['verification_scope'] == 'not_checked' for e in accepted)
    opening = next(e for e in accepted if e['side'] == 'bull' and e['round'] == 'opening')
    assert opening['statement']['argument'] == CORRECTED
    assert opening['statement']['statement_id'] == 'graph-test:bull:t1'
    assert opening['statement']['evidence'][0]['observation']['value'] == snapshot.facts['PX.CLOSE'].value
    opponent_history = [json.dumps(initial_payload(conv)['history'], ensure_ascii=False)
                        for conv, _ in run.bear.calls]
    assert all('100조' not in history for history in opponent_history)
    assert CORRECTED in opponent_history[1]
    moderator_history = json.dumps(initial_payload(run.moderator.calls[0][0])['history'], ensure_ascii=False)
    assert CORRECTED in moderator_history and '100조' not in moderator_history
    assert all('100조' not in json.dumps(payload['history'], ensure_ascii=False)
               for payload in run.statement_reviewers['bear'].calls)
    assert not any(kind in ('statement_reviewed', 'statement_rejected') for kind, _ in public)
    assert '100조' not in json.dumps(public, ensure_ascii=False, default=str)
    assert '100조' not in json.dumps(result, ensure_ascii=False, default=str)


def test_clean_review_preserves_original_statement_content(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    reviewers = {'bull': Reviewer(), 'bear': Reviewer()}
    run.statement_reviewers = reviewers
    run.run()
    accepted = [e for e in EventLog.read(run.log.path) if e['type'] == 'statement_accepted']
    for side, reviewer in reviewers.items():
        side_events = [e for e in accepted if e['side'] == side]
        assert len(side_events) == len(reviewer.calls) == 3
        for event, call in zip(side_events, reviewer.calls):
            assert wire_statement(event['statement']) == wire_statement(call['statement'])
    assert run.bull.count == run.bear.count == 3


def test_invalid_revision_exhausts_reviewer_bound_without_regenerating_or_publishing(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    reviewer = Reviewer(invalid_revision=True)
    run.statement_reviewers = {'bull': reviewer}
    with pytest.raises(LLMError):
        run.run()
    assert len(reviewer.calls) == 2 and run.bull.count == 1
    assert not run.moderator.calls
    assert not any(e['type'] == 'statement_accepted' and e['side'] == 'bull'
                   for e in EventLog.read(run.log.path))


def test_fabricated_review_quote_fails_closed(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    reviewer = Reviewer(fabricated=True)
    run.statement_reviewers = {'bull': reviewer}
    with pytest.raises(LLMError):
        run.run()
    assert len(reviewer.calls) == 2 and run.bull.count == 1


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
        self.messages.append(deepcopy(conv.messages))
        return next(self.responses)


def review_candidate(snapshot):
    from .fakes import statement
    from .learning_fixtures import with_analysis
    candidate = with_analysis(statement(('E1', 'PX.CLOSE', snapshot.facts['PX.CLOSE'].value),
                         argument='확인되지 않은 수치로 상승을 단정했습니다 [E1].'))
    candidate.analysis.outlook = Decision.BUY
    return candidate


def test_invalid_quote_then_clean_review_recovers_once(snapshot):
    candidate = review_candidate(snapshot)
    reviewer = ReviewSequence([revised_review(candidate, quote='원문에 없는 인용'),
                               {'issues': [], 'edits': []}])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert result.issues == [] and result.revised_statement is None and len(reviewer.messages) == 2
    assert reviewer.messages[0][0] == reviewer.messages[1][0]


def test_unknown_review_source_gets_one_repair_then_fails_closed(snapshot):
    candidate = review_candidate(snapshot)
    invalid = revised_review(candidate, sources=('UNKNOWN',))
    reviewer = ReviewSequence([invalid, invalid])
    with pytest.raises(LLMError):
        review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2


def test_unknown_review_source_can_be_corrected_without_losing_concern(snapshot):
    candidate = review_candidate(snapshot)
    reviewer = ReviewSequence([revised_review(candidate, sources=('UNKNOWN',)), revised_review(candidate)])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2
    assert len(result.issues) == 1 and result.issues[0].source_ids == ['PX.CLOSE']
    assert result.revised_statement.argument == CORRECTED


@pytest.mark.parametrize('problem', ['unrequested_edit', 'missing_edits', 'unchanged_edit',
                                    'replace_analysis', 'wrong_role', 'unknown_source'])
def test_invalid_review_contract_cannot_publish(snapshot, problem):
    candidate = review_candidate(snapshot)
    invalid = revised_review(candidate)
    if problem == 'unrequested_edit':
        invalid['issues'] = []
    elif problem == 'missing_edits':
        invalid['edits'] = []
    elif problem == 'unchanged_edit':
        invalid['edits'][0]['value'] = candidate.argument
    elif problem == 'replace_analysis':
        invalid['edits'] = [{'path': 'analysis', 'value': 'null'}]
    elif problem == 'wrong_role':
        invalid['edits'] = [{'path': 'analysis.outlook', 'value': 'SELL'}]
    elif problem == 'unknown_source':
        invalid['edits'] = [{'path': 'evidence.0.source_id', 'value': 'UNKNOWN'}]
    reviewer = ReviewSequence([invalid, invalid])
    with pytest.raises(LLMError):
        review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2


@pytest.mark.parametrize('edits', [None, [], [{'path': 'claim'}]])
def test_valid_concern_cannot_be_dropped_to_bypass_failed_revision(snapshot, edits):
    candidate = review_candidate(snapshot)
    invalid = revised_review(candidate)
    invalid['edits'] = edits
    reviewer = ReviewSequence([invalid, {'issues': [], 'edits': []}])
    with pytest.raises(LLMError):
        review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert len(reviewer.messages) == 2


def test_reviewer_repairs_its_own_invalid_value_without_another_debater_call(snapshot, tmp_path):
    class RepairsValue(Reviewer):
        def structured(self, conv, **kwargs):
            result = super().structured(conv, **kwargs)
            if len(self.calls) == 1:
                result['edits'] = [{'path': 'evidence.0.value', 'value': '-1'}]
            return result
    bull = WrongMoney(snapshot)
    run = runtime(snapshot, tmp_path, bull=bull)
    reviewer = RepairsValue()
    run.statement_reviewers = {'bull': reviewer}
    run.run()
    assert bull.count == 3 and len(reviewer.calls) == 4
    opening = next(e for e in EventLog.read(run.log.path)
                   if e['type'] == 'statement_accepted' and e['side'] == 'bull')
    assert opening['statement']['argument'] == CORRECTED
    assert opening['statement']['evidence'][0]['value'] == snapshot.facts['PX.CLOSE'].value


def test_reviewer_cannot_publish_broken_rebuttal_connection(snapshot, tmp_path):
    class InvalidRebuttal(Reviewer):
        def structured(self, conv, **kwargs):
            payload = initial_payload(conv)
            self.calls.append(payload)
            if payload['statement']['analysis']['rebuttal'] is None:
                return {'issues': [], 'edits': []}
            result = revised_review(payload['statement'])
            result['edits'] = [{'path': 'analysis.rebuttal.target_statement_id',
                                'value': 'fabricated-opponent'}]
            return result
    run = runtime(snapshot, tmp_path)
    reviewer = InvalidRebuttal()
    run.statement_reviewers = {'bull': reviewer}
    with pytest.raises(LLMError):
        run.run()
    assert run.bull.count == 2 and len(reviewer.calls) == 3
    assert not run.moderator.calls
    published_bull = [e for e in EventLog.read(run.log.path)
                      if e['type'] == 'statement_accepted' and e['side'] == 'bull']
    assert len(published_bull) == 1 and published_bull[0]['round'] == 'opening'

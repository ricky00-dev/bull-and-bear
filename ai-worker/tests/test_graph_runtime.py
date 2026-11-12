import csv
import json
from io import StringIO
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime, GraphStopped, MEDIATION_SCHEMA
from bullbear.llm import LLMError, anthropic_schema
from bullbear.schemas import Side
from bullbear.snapshot import build_snapshot
from .prompt_helpers import initial_payload
from .fakes import NOW, FakeSource
from .graph_fakes import GraphLLM
from .test_server import setup, app_for, start, completed, AUTH, parse_sse


@pytest.fixture
def snapshot():
    return build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)


def test_overlong_summary_does_not_trigger_code_rewriting(snapshot, tmp_path):
    class Summary(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            raw['claim'] += '. 관측된 흐름의 지속은 불확실합니다.'
            if self.count == 1:
                raw['claim'] += ' 추가 확인이 필요합니다.'
            return raw
    run = runtime(snapshot, tmp_path, bull=Summary(snapshot))
    run.run()
    events = EventLog.read(run.log.path)
    rejected = [e for e in events if e['type'] == 'statement_rejected']
    assert not rejected
    accepted = [e for e in events if e['type'] == 'statement_accepted' and e['side'] == 'bull']
    from bullbear.presentation import sentence_count
    assert len(accepted) == 3 and sentence_count(accepted[0]['statement']['claim']) == 3
    assert all(e['attempts'] == 1 for e in accepted)


def test_shared_horizon_need_not_be_repeated_in_each_utterance(snapshot, tmp_path):
    class NaturalClaim(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if 'claim' in raw:
                raw['claim'] = '관측된 흐름이 이어진다는 가정 아래 전망을 유지합니다.'
                if raw['analysis']['rebuttal'] is not None:
                    quote = '관측된 가격을 배경으로'
                    raw['analysis']['rebuttal']['target_quote'] = quote
                    raw['argument'] = f'상대의 “{quote}”라는 설명만으로는 흐름의 지속을 확정할 수 없습니다 [E1].'
            return raw
    run = runtime(snapshot, tmp_path)
    run.bull = NaturalClaim(snapshot)
    run.bear = NaturalClaim(snapshot)
    run.run()
    events = EventLog.read(run.log.path)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert len(accepted) == 6 and all(e['attempts'] == 1 for e in accepted)
    assert all('7거래일' not in e['statement']['claim'] for e in accepted)
    assert all('코스피 대비' not in e['statement']['argument'] for e in accepted)


def test_final_forecast_accepts_reasoning_without_scoring_target(snapshot, tmp_path):
    class UnscoredForecast(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            raw['forecast']['reasoning'] = '관측된 가격만으로 상승 방향을 확신하기 어려워 판단을 보류합니다 [E1].'
            return raw
    moderator = UnscoredForecast(snapshot)
    run = runtime(snapshot, tmp_path, moderator=moderator)
    result = run.run()
    assert moderator.count == 1
    assert result['verdict']['reasoning'] == '관측된 가격만으로 상승 방향을 확신하기 어려워 판단을 보류합니다 [E1].'
    assert not any(e['type'] == 'moderator_rejected' for e in EventLog.read(run.log.path))


def test_agent_and_reviewer_systems_do_not_impose_application_scoring():
    from bullbear import prompts
    from bullbear.graph_runtime import MEDIATOR_SYSTEM
    from bullbear.semantic import SYSTEM as REVIEW_SYSTEM
    from bullbear.single import SYSTEM as SINGLE_SYSTEM

    systems = [MEDIATOR_SYSTEM, REVIEW_SYSTEM, SINGLE_SYSTEM]
    systems += [prompts.debater_system(side) for side in Side]
    for system in systems:
        assert all(marker not in system for marker in ('7거래일', '2%p', '일곱 번째', 'T7'))


def test_return_sign_is_not_checked_by_runtime(snapshot, tmp_path):
    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'return_context' not in initial_payload(conv)
            if self.count == 1:
                raw['argument'] = '상대수익은 -0.84%p로 코스피보다 더 올랐습니다 [E1].'
            return raw
    llm = WrongFirst(snapshot)
    run = runtime(snapshot, tmp_path, bull=llm)
    run.run()
    events = EventLog.read(run.log.path)
    assert not any(e['type'] == 'statement_rejected' for e in events)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert len(accepted) == 6
    assert next(e for e in accepted if e['side'] == 'bull')['statement']['argument'] == (
        '상대수익은 -0.84%p로 코스피보다 더 올랐습니다 [E1].')
    assert llm.count == 3


def test_moderator_return_sign_does_not_trigger_regeneration(snapshot, tmp_path):
    class WrongModerator(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'return_context' not in initial_payload(conv)
            if self.count == 1:
                raw['forecast']['reasoning'] = '7거래일 코스피 대비 상대수익 -0.84%p로 코스피보다 더 올랐습니다 [E1].'
            return raw
    run = runtime(snapshot, tmp_path, moderator=WrongModerator(snapshot))
    result = run.run()
    assert '더 올랐습니다' in result['verdict']['reasoning']
    assert run.moderator.count == 1
    assert not any(e['type'] == 'moderator_rejected' for e in EventLog.read(run.log.path))


def test_news_source_wording_is_not_code_corrected(snapshot, tmp_path):
    bad_text = '발표 다음 날 장중 급락했다는 기사입니다 [E1].'

    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'source_context' not in initial_payload(conv)
            if self.count == 1:
                raw['argument'] = bad_text
            return raw
    run = runtime(snapshot, tmp_path, bull=WrongFirst(snapshot))
    run.run()
    events = EventLog.read(run.log.path)
    assert not any(e['type'] == 'statement_rejected' for e in events)
    assert any(e['statement']['argument'] == bad_text for e in events if e['type'] == 'statement_accepted')
    assert run.bull.count == 3


def test_moderator_per_is_not_code_corrected(snapshot, tmp_path):
    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'source_context' not in initial_payload(conv)
            if self.count == 1:
                raw['forecast']['reasoning'] = '7거래일 코스피 대비 PER 8.46배로 낮은 편이라 반등을 예상합니다 [E1].'
            return raw
    run = runtime(snapshot, tmp_path, moderator=WrongFirst(snapshot))
    result = run.run()
    assert result['verdict']['reasoning'] == '7거래일 코스피 대비 PER 8.46배로 낮은 편이라 반등을 예상합니다 [E1].'
    assert run.moderator.count == 1
    assert not any(e['type'] == 'moderator_rejected' for e in EventLog.read(run.log.path))


def runtime(snapshot, tmp_path, *, actions=(), max_extra=1, emit=None, bull=None, moderator=None):
    return GraphRuntime(snapshot, debate_id='graph-test',
        bull=bull or GraphLLM(snapshot), bear=GraphLLM(snapshot),
        moderator=moderator or GraphLLM(snapshot, actions=actions),
        log=EventLog(tmp_path / 'graph.jsonl'), max_extra_rounds=max_extra, emit=emit)


def test_parallel_initial_nodes_keep_separate_clients_ids_and_events(snapshot, tmp_path):
    barrier = Barrier(2)
    class Parallel(GraphLLM):
        def structured(self, conv, **kwargs):
            if not self.calls:
                # Bear starts once Bull's response has begun; both then generate together.
                kwargs['on_event']('stream_started', {})
                barrier.wait(timeout=5)
            return super().structured(conv, **kwargs)
    run = runtime(snapshot, tmp_path)
    run.bull = Parallel(snapshot)
    run.bear = Parallel(snapshot)
    result = run.run()
    assert result['engine'] == 'langgraph' and result['graph_status'] == 'accepted'
    events = EventLog.read(run.log.path)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert len(accepted) == 6
    ids = [e['statement']['evidence'][0]['interpretation_id'] for e in accepted]
    assert len(set(ids)) == 6
    assert {e['side'] for e in accepted} == {'bull', 'bear'}
    assert all(e['statement']['evidence'][0]['observation']['value'] == 399 for e in accepted)
    assert [e['seq'] for e in events] == list(range(1, len(events) + 1))


def test_fixed_rounds_join_both_sides_and_reuse_evidence(snapshot, tmp_path):
    snapshot.facts = {'PX.CLOSE': snapshot.facts['PX.CLOSE']}
    run = runtime(snapshot, tmp_path)
    result = run.run()
    assert all(result['stats'][side]['statements'] == 3 for side in ('bull', 'bear'))
    for stats in result['stats'].values():
        assert stats['first_try_pass_rate'] is None
        assert stats['evidence_accuracy'] is None
        assert stats['rejected_attempts'] == 0
        assert stats['final_unverified_statements'] == 3
    events = EventLog.read(run.log.path)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert all(e['verified'] is False and e['verification'] is None
               and e['verification_scope'] == 'not_checked' for e in accepted)
    assert not any(e['type'] == 'statement_reviewed' for e in events)
    assert [e['round'] for e in accepted] == ['opening']*2 + ['rebuttal']*2 + ['closing']*2
    assert all(e['statement']['analysis']['outlook'] == ('BUY' if e['side']=='bull' else 'SELL') for e in accepted)
    assert events.index(next(e for e in events if e['type']=='moderator_started')) > events.index(accepted[-1])

    rounds = ['opening', 'rebuttal', 'closing']
    ordered = sorted(accepted, key=lambda e: (rounds.index(e['round']), e['side'] == 'bear'))
    expected = []
    for event in ordered:
        record = dict(side=event['side'], round=event['round'], **event['statement'])
        assert all(e['observation']['id'] == e['source_id'] for e in record['evidence'])
        record['evidence'] = [{key: value for key, value in item.items() if key != 'observation'}
                              for item in record['evidence']]
        expected.append(record)
    by_id = {record['statement_id']: record for record in expected}
    for client in (run.bull, run.bear):
        calls = [initial_payload(conv) for conv, _ in client.calls]
        assert [c['round'] for c in calls] == rounds
        for call, count in zip(calls, (0, 2, 4), strict=True):
            assert len(call['history']) <= count
            for record in call['history']:
                original = by_id[record['statement_id']]
                assert record['claim'] == original['claim']
                assert record['argument'] == original['argument']
                assert [(e['ref'], e['source_id']) for e in record['evidence']] == [
                    (e['ref'], e['source_id']) for e in original['evidence']]
                assert all('observation' not in e for e in record['evidence'])
    moderator_call, = [initial_payload(c) for c, schema in run.moderator.calls
                       if 'forecast' in schema['properties']]
    assert [r['statement_id'] for r in moderator_call['history']] == list(by_id)
    assert [r['argument'] for r in moderator_call['history']] == [r['argument'] for r in expected]


def test_overlong_moderator_comment_does_not_call_an_editor(snapshot, tmp_path):
    from copy import deepcopy

    class Editor(GraphLLM):
        def structured(self, conv, **kwargs):
            payload = initial_payload(conv)
            assert 'comments' not in payload
            raw = deepcopy(super().structured(conv, **kwargs))
            raw['forecast']['bull'] = dict(raw['forecast']['bull'])
            raw['forecast']['bull']['comment'] = '자료는 인정해요. 미래 관계는 확인되지 않았어요.'
            self.original = deepcopy(raw['forecast'])
            return raw

    moderator = Editor(snapshot)
    run = runtime(snapshot, tmp_path, moderator=moderator)
    result = run.run()
    assert moderator.count == 1
    assert sum('forecast' in s['properties'] for _, s in moderator.calls) == 1
    assert result['verdict']['scores']['bull']['comment'] == '자료는 인정해요. 미래 관계는 확인되지 않았어요.'
    for key in ('decision', 'confidence', 'reasoning', 'decisive_evidence', 'analysis'):
        assert result['verdict'][key] == moderator.original[key]
    events = EventLog.read(run.log.path)
    assert not any(e['type'] in ('moderator_rejected', 'moderator_format_edited') for e in events)


@pytest.mark.parametrize('comment', [
    '수익률 99%가 확실해요.',
    '자료를 인정해요. 위험이 있어요.',
    '',
    'PX.CLOSE를 판정의 근거로 삼았어요.',
])
def test_comment_content_does_not_trigger_code_retries(snapshot, tmp_path, comment):
    from copy import deepcopy

    class Comment(GraphLLM):
        def structured(self, conv, **kwargs):
            assert 'comments' not in initial_payload(conv)
            raw = deepcopy(super().structured(conv, **kwargs))
            raw['forecast']['bull']['comment'] = comment
            return raw

    moderator = Comment(snapshot)
    run = runtime(snapshot, tmp_path, moderator=moderator)
    result = run.run()
    assert moderator.count == 1
    assert result['verdict']['scores']['bull']['comment'] == comment
    assert not any(e['type'] in ('moderator_rejected', 'moderator_format_edited')
                   for e in EventLog.read(run.log.path))


def test_unknown_verdict_source_is_preserved_without_code_gate(snapshot, tmp_path):
    from copy import deepcopy

    class InvalidVerdict(GraphLLM):
        def structured(self, conv, **kwargs):
            assert 'comments' not in initial_payload(conv)
            raw = deepcopy(super().structured(conv, **kwargs))
            raw['forecast']['bull']['comment'] = '자료를 인정해요. 불확실해요.'
            raw['forecast']['decisive_evidence'] = ['MISSING']
            return raw

    moderator = InvalidVerdict(snapshot)
    result = runtime(snapshot, tmp_path, moderator=moderator).run()
    assert result['verdict']['decisive_evidence'] == ['MISSING']
    assert moderator.count == 1


def test_abstention_preserves_all_six_statements(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path, actions=['ABSTAIN'])
    with pytest.raises(GraphStopped) as exc:
        run.run()
    assert exc.value.graph_status == 'abstained'
    assert len([e for e in EventLog.read(run.log.path) if e['type']=='statement_accepted']) == 6


def test_extra_round_requests_rejected_and_logged_privately(snapshot, tmp_path):
    from bullbear.graph_runtime import MediationFailed
    public = []
    run = runtime(snapshot, tmp_path, actions=['CHALLENGE_BULL']*3, emit=lambda *e: public.append(e))
    with pytest.raises(MediationFailed):
        run.run()
    rejected = [e for e in EventLog.read(run.log.path) if e['type']=='moderator_rejected']
    assert len(rejected) == 3
    assert all(e['category']=='schema_or_action' for e in rejected)
    assert not any(e[0] in ('moderator_rejected', 'extra_round_requested') for e in public)


@pytest.mark.parametrize('problem', ['value', 'source', 'analysis', 'role'])
def test_content_issues_do_not_reject_structurally_readable_statements(snapshot, tmp_path, problem):
    class Invalid(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if 'claim' in raw:
                if problem == 'value': raw['evidence'][0]['value'] = 999
                elif problem == 'source': raw['evidence'][0]['source_id'] = 'INVENTED'
                elif problem == 'analysis': raw['analysis'] = None
                else: raw['analysis']['outlook'] = 'HOLD'
            return raw
    bull = Invalid(snapshot)
    run = runtime(snapshot, tmp_path, bull=bull)
    run.run()
    events = EventLog.read(run.log.path)
    accepted = [e for e in events if e['type'] == 'statement_accepted' and e['side'] == 'bull']
    assert len(accepted) == 3
    assert not any(e['type'] == 'statement_rejected' for e in events)
    for event in accepted:
        candidate = event['statement']
        if problem == 'value': assert candidate['evidence'][0]['value'] == 999
        elif problem == 'source':
            assert candidate['evidence'][0]['source_id'] == 'INVENTED'
            assert candidate['evidence'][0]['observation'] is None
        elif problem == 'analysis': assert candidate['analysis'] is None
        else: assert candidate['analysis']['outlook'] == 'HOLD'
    assert len(bull.calls) == 3


def test_unreadable_statement_schema_still_has_bounded_retries(snapshot, tmp_path):
    class MissingClaim(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            raw.pop('claim')
            return raw

    bull = MissingClaim(snapshot)
    run = runtime(snapshot, tmp_path, bull=bull)
    with pytest.raises(LLMError):
        run.run()
    events = EventLog.read(run.log.path)
    assert len(bull.calls) == 3
    assert not any(e['type'] == 'statement_accepted' and e['side'] == 'bull' for e in events)
    rejected = [e for e in events if e['type'] == 'statement_rejected' and e['side'] == 'bull']
    assert len(rejected) == 3
    assert all(e['category'] == 'schema' and e['issues'][0]['code'] == 'invalid_schema' for e in rejected)


def test_moderator_reviews_all_statements_without_debater_self_review(snapshot, tmp_path):
    class Unsupported(GraphLLM):
        def structured(self, conv, **kwargs):
            assert 'issues' not in kwargs['schema']['properties']
            raw = super().structured(conv, **kwargs)
            if 'claim' in raw:
                raw['analysis']['interpretations'][0]['assumptions'] = ['기관 매수가 이미 발생했다']
                raw['argument'] = '조건부 해석에는 확인되지 않은 가정이 남는다 [E1].'
            return raw
    class Reviewing(GraphLLM):
        def structured(self, conv, **kwargs):
            payload = initial_payload(conv)
            assert len(payload['history']) == 6
            facts = {row['source_id']: row for row in csv.DictReader(StringIO(payload['facts_csv'], newline=''))}
            assert facts['PX.CLOSE']['value'] == '399'
            # The judge reads the full record, including each chip's assumptions.
            assert '기관 매수가 이미 발생했다' in conv.messages[1]['content']
            detail = json.loads(kwargs['tool_handler']('get_statement_details', {
                'statement_id': next(r['statement_id'] for r in payload['history'] if r['side'] == 'bull')}))
            assert detail['analysis']['interpretations'][0]['assumptions'] == ['기관 매수가 이미 발생했다']
            raw = super().structured(conv, **kwargs)
            for review in raw['forecast']['analysis']['statement_reviews']:
                if ':bull:' in review['statement_id']:
                    review.update(assessment='concern', reason='기관 매수는 스냅샷에 없는 주장이다.')
            return raw
    bull, moderator = Unsupported(snapshot), Reviewing(snapshot)
    result = runtime(snapshot, tmp_path, bull=bull, moderator=moderator).run()
    assert len(bull.calls) == 3 and len(moderator.calls) == 1
    assert sum(r['assessment']=='concern' for r in result['verdict']['analysis']['statement_reviews']) == 3
    events = EventLog.read(tmp_path/'graph.jsonl')
    accepted = [e for e in events if e['type']=='statement_accepted']
    assert len(accepted) == 6  # No literal quotation in the rebuttal body is necessary.
    assert all(e['verification_scope'] == 'not_checked' and e['verified'] is False for e in accepted)


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'unknown_source'])
def test_moderator_review_coverage_and_sources_are_not_code_checked(snapshot, tmp_path, problem):
    class InvalidReview(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            reviews = raw['forecast']['analysis']['statement_reviews']
            if problem=='missing': reviews.pop()
            elif problem=='duplicate': reviews[0]['statement_id'] = reviews[1]['statement_id']
            else: reviews[0]['source_ids'] = ['INVENTED']
            return raw
    moderator = InvalidReview(snapshot)
    result = runtime(snapshot, tmp_path, moderator=moderator).run()
    reviews = result['verdict']['analysis']['statement_reviews']
    if problem == 'missing': assert len(reviews) == 5
    elif problem == 'duplicate': assert reviews[0]['statement_id'] == reviews[1]['statement_id']
    else: assert reviews[0]['source_ids'] == ['INVENTED']
    assert moderator.count == 1



def test_final_forecast_does_not_code_check_interpretation_ids(snapshot, tmp_path):
    class BadModerator(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if raw.get('forecast'):
                raw['forecast']['analysis']['key_interpretation_ids'] = ['missing']
            return raw
    moderator = BadModerator(snapshot)
    result = runtime(snapshot, tmp_path, moderator=moderator).run()
    assert result['verdict']['analysis']['key_interpretation_ids'] == ['missing']
    assert len(moderator.calls) == 1


def test_mediation_schema_has_closed_objects_and_valid_references():
    schema = anthropic_schema(MEDIATION_SCHEMA)
    def check(item):
        if isinstance(item, dict):
            if '$ref' in item:
                assert item['$ref'].split('/')[-1] in schema['$defs']
            if item.get('type') == 'object':
                assert item['additionalProperties'] is False
                assert set(item['required']) == set(item['properties'])
            for child in item.values(): check(child)
        elif isinstance(item, list):
            for child in item: check(child)
    check(schema)


@pytest.mark.parametrize('action,expected', [('ACCEPT', 'completed'), ('ABSTAIN', 'failed'), ('ERROR', 'failed'), ('INVALID', 'failed')])
def test_live_http_uses_graph_and_preserves_usage_and_sealed_payload(setup, monkeypatch, action, expected):
    from bullbear.server import service
    settings, market = setup
    snap = market.snapshot(market.quote('005930'))
    clients = []
    class Provider(GraphLLM):
        def structured(self, conv, **kwargs):
            if action == 'ERROR' and 'forecast' in kwargs['schema']['properties']:
                raise LLMError('PRIVATE PROVIDER FAILURE')
            raw = super().structured(conv, **kwargs)
            if action == 'INVALID' and raw.get('forecast'):
                raw['forecast']['confidence'] = 'PRIVATE_INVALID_TYPE'
            return raw
    def provider(model):
        client = Provider(snap, model=model, actions=['ACCEPT' if action == 'INVALID' else action])
        client.closed = False
        client.client.close = lambda: setattr(client, 'closed', True)
        clients.append(client)
        return client
    monkeypatch.setattr(service, 'LLM', provider)
    with TestClient(app_for(setup, runner_factory=lambda: service.LiveRunner(settings))) as client:
        ident = start(client).json()['debate_id']
        result = completed(client, ident)
        assert result['status'] == expected and len(result['statements']) == 6
        assert result['generation']['base_rounds_complete'] is True
        if action == 'ACCEPT':
            assert result['engine'] == 'langgraph'
            assert set(result['verdict']['scores']) == {'bull', 'bear'}
            assert result['generation']['moderator_status'] == 'completed'
        elif action == 'INVALID':
            assert result['error']['reason'] == 'moderator_validation_failed'
            assert result['generation']['debate_complete'] is True
            assert result['generation']['moderator_status'] == 'failed'
        elif action == 'ABSTAIN':
            assert 'verdict' not in result and result['error']['reason'] == 'graph_abstained'
            assert result['generation']['moderator_status'] == 'abstained'
        else:
            assert 'verdict' not in result and result['error']['stage'] == 'moderator'
            assert result['generation']['moderator_status'] == 'failed'
            assert result['generation']['debate_complete'] is True
            assert 'PRIVATE PROVIDER FAILURE' not in json.dumps(result)
        events = parse_sse(client.get(f'/debates/{ident}/events', headers=AUTH).text)
        assert all('forecast' not in json.dumps(data) and 'reasoning' not in data
                   for _, kind, data in events if kind not in ('debate_completed', 'debate_failed'))
        manifest = json.loads((settings.data_dir/'audits'/ident/'manifest.json').read_text(encoding='utf-8'))
        assert manifest['config']['engine'] == 'langgraph'
        if action == 'ERROR':
            assert 'usage' not in result and not manifest['usage_complete']
        else:
            assert manifest['usage'] == result['usage']
        # Six statements and the moderator only; there is no statement reviewer.
        assert len(manifest['llm_calls']) == (9 if action == 'INVALID' else 7)
        assert {call['role'] for call in manifest['llm_calls']} == {'debater', 'moderator'}
        private_events = EventLog.read(settings.debate_dir / f'{ident}.jsonl')
        assert not any(event['type'] == 'statement_reviewed' for event in private_events)
        assert 'PRIVATE_INVALID_TYPE' not in json.dumps(events)
        if action == 'INVALID':
            private = EventLog.read(settings.debate_dir / f'{ident}.jsonl')
            rejected = [e for e in private if e['type'] == 'moderator_rejected']
            assert len(rejected) == 3
            assert all(e['category'] == 'schema_or_action' and e['issue_codes'] == ['invalid_mediation']
                       for e in rejected)
    assert len(clients) == 3 and all(c.closed for c in clients)


def test_cli_calls_same_graph_runner_and_waits_for_user_before_printing_verdict(snapshot, tmp_path, monkeypatch, capsys):
    from dataclasses import replace
    from types import SimpleNamespace
    from bullbear import cli
    from bullbear.config import load_settings
    from bullbear.server import service
    settings = replace(load_settings(), data_dir=tmp_path)
    snapshot.save(settings.snapshot_dir)
    monkeypatch.setattr(service, 'LLM', lambda model: GraphLLM(snapshot, model=model))
    def judge():
        assert '중재자 판정:' not in capsys.readouterr().out
        return cli.Decision.HOLD, '조건부 판단'
    monkeypatch.setattr(cli, '_ask_user', judge)
    cli.cmd_debate(SimpleNamespace(snapshot=snapshot.snapshot_id, ticker=snapshot.ticker,
                                  no_judge=False, max_extra_rounds=0), settings)
    assert '중재자 판정:' in capsys.readouterr().out
    events = EventLog.read(next(settings.debate_dir.glob('*.jsonl')))
    assert any(e['type'] == 'user_verdict' for e in events)


def test_progress_distinguishes_partial_fixed_rounds_from_legacy_graph():
    from bullbear.server.progress import generation_progress
    events = []
    for stage in ('opening', 'rebuttal', 'closing'):
        for side in ('bull', 'bear'):
            events.append({'type':'turn_started', 'data':json.dumps({'side':side, 'round':stage,
                'engine':'langgraph', 'debate_flow':'fixed_three_rounds'})})
            events.append({'type':'statement_accepted', 'data':json.dumps({'side':side, 'round':stage})})
        result = generation_progress(events, terminal='failed')
        assert result['debate_complete'] == (stage=='closing')
    legacy = [dict(e, data=e['data'].replace(', "debate_flow": "fixed_three_rounds"','')) for e in events[:4]]
    assert generation_progress(legacy)['base_rounds_complete'] is True


def test_rebuttal_failure_preserves_openings_without_calling_moderator(snapshot, tmp_path):
    class FailedRebuttal(GraphLLM):
        def structured(self, conv, **kwargs):
            if 'claim' in kwargs['schema']['properties'] and initial_payload(conv)['round']=='rebuttal':
                raise LLMError('rebuttal failed')
            return super().structured(conv, **kwargs)
    run = runtime(snapshot, tmp_path, bull=FailedRebuttal(snapshot))
    with pytest.raises(LLMError):
        run.run()
    events = EventLog.read(run.log.path)
    assert len([e for e in events if e['type']=='statement_accepted' and e['round']=='opening']) == 2
    assert not run.moderator.calls


def test_rebuttal_target_outside_opponent_statements_is_retried(snapshot, tmp_path):
    """Observed: a model filled the rebuttal row with prose, so the target ID field
    held text. With no reviewer, the target must name a real opponent statement."""
    class InvalidTargetOnce(GraphLLM):
        invented = False
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if raw.get('analysis', {}).get('rebuttal') and not self.invented:
                self.invented = True
                raw['analysis']['rebuttal']['target_statement_id'] = '[@S2] "인용": 평가'
            return raw
    run = runtime(snapshot, tmp_path, bull=InvalidTargetOnce(snapshot))
    run.run()
    assert len(run.moderator.calls) == 1 and len(run.bull.calls) == 4
    events = EventLog.read(run.log.path)
    rejected = [(e['side'], e['round']) for e in events if e['type'] == 'statement_rejected']
    assert rejected == [('bull', 'rebuttal')]
    accepted = {(e['side'], e['round']): e['statement'] for e in events if e['type'] == 'statement_accepted'}
    target = accepted[('bull', 'rebuttal')]['analysis']['rebuttal']['target_statement_id']
    assert target == accepted[('bear', 'opening')]['statement_id']

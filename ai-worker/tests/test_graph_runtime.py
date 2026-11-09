import json
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime, GraphStopped, MEDIATION_SCHEMA
from bullbear.llm import LLMError, anthropic_schema
from bullbear.schemas import Side
from bullbear.snapshot import build_snapshot
from .fakes import NOW, FakeSource
from .graph_fakes import GraphLLM
from .test_server import setup, app_for, start, completed, AUTH, parse_sse


@pytest.fixture
def snapshot():
    return build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)


def test_return_sign_failure_is_rewritten_before_publication(snapshot, tmp_path):
    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'return_context' in json.loads(conv.messages[0]['content'])
            if self.count == 1:
                raw['argument'] = '상대수익은 -0.84%p로 코스피보다 더 올랐습니다 [E1].'
            return raw
    llm = WrongFirst(snapshot)
    run = runtime(snapshot, tmp_path, bull=llm)
    run.run()
    events = EventLog.read(run.log.path)
    assert any(e['type'] == 'statement_rejected' and
               any(i['code'] == 'relative_return_sign' for i in e['issues']) for e in events)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert len(accepted) == 6
    assert all('더 올랐습니다' not in e['statement']['argument'] for e in accepted)


def test_moderator_return_sign_failure_is_rewritten(snapshot, tmp_path):
    class WrongModerator(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'return_context' in json.loads(conv.messages[0]['content'])
            if self.count == 1:
                raw['forecast']['reasoning'] = '7거래일 코스피 대비 상대수익 -0.84%p로 코스피보다 더 올랐습니다 [E1].'
            return raw
    run = runtime(snapshot, tmp_path, moderator=WrongModerator(snapshot))
    result = run.run()
    assert '더 올랐습니다' not in result['verdict']['reasoning']
    assert any(e['type'] == 'moderator_rejected' and
               any(i['code'] == 'relative_return_sign' for i in e.get('issues', []))
               for e in EventLog.read(run.log.path))


@pytest.mark.parametrize('bad_text,expected_code', [
    ('발표 다음 날 장중 급락했다는 기사입니다 [E1].', 'news_relative_date'),
    ('PER은 8.46배로 낮은 편이라 회복 여지가 있습니다 [E1].', 'per_without_comparison'),
])
def test_source_wording_is_corrected_before_publication(snapshot, tmp_path, bad_text, expected_code):
    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'source_context' in json.loads(conv.messages[0]['content'])
            if self.count == 1:
                raw['argument'] = bad_text
            return raw
    run = runtime(snapshot, tmp_path, bull=WrongFirst(snapshot))
    run.run()
    events = EventLog.read(run.log.path)
    assert any(e['type'] == 'statement_rejected' and
               any(i['code'] == expected_code for i in e['issues']) for e in events)
    assert all(e['statement']['argument'] != bad_text for e in events if e['type'] == 'statement_accepted')


def test_moderator_per_is_corrected_before_publication(snapshot, tmp_path):
    class WrongFirst(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            assert 'source_context' in json.loads(conv.messages[0]['content'])
            if self.count == 1:
                raw['forecast']['reasoning'] = '7거래일 코스피 대비 PER 8.46배로 낮은 편이라 반등을 예상합니다 [E1].'
            return raw
    run = runtime(snapshot, tmp_path, moderator=WrongFirst(snapshot))
    run.run()
    assert any(e['type'] == 'moderator_rejected' and
               any(i['code'] == 'per_without_comparison' for i in e.get('issues', []))
               for e in EventLog.read(run.log.path))


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
    for side, client in (('bull', run.bull), ('bear', run.bear)):
        calls = [json.loads(c.messages[0]['content']) for c, schema in client.calls if 'claim' in schema['properties']]
        assert [c['round'] for c in calls] == ['opening', 'rebuttal', 'closing']
        assert [len(c['history']) for c in calls] == [0, 2, 4]
    events = EventLog.read(run.log.path)
    accepted = [e for e in events if e['type'] == 'statement_accepted']
    assert [e['round'] for e in accepted] == ['opening']*2 + ['rebuttal']*2 + ['closing']*2
    assert all(e['statement']['analysis']['outlook'] == ('BUY' if e['side']=='bull' else 'SELL') for e in accepted)
    assert events.index(next(e for e in events if e['type']=='moderator_started')) > events.index(accepted[-1])


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


@pytest.mark.parametrize('problem', ['value', 'source', 'analysis', 'private', 'role'])
def test_invalid_statements_never_publish_and_retry_is_bounded(snapshot, tmp_path, problem):
    class Invalid(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if 'claim' in raw:
                if problem == 'value': raw['evidence'][0]['value'] = 999
                elif problem == 'source': raw['evidence'][0]['source_id'] = 'INVENTED'
                elif problem == 'analysis': raw['analysis'] = None
                elif problem == 'role': raw['analysis']['outlook'] = 'HOLD'
                else: raw['analysis']['interpretations'][0]['assumptions'] = ['K.private']
            return raw
    bull = Invalid(snapshot)
    run = runtime(snapshot, tmp_path, bull=bull)
    with pytest.raises(LLMError):
        run.run()
    events = EventLog.read(run.log.path)
    assert not any(e['type'] == 'statement_accepted' and e['side'] == 'bull' for e in events)
    assert len(bull.calls) == 3


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
            payload = json.loads(conv.messages[0]['content'])
            assert len(payload['history']) == 6
            assert payload['facts']['PX.CLOSE']['value'] == 399
            assert '기관 매수가 이미 발생했다' in conv.messages[0]['content']
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
    assert all(e['verification_scope']=='source_values_and_structure' for e in accepted)


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'unknown_source'])
def test_moderator_review_coverage_and_sources_are_checked(snapshot, tmp_path, problem):
    class InvalidReview(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            reviews = raw['forecast']['analysis']['statement_reviews']
            if problem=='missing': reviews.pop()
            elif problem=='duplicate': reviews[0]['statement_id'] = reviews[1]['statement_id']
            else: reviews[0]['source_ids'] = ['INVENTED']
            return raw
    with pytest.raises(LLMError):
        runtime(snapshot, tmp_path, moderator=InvalidReview(snapshot)).run()



def test_final_forecast_rejects_nonexistent_interpretation(snapshot, tmp_path):
    class BadModerator(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if raw.get('forecast'):
                raw['forecast']['analysis']['key_interpretation_ids'] = ['missing']
            return raw
    moderator = BadModerator(snapshot)
    with pytest.raises(LLMError):
        runtime(snapshot, tmp_path, moderator=moderator).run()
    assert len(moderator.calls) == 3


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


def test_frozen_rag_context_reaches_graph_generators_and_reviews_once(snapshot, tmp_path):
    from .test_rag_agents import context_for
    context = context_for(snapshot)
    clients = [GraphLLM(snapshot) for _ in range(3)]
    events = []
    result = GraphRuntime(snapshot, debate_id='context', bull=clients[0], bear=clients[1], moderator=clients[2],
        log=EventLog(tmp_path/'context.jsonl'), background_context=context,
        emit=lambda kind, data: events.append((kind, data))).run()
    assert result['graph_status'] == 'accepted'
    for client in clients:
        assert len(client.calls) == (1 if client is clients[2] else 3)
        for conv, _ in client.calls:
            assert conv.system.count('RAG_UNIQUE_DEFINITION') == 1
            assert 'RAG_UNIQUE_DEFINITION' not in conv.messages[0]['content']
    assert 'RAG_UNIQUE_DEFINITION' not in str(events)


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
                raw['forecast']['analysis']['key_interpretation_ids'] = ['PRIVATE_INVALID_ID']
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
        assert len(manifest['llm_calls']) == (9 if action == 'INVALID' else 7)
        assert 'PRIVATE_INVALID_ID' not in json.dumps(events)
        if action == 'INVALID':
            private = EventLog.read(settings.debate_dir / f'{ident}.jsonl')
            rejected = [e for e in private if e['type'] == 'moderator_rejected']
            assert len(rejected) == 3
            assert all(e['issues'][0]['code'] == 'interpretation_target' for e in rejected)
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
            if 'claim' in kwargs['schema']['properties'] and json.loads(conv.messages[0]['content'])['round']=='rebuttal':
                raise LLMError('rebuttal failed')
            return super().structured(conv, **kwargs)
    run = runtime(snapshot, tmp_path, bull=FailedRebuttal(snapshot))
    with pytest.raises(LLMError):
        run.run()
    events = EventLog.read(run.log.path)
    assert len([e for e in events if e['type']=='statement_accepted' and e['round']=='opening']) == 2
    assert not run.moderator.calls


def test_invalid_structured_opponent_is_still_rejected(snapshot, tmp_path):
    class InvalidTarget(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if raw.get('analysis', {}).get('rebuttal'):
                raw['analysis']['rebuttal']['target_statement_id'] = 'invented-opponent'
            return raw
    run = runtime(snapshot, tmp_path, bull=InvalidTarget(snapshot))
    with pytest.raises(LLMError): run.run()
    assert not run.moderator.calls
    rejected = [e for e in EventLog.read(run.log.path) if e['type']=='statement_rejected']
    assert any(i['code']=='structured_rebuttal_target' for e in rejected for i in e['issues'])

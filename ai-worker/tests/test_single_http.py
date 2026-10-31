import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bullbear.events import EventLog
from bullbear.llm import LLMError
from bullbear.server import service as service_module
from bullbear.server.store import Store
from bullbear.single import SingleAnalyst, SINGLE_VERDICT_SCHEMA
from .http_fixture import TestRunner, prepare_rag
from .test_server import setup, app_for, start, completed, parse_sse, AUTH


def verdict():
    return {'decision': 'HOLD', 'confidence': 0.55,
            'reasoning': '7거래일 코스피 대비 비슷한 움직임을 예상하지만 종가만으로 방향을 확신하기 어렵습니다 [E1].',
            'decisive_evidence': ['PX.CLOSE']}


class SingleRunner(TestRunner):
    def run_single(self, snapshot, debate_id, emit):
        if self.gate:
            assert self.gate.wait(10)
        emit('moderator_started', {})
        for event in ('token', 'tool_call', 'turn_started', 'statement_accepted', 'moderator_evaluated'):
            emit(event, {'private': 'DO_NOT_EXPOSE'})
        if self.invalid:
            raise LLMError('secret provider error')
        return {'debate_id': debate_id, 'verdict': {**verdict(), 'scores': None}, 'stats': None}


def seed(app, settings, market, *, suffix=''):
    snapshot = market.snapshot(market.quote('005930'))
    if suffix:
        snapshot = snapshot.model_copy(update={'snapshot_id': snapshot.snapshot_id + suffix})
    store = app.state.service.store
    row, _ = store.create('seed' + suffix, 'seed' + suffix, snapshot.ticker, str(snapshot.as_of), 2,
                          snapshot_id=snapshot.snapshot_id)
    store.save_snapshot(row['id'], snapshot)
    store.emit(row['id'], 'debate_completed', {})
    return snapshot, row['id']


def test_single_contract_validation_and_explicit_snapshot_never_fetches_market(setup, monkeypatch):
    settings, market = setup
    app = app_for(setup, runner_factory=lambda: SingleRunner(settings))
    with TestClient(app) as c:
        snapshot, debate_id = seed(app, settings, market)
        def offline(*args):
            raise AssertionError('explicit snapshot must not fetch data')
        monkeypatch.setattr(market, 'quote', offline)
        monkeypatch.setattr(market, 'snapshot', offline)
        for body in ({'mode': 'single'}, {'mode': 'invalid'}, {'mode': 'single', 'snapshot_id': ''}):
            assert start(c, **body).status_code == 400
        assert start(c, mode='single', snapshot_id='missing').status_code == 404
        assert start(c, ticker='000660', mode='single', snapshot_id=snapshot.snapshot_id).status_code == 400
        response = start(c, mode='single', snapshot_id=snapshot.snapshot_id)
        assert response.status_code == 202
        accepted = response.json()
        assert accepted['snapshot_id'] == snapshot.snapshot_id and not accepted['reused']
        assert accepted['debate_id'] != debate_id
        result = completed(c, accepted['debate_id'])
        assert result['status'] == 'completed' and result['statements'] == []
        assert result['stats'] is None and result['verdict']['scores'] is None
        assert set(result['verdict']) == {'decision', 'confidence', 'reasoning', 'decisive_evidence', 'scores'}
        assert result['usage']['calls']
        events_url = f"/debates/{accepted['debate_id']}/events"
        events = parse_sse(c.get(events_url, headers=AUTH).text)
        assert [e[1] for e in events] == ['snapshot_created', 'moderator_started', 'debate_completed']
        assert 'DO_NOT_EXPOSE' not in str(events)
        replay = parse_sse(c.get(events_url, headers={**AUTH, 'Last-Event-ID': str(events[1][0])}).text)
        assert replay == events[2:]
        reused = start(c, key='r2', mode='single', snapshot_id=snapshot.snapshot_id).json()
        assert reused['reused'] and reused['debate_id'] == accepted['debate_id']
        assert start(c, key='r1', snapshot_id=snapshot.snapshot_id).status_code == 409
        assert start(c, key='r3', snapshot_id=snapshot.snapshot_id).json()['debate_id'] == debate_id
        manifest = json.loads((settings.data_dir / 'audits' / accepted['debate_id'] / 'manifest.json').read_text())
        assert manifest['config']['mode'] == 'single' and manifest['config']['first_side'] is None
        assert manifest['snapshot'] == snapshot.model_dump(mode='json')


def test_concurrent_single_reuse_shared_capacity_and_distinct_snapshots(setup):
    settings, market = setup
    gate = threading.Event()
    app = app_for(setup, runner_factory=lambda: SingleRunner(settings, gate=gate), max_running=1)
    with TestClient(app) as c:
        snapshot, _ = seed(app, settings, market)
        other, _ = seed(app, settings, market, suffix='-other')
        try:
            def post(n):
                return start(c, key=f'r{n}', mode='single', snapshot_id=snapshot.snapshot_id).json()
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(post, range(8)))
            assert len({r['debate_id'] for r in responses}) == 1
            assert sum(not r['reused'] for r in responses) == 1
            assert start(c, key='other', mode='single', snapshot_id=other.snapshot_id).status_code == 429
            assert start(c, key='debate-capacity', ticker='000660').status_code == 429
            assert start(c, key='r0', mode='single', snapshot_id=other.snapshot_id).status_code == 409
        finally:
            gate.set()
        completed(c, responses[0]['debate_id'])
        response = start(c, key='other', mode='single', snapshot_id=other.snapshot_id).json()
        assert not response['reused'] and response['debate_id'] != responses[0]['debate_id']
        assert completed(c, response['debate_id'])['status'] == 'completed'


def test_failed_single_retry_and_persisted_result(setup):
    settings, market = setup
    app = app_for(setup, runner_factory=lambda: SingleRunner(settings, invalid=True))
    with TestClient(app) as c:
        snapshot, _ = seed(app, settings, market)
        first = start(c, mode='single', snapshot_id=snapshot.snapshot_id).json()
        failed = completed(c, first['debate_id'])
        assert failed['status'] == 'failed' and failed['error']['code'] == 'LLM_ERROR'
        assert 'secret' not in str(failed) and failed['usage']
        assert start(c, mode='single', snapshot_id=snapshot.snapshot_id).json()['debate_id'] == first['debate_id']
    with TestClient(app_for(setup, runner_factory=lambda: SingleRunner(settings))) as c:
        assert c.get('/debates/' + first['debate_id'], headers=AUTH).json() == failed
        second = start(c, key='retry', mode='single', snapshot_id=snapshot.snapshot_id).json()
        assert second['debate_id'] != first['debate_id'] and not second['reused']
        assert completed(c, second['debate_id'])['status'] == 'completed'


def test_store_migrates_old_database_and_keeps_legacy_idempotency(tmp_path):
    with sqlite3.connect(tmp_path / 'worker.sqlite3') as db:
        db.execute('CREATE TABLE debates (id TEXT PRIMARY KEY,ticker TEXT NOT NULL,data_date TEXT NOT NULL,snapshot_id TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL)')
        db.execute("INSERT INTO debates VALUES ('old','005930','2026-10-30','snap','completed','2026-10-30')")
    store = Store(tmp_path)
    try:
        assert store.get('old')['mode'] == 'debate'
        old, reused = store.create('legacy', 'fp', '005930', '2026-10-30', 2)
        assert reused and old['id'] == 'old'
        single, reused = store.create('single', 'single-fp', '005930', '2026-10-30', 2, mode='single', snapshot_id='snap')
        assert not reused and single['id'] != 'old'
    finally:
        store.close()


class ScriptedLLM:
    model = 'claude-sonnet-5-5'
    def __init__(self, outputs):
        self.outputs, self.calls = iter(outputs), []
        self.client = SimpleNamespace(close=lambda: None)

    def structured(self, conv, **kwargs):
        self.calls.append((conv, kwargs))
        return next(self.outputs)

    def usage_payload(self):
        return {'calls': [{'model': 'claude-sonnet-5-5', 'input_tokens': len(self.calls) * 10, 'output_tokens': 5}]}


@pytest.mark.parametrize('bad', [
    {'confidence': 2}, {'decisive_evidence': ['UNKNOWN']},
    {'reasoning': '장기 상승을 예상합니다 [E1].'},
    {'reasoning': '7거래일 코스피 대비 비슷한 움직임을 예상합니다 [E2].'},
    {'reasoning': '7거래일 코스피 대비 비슷한 움직임을 예상합니다 [K1].'},
])
def test_single_rejects_invalid_verdict_before_semantic_review(setup, bad):
    settings, market = setup
    snapshot = market.snapshot(market.quote('005930'))
    llm = ScriptedLLM([{**verdict(), **bad}] * 3)
    with pytest.raises(LLMError):
        SingleAnalyst(llm, snapshot).evaluate(EventLog(settings.data_dir / 'single.jsonl'))
    assert len(llm.calls) == 3
    assert all(call[1]['schema'] == SINGLE_VERDICT_SCHEMA for call in llm.calls)


def test_live_runner_single_uses_only_moderator_and_records_audit(setup, monkeypatch):
    settings, market = setup
    llm = ScriptedLLM([verdict(), {'issues': []}])
    models = []
    def make_llm(model):
        models.append(model)
        return llm
    monkeypatch.setattr(service_module, 'LLM', make_llm)
    monkeypatch.setenv('BULLBEAR_MODERATOR_MODEL', 'claude-sonnet-5-5')
    app = app_for(setup, runner_factory=lambda: service_module.LiveRunner(settings))
    with TestClient(app) as c:
        snapshot, _ = seed(app, settings, market)
        response = start(c, mode='single', snapshot_id=snapshot.snapshot_id).json()
        result = completed(c, response['debate_id'])
        assert result['status'] == 'completed'
        assert models == ['claude-sonnet-5-5']
        assert len(llm.calls) == 2
        review = json.loads(llm.calls[1][0].messages[0]['content'])
        assert review['history'] == [] and review['verification_stats'] is None
        assert review['reference_map'] == {'E1': 'PX.CLOSE'}
        manifest = json.loads((settings.data_dir / 'audits' / response['debate_id'] / 'manifest.json').read_text())
        assert len(manifest['llm_calls']) == 2 and manifest['usage'] == result['usage']


def test_explicit_debate_snapshot_and_legacy_default_idempotency(setup, monkeypatch):
    settings, market = setup
    app = app_for(setup)
    with TestClient(app) as c:
        first = start(c).json()
        result = completed(c, first['debate_id'])
        assert start(c, mode='debate').json()['debate_id'] == first['debate_id']
        other = market.snapshot(market.quote('005930')).model_copy(update={'snapshot_id': result['snapshot_id'] + '-changed'})
        with app.state.service.store.transaction() as db:
            db.execute('INSERT INTO snapshots VALUES (?,?)', (other.snapshot_id, other.model_dump_json()))
        monkeypatch.setattr(market, 'quote', lambda *args: pytest.fail('fresh quote requested'))
        second = start(c, key='different-snapshot', snapshot_id=other.snapshot_id).json()
        assert not second['reused'] and second['debate_id'] != first['debate_id']
        assert completed(c, second['debate_id'])['snapshot_id'] == other.snapshot_id


def test_single_semantic_rejection_requires_regeneration(setup):
    settings, market = setup
    snapshot = market.snapshot(market.quote('005930'))
    llm = ScriptedLLM([verdict(), {'issues': [{'code': 'unsupported_inference',
        'quote': '종가만으로 방향을 확신하기 어렵습니다', 'message': '검수 반려 테스트'}]}, verdict(), {'issues': []}])
    analyst = SingleAnalyst(llm, snapshot)
    result = analyst.evaluate(EventLog(settings.data_dir / 'single.jsonl'))
    assert result.decision.value == 'HOLD' and len(llm.calls) == 4
    assert len(analyst.reviewer.records) == 2
    assert '검수 반려 테스트' in llm.calls[2][0].messages[-1]['content']


def test_single_rag_is_private_and_shared_with_reviewer(setup, monkeypatch):
    settings, market = setup
    settings = prepare_rag(settings)
    llm = ScriptedLLM([verdict(), {'issues': []}])
    monkeypatch.setattr(service_module, 'LLM', lambda model: llm)
    app = app_for((settings, market), runner_factory=lambda: service_module.LiveRunner(settings))
    with TestClient(app) as c:
        snapshot, _ = seed(app, settings, market)
        response = start(c, mode='single', snapshot_id=snapshot.snapshot_id).json()
        result = completed(c, response['debate_id'])
        assert result['status'] == 'completed'
        assert all('PRIVATE_RAG_BACKGROUND' in call[0].system for call in llm.calls)
        events = c.get('/debates/' + response['debate_id'] + '/events', headers=AUTH).text
        assert 'PRIVATE_RAG_BACKGROUND' not in events

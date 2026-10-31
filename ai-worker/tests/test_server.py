import json
import subprocess
import sys
import threading
import time
from importlib import import_module
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from bullbear.config import load_settings
from bullbear.data import DataUnavailable
from bullbear.server.app import create_app
from bullbear.server.store import Store
from .fakes import NOW
from .http_fixture import TestRunner, fixture_market

AUTH = {'X-Worker-Token': 'test-token'}


@pytest.fixture
def setup(tmp_path):
    settings = replace(load_settings(), data_dir=tmp_path)
    market = fixture_market(settings)
    try:
        yield settings, market
    finally:
        market.close()


def app_for(setup, **kw):
    settings, market = setup
    kw.setdefault('runner_factory', lambda: TestRunner(settings))
    return create_app(settings=settings, market=market, token='test-token', **kw)


def start(client, key='r1', ticker='005930', **kw):
    return client.post('/debates', json={'ticker': ticker, 'request_id': key, **kw}, headers=AUTH)


def completed(client, debate_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(f'/debates/{debate_id}', headers=AUTH).json()
        if body['status'] != 'running':
            return body
        time.sleep(0.01)
    pytest.fail('debate did not finish')


def parse_sse(text):
    records = []
    for block in text.split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line and not line.startswith(':'))
        if 'id' in fields:
            records.append((int(fields['id']), fields['event'], json.loads(fields['data'])))
    return records


def test_auth_validation_and_not_found(setup):
    with TestClient(app_for(setup)) as c:
        assert c.get('/health').json() == {'status': 'UP'}
        for path in ['/stocks/search?q=x', '/stocks/005930', '/stocks/005930/eligibility',
                     '/debates/missing', '/debates/missing/events', '/snapshots/missing',
                     '/prices/daily', '/indices/daily']:
            assert c.get(path).status_code == 401
        assert c.post('/debates', json={}).status_code == 401
        for path in ['/stocks/999999', '/debates/missing', '/debates/missing/events', '/snapshots/missing']:
            assert c.get(path, headers=AUTH).json()['error']['code'] == 'NOT_FOUND'
        assert start(c, max_extra_rounds=-1).status_code == 400
        assert c.get('/prices/daily?ticker=005930&from=bad&to=2026-10-16', headers=AUTH).status_code == 400
        assert c.get('/indices/daily?code=INVALID&from=2026-10-15&to=2026-10-16', headers=AUTH).status_code == 404
        assert start(c, ticker='005935').json()['error']['reasons']


@pytest.mark.parametrize('token', ['', 'wrong', 'test-token ', 'test-toke'])
def test_invalid_token_cannot_create_or_read_a_debate(setup, token):
    with TestClient(app_for(setup)) as c:
        headers = {'X-Worker-Token': token}
        assert c.post('/debates', json={'ticker': '005930', 'request_id': 'unauthorized'}, headers=headers).status_code == 401
        assert c.get('/debates/missing/events', headers=headers).status_code == 401
        assert c.app.state.service.store.db.execute('SELECT count(*) FROM debates').fetchone()[0] == 0


def test_application_closes_its_own_market(setup, monkeypatch):
    owned_market = fixture_market(setup[0])
    monkeypatch.setattr(import_module('bullbear.server.app'), 'Market', lambda settings: owned_market)
    with TestClient(create_app(settings=setup[0], token='test-token')) as c:
        assert c.get('/health').status_code == 200
    assert owned_market.closed


def test_quote_search_confirmed_prices_and_snapshot_agree(setup):
    setup[1].now = lambda: NOW.replace(hour=10)
    with TestClient(app_for(setup)) as c:
        items = c.get('/stocks/search?q=ㅅㅅㅈㅈ', headers=AUTH).json()['items']
        assert len(items) == 2 and items[0]['eligible'] and not items[1]['eligible']
        quote = c.get('/stocks/005930', headers=AUTH).json()
        assert quote['as_of'] == '2026-10-15'
        result = completed(c, start(c).json()['debate_id'])
        snap = c.get('/snapshots/' + result['snapshot_id'], headers=AUTH).json()
        assert snap['as_of'] == quote['as_of']
        assert snap['facts']['PX.CLOSE']['value'] == quote['close']
        for path in ['/prices/daily?ticker=005930', '/indices/daily?code=KOSPI']:
            rows = c.get(path + '&from=2026-10-14&to=2099-01-01', headers=AUTH).json()['items']
            assert [r['date'] for r in rows] == ['2026-10-14', '2026-10-15']


def test_replay_resume_contract_and_private_data_filter(setup):
    with TestClient(app_for(setup, runner_factory=lambda: TestRunner(setup[0], extra=True))) as c:
        started = start(c)
        assert started.status_code == 202
        debate_id = started.json()['debate_id']
        result = completed(c, debate_id)
        assert result['status'] == 'completed' and len(result['statements']) == 8
        assert set(result['verdict']['scores']) == {'bull', 'bear'}
        assert result['usage']['calls'][0]['cache_creation_input_tokens'] == 5
        url = f'/debates/{debate_id}/events'
        response = c.get(url, headers=AUTH)
        assert response.headers['content-type'].startswith('text/event-stream')
        assert 'PRIVATE' not in response.text
        events = parse_sse(response.text)
        assert [e[0] for e in events] == list(range(1, len(events) + 1))
        assert events[0][1] == 'snapshot_created' and events[-1][1] == 'debate_completed'
        assert any(e[1] == 'statement_rejected' for e in events)
        accepted = [e[2] for e in events if e[1] == 'statement_accepted']
        assert all(e['verified'] and 'warnings' in e and 'verification' not in e for e in accepted)
        assert next(e[2] for e in events if e[1] == 'tool_call') == {'side': 'bull', 'tool': 'get_price'}
        assert parse_sse(c.get(url, headers={**AUTH, 'Last-Event-ID': '3'}).text) == events[3:]
        assert c.get(url, headers={**AUTH, 'Last-Event-ID': str(events[-1][0])}).text == ''
        assert c.get(url, headers={**AUTH, 'Last-Event-ID': 'invalid'}).status_code == 400


def test_concurrent_idempotency_capacity_and_live_stream(setup):
    gate = threading.Event()
    with TestClient(app_for(setup, max_running=1, runner_factory=lambda: TestRunner(setup[0], gate=gate))) as c:
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda _: start(c).json(), range(8)))
            assert len({r['debate_id'] for r in responses}) == 1
            assert sum(not r['reused'] for r in responses) == 1
            debate_id = responses[0]['debate_id']
            assert start(c, key='r2').json()['debate_id'] == debate_id
            assert start(c, ticker='000660').status_code == 409
            busy = start(c, key='other', ticker='000660')
            assert busy.status_code == 429 and busy.headers['retry-after'] == '5'
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(c.get, f'/debates/{debate_id}/events', headers=AUTH)
                gate.set()
                events = parse_sse(pending.result(timeout=5).text)
            assert events[-1][1] == 'debate_completed'
        finally:
            gate.set()


def test_failed_verification_never_emits_statement_and_releases_capacity(setup):
    with TestClient(app_for(setup, max_running=1, runner_factory=lambda: TestRunner(setup[0], invalid=True))) as c:
        d = start(c).json()['debate_id']
        result = completed(c, d)
        assert result['status'] == 'failed' and result['error']['code'] == 'LLM_ERROR'
        assert result['statements'] == [] and result['usage']['calls']
        assert start(c).json()['debate_id'] == d
        assert start(c, key='retry').json()['debate_id'] != d


def test_durable_replay_idempotency_and_restart_failure(setup):
    with TestClient(app_for(setup)) as c:
        d = start(c).json()['debate_id']
        completed(c, d)
        before = c.get(f'/debates/{d}/events', headers=AUTH).text
    with TestClient(app_for(setup)) as c:
        assert start(c).json()['debate_id'] == d
        assert c.get(f'/debates/{d}/events', headers=AUTH).text == before
        # A caller-owned Market remains usable across application lifespans.
        restarted = start(c, key='after-restart', ticker='000660')
        assert restarted.status_code == 202
        assert completed(c, restarted.json()['debate_id'])['status'] == 'completed'
    path = setup[0].data_dir / 'http'
    store = Store(path)
    row, _ = store.create('crashed', 'fingerprint', '000660', '2026-10-19', 2)
    store.emit(row['id'], 'turn_started', {'side': 'bull', 'round': 'opening'})
    with pytest.raises(RuntimeError, match='프로세스 하나'):
        Store(path)
    store.close()
    store = Store(path)
    try:
        assert store.get(row['id'])['status'] == 'failed'
        assert store.events(row['id'])[-1]['type'] == 'debate_failed'
    finally:
        store.close()


def test_provider_failure_is_sanitized(setup):
    def unavailable(*args):
        raise DataUnavailable('secret-key-must-not-leak')
    setup[1].source.get_daily_prices = unavailable
    with TestClient(app_for(setup)) as c:
        res = c.get('/stocks/005930', headers=AUTH)
        assert res.status_code == 503 and 'secret-key' not in res.text


def test_cold_quote_is_bounded_shared_and_keeps_snapshot_consistent(setup):
    market = setup[1]
    market.quote_wait_seconds = 0.01
    original = market.source.get_daily_prices
    gate, entered = threading.Event(), threading.Event()
    calls = []

    def slow_prices(ticker, start, end):
        calls.append((ticker, start, end))
        entered.set()
        assert gate.wait(10)
        return original(ticker, start, end)

    market.source.get_daily_prices = slow_prices
    with TestClient(app_for(setup)) as c:
        with ThreadPoolExecutor(max_workers=8) as pool:
            try:
                requests = [pool.submit(c.get, '/stocks/005930', headers=AUTH) for _ in range(8)]
                assert entered.wait(2)
                # All requests finish while the provider remains blocked.
                responses = [request.result(timeout=2) for request in requests]
                assert all(response.status_code == 503 for response in responses)
                assert all(response.json()['error']['code'] == 'DATA_UNAVAILABLE' for response in responses)
                pending_debate = pool.submit(start, c)
                assert pending_debate.result(timeout=2).status_code == 503
                assert len(calls) == 1
            finally:
                gate.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            quote = c.get('/stocks/005930', headers=AUTH)
            if quote.status_code == 200:
                break
            time.sleep(0.01)
        assert quote.status_code == 200
        quote = quote.json()
        assert len(quote['sparkline']) == 60
        created = start(c)
        assert created.status_code == 202 and not created.json()['reused']
        result = completed(c, created.json()['debate_id'])
        snap = c.get('/snapshots/' + result['snapshot_id'], headers=AUTH).json()
        assert snap['as_of'] == quote['as_of']
        assert snap['facts']['PX.CLOSE']['value'] == quote['close']
        assert 'PX.RET_1Y' in snap['facts']
        assert len(calls) == 1


def test_snapshot_is_built_after_202_and_failure_is_terminal(setup):
    gate = threading.Event()
    def slow_snapshot(quote):
        assert gate.wait(5)
        raise DataUnavailable('private provider detail')
    setup[1].snapshot = slow_snapshot
    with TestClient(app_for(setup)) as c:
        try:
            res = start(c)
            assert res.status_code == 202 and res.json()['snapshot_id'] is None
            d = res.json()['debate_id']
            assert c.get(f'/debates/{d}', headers=AUTH).json()['status'] == 'running'
        finally:
            gate.set()
        result = completed(c, d)
        assert result['status'] == 'failed' and result['error']['code'] == 'DATA_UNAVAILABLE'
        assert 'private provider' not in str(result)


def test_live_runner_uses_pipeline_and_contract_verdict(setup, monkeypatch):
    from bullbear.server import service
    from .fakes import ScriptedDebater, ScriptedModerator, statement
    class Client:
        def __init__(self, model):
            self.client = self
        def usage_payload(self):
            return {'calls': [{'model': 'model', 'input_tokens': 2, 'output_tokens': 1,
                               'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 1}]}
        def close(self):
            pass
    monkeypatch.setattr(service, 'LLM', Client)
    monkeypatch.setattr(service, 'Debater', lambda llm, snap, **kw: ScriptedDebater(statement(('E1', 'PX.CLOSE', 399))))
    monkeypatch.setattr(service, 'Moderator', lambda *a, **kw: ScriptedModerator(['verdict']))
    with TestClient(app_for(setup, runner_factory=lambda: service.LiveRunner(setup[0]))) as c:
        result = completed(c, start(c).json()['debate_id'])
        assert result['status'] == 'completed'
        assert len(result['statements']) == 6
        assert 'bull' not in result['verdict'] and 'action' not in result['verdict']
        assert set(result['verdict']['scores']) == {'bull', 'bear'}
        assert result['usage']['calls'][0]['cache_creation_input_tokens'] == 2


def test_submit_failure_is_terminal_and_capacity_is_released(setup, monkeypatch):
    app = app_for(setup, max_running=1)
    with TestClient(app) as c:
        original = app.state.service.pool.submit
        def rejected(*args):
            raise RuntimeError('private executor detail')
        monkeypatch.setattr(app.state.service.pool, 'submit', rejected)
        response = start(c)
        assert response.status_code == 202
        failed = completed(c, response.json()['debate_id'])
        assert failed['status'] == 'failed'
        assert 'private executor' not in json.dumps(failed)
        assert start(c).json()['debate_id'] == failed['debate_id']
        monkeypatch.setattr(app.state.service.pool, 'submit', original)
        assert completed(c, start(c, key='retry').json()['debate_id'])['status'] == 'completed'


def test_sse_cursor_outside_sqlite_range_is_bad_request(setup):
    with TestClient(app_for(setup)) as c:
        d = start(c).json()['debate_id']
        completed(c, d)
        for cursor in ('-1', str(2**63), '9' * 100):
            assert c.get(f'/debates/{d}/events', headers={**AUTH, 'Last-Event-ID': cursor}).status_code == 400


def test_detail_terminal_event_cannot_return_stale_running_status(setup, monkeypatch):
    app = app_for(setup)
    with TestClient(app) as c:
        d = start(c).json()['debate_id']
        completed(c, d)
        original = app.state.service.store.get
        monkeypatch.setattr(app.state.service.store, 'get', lambda key: {**original(key), 'status': 'running'})
        assert c.get(f'/debates/{d}', headers=AUTH).json()['status'] == 'completed'


@pytest.mark.parametrize('audit_kind', ['running', 'missing', 'corrupt'])
def test_restart_preserves_unknown_usage_and_original_audit(setup, audit_kind):
    settings, _ = setup
    store = Store(settings.data_dir / 'http')
    row, _ = store.create('interrupted', 'fingerprint', '005930', '2026-10-16', 1)
    d = row['id']
    store.emit(d, 'turn_started', {'side': 'bull', 'round': 'opening'})
    store.close()
    manifest = settings.data_dir / 'audits' / d / 'manifest.json'
    known = {'calls': [{'model': 'claude-haiku-5-5', 'input_tokens': 123, 'output_tokens': 7}]}
    raw = None
    if audit_kind != 'missing':
        manifest.parent.mkdir(parents=True)
        raw = json.dumps({'run_id': d, 'status': 'running', 'usage': known,
                          'llm_calls': [{'call_id': 2, 'status': 'running'}]}) if audit_kind == 'running' else '{broken'
        manifest.write_text(raw, encoding='utf-8')
    with TestClient(app_for(setup)) as c:
        detail = c.get(f'/debates/{d}', headers=AUTH).json()
        assert detail['status'] == 'failed' and 'usage' not in detail
        events = parse_sse(c.get(f'/debates/{d}/events', headers={**AUTH, 'Last-Event-ID': '1'}).text)
        assert len(events) == 1 and events[0][1] == 'debate_failed'
        recovery = json.loads(c.app.state.service.store.db.execute(
            'SELECT data FROM recoveries WHERE debate_id=?', (d,)).fetchone()[0])
        assert recovery['usage_complete'] is False
        if audit_kind == 'running':
            assert recovery['known_usage'] == known
            assert recovery['unfinished_call_ids'] == [2]
    if raw is not None:
        assert manifest.read_text(encoding='utf-8') == raw
    with TestClient(app_for(setup)) as c:
        assert len(parse_sse(c.get(f'/debates/{d}/events', headers=AUTH).text)) == 2


@pytest.mark.parametrize('failure', ['usage_reader', 'unfinished_call', 'failed_call_without_usage', 'failed_call_with_partial_usage'])
def test_partial_usage_stays_in_audit_but_is_not_settled_as_final(setup, failure):
    from bullbear.server.service import LiveRunner
    known = {'calls': [{'model': 'claude-haiku-5-5', 'input_tokens': 123, 'output_tokens': 7}]}
    class InterruptedRunner(LiveRunner):
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            self.audit.data['usage'] = known
            if failure != 'usage_reader':
                self.audit.data['llm_calls'].append({
                    'call_id': 2, 'status': 'running' if failure == 'unfinished_call' else 'failure',
                    'usage': known if failure == 'failed_call_with_partial_usage' else {'calls': []}})
            raise RuntimeError('private provider detail')
        def usage(self):
            if failure == 'usage_reader':
                raise RuntimeError('private usage detail')
            return known
    with TestClient(app_for(setup, runner_factory=lambda: InterruptedRunner(setup[0]))) as c:
        d = start(c).json()['debate_id']
        result = completed(c, d)
        assert result['status'] == 'failed' and 'usage' not in result
        events = parse_sse(c.get(f'/debates/{d}/events', headers=AUTH).text)
        assert events[-1][1] == 'debate_failed' and 'usage' not in events[-1][2]
        manifest = json.loads((setup[0].data_dir / 'audits' / d / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['usage'] == known and manifest['usage_complete'] is False
        assert 'private provider' not in json.dumps(manifest)


def test_abrupt_process_exit_releases_owner_and_replays_one_terminal_event(tmp_path):
    script = '''
import os, sys
from pathlib import Path
from bullbear.server.store import Store
store = Store(Path(sys.argv[1]))
row, _ = store.create('crash', 'same-body', '005930', '2026-10-16', 1)
store.emit(row['id'], 'turn_started', {'side': 'bull', 'round': 'opening'})
os._exit(23)
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'http')],
                            capture_output=True, timeout=20)
    assert result.returncode == 23, result.stderr.decode(errors='replace')
    for _ in range(2):
        store = Store(tmp_path / 'http')
        try:
            row = store.request('crash', 'same-body')
            assert row['status'] == 'failed'
            assert [event['type'] for event in store.events(row['id'])] == ['turn_started', 'debate_failed']
            assert 'usage' not in json.loads(store.events(row['id'])[-1]['data'])
        finally:
            store.close()

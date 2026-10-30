import json
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

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from bullbear.anthropic_budget import WorkerSpendLedger, BudgetDenied
from bullbear.server.app import create_app
from bullbear.server.store import Store
from .test_server import setup, start, completed
from .test_anthropic_budget import fake_client, request


def test_http_budget_denial_precedes_provider_and_reports_zero_known_usage(setup, monkeypatch):
    def unexpected_image(_):
        pytest.fail("text-only worker budget must not render a chart image")

    monkeypatch.setattr('bullbear.graph_runtime.daily_chart_image', unexpected_image)
    settings, market = setup
    settings = replace(settings, worker_budget_usd='0.01', worker_budget_id='test-budget')
    calls, clients = [], []
    def create_client(**kwargs):
        clients.append(kwargs)
        return fake_client(calls)
    monkeypatch.setattr('bullbear.llm.anthropic.Anthropic', create_client)
    with TestClient(create_app(settings=settings, market=market, token='test-token')) as client:
        ident = start(client).json()['debate_id']
        result = completed(client, ident)
        assert result['status'] == 'failed' and result['error']['code'] == 'LLM_ERROR'
        assert result['usage'] == {'calls': [], 'cost_usd': 0}
        assert client.app.state.service.budget.summary()['requests'] == 0
    assert not calls and all(c['max_retries'] == 0 for c in clients)
    audit = json.loads((settings.data_dir/'audits'/ident/'manifest.json').read_bytes())
    assert audit['usage_complete'] and audit['llm_calls'][0]['dispatch_blocked']


def test_service_restart_halts_existing_interrupted_budget(setup):
    settings, market = setup
    settings = replace(settings, worker_budget_usd='3', worker_budget_id='test-budget')
    with TestClient(create_app(settings=settings, market=market, token='test-token')) as client:
        client.app.state.service.budget.reserve(request(), scope='unfinished')
    with TestClient(create_app(settings=settings, market=market, token='test-token')) as client:
        budget = client.app.state.service.budget
        assert budget.summary()['halted'] and budget.summary()['reserved_unconfirmed_usd'] == 2.16
        with pytest.raises(BudgetDenied):
            budget.reserve(request(), scope='new-run')


def test_invalid_budget_does_not_leak_worker_owner_lock(setup):
    settings, market = setup
    settings = replace(settings, worker_budget_usd='3', worker_budget_id=None)
    with pytest.raises(BudgetDenied):
        with TestClient(create_app(settings=settings, market=market, token='test-token')):
            pass
    store = Store(settings.data_dir/'http', maintenance=True)
    store.close()


def test_removing_budget_environment_cannot_reopen_unlimited_worker(setup):
    settings, market = setup
    configured = replace(settings, worker_budget_usd='3', worker_budget_id='test-budget')
    with TestClient(create_app(settings=configured, market=market, token='test-token')):
        pass
    with pytest.raises(BudgetDenied, match='original configuration'):
        with TestClient(create_app(settings=settings, market=market, token='test-token')):
            pass

"""Offline guard checks for the explicitly paid HTTP pilot; no client is created."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def pilot():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'worker-http-live-pilot.py'
    spec = importlib.util.spec_from_file_location('http_live_pilot', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(model='claude-sonnet-5-5', **extra):
    return {'model': model, 'max_tokens': 16000, **extra}


def test_unconfirmed_reservation_cannot_be_reused_as_zero_cost(pilot, tmp_path):
    ledger = pilot.Ledger(tmp_path)
    ledger.reserve(request())
    with pytest.raises(RuntimeError, match='budget'):
        ledger.reserve(request())
    assert len(ledger.data['requests']) == 1
    assert ledger.data['requests'][0]['status'] == 'reserved'


@pytest.mark.parametrize('payload', [request(model='unknown'), request(max_tokens=16001),
                                    request(cache_control={'type': 'ephemeral'})])
def test_unpriced_requests_never_reserve(pilot, tmp_path, payload):
    ledger = pilot.Ledger(tmp_path)
    with pytest.raises(RuntimeError):
        ledger.reserve(payload)
    assert ledger.data['requests'] == []


def test_halted_or_maximum_requests_prevent_further_dispatch(pilot, tmp_path):
    ledger = pilot.Ledger(tmp_path)
    ledger.data['halted'] = True
    with pytest.raises(RuntimeError, match='limit'):
        ledger.reserve(request())
    ledger.data['halted'] = False
    ledger.data['requests'] = [{'actual_nano': 0, 'reserved_nano': 1}] * 48
    with pytest.raises(RuntimeError, match='limit'):
        ledger.reserve(request())


def test_call_without_paid_flag_does_not_load_environment_or_create_server(pilot, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('paid path entered without explicit flag')
    monkeypatch.setattr(pilot, 'load_dotenv', forbidden)
    with pytest.raises(ValueError, match='allow-paid'):
        pilot.run(SimpleNamespace(allow_paid=False))


@pytest.mark.parametrize('limit,ident', [('3', 'production'), ('3', None), (None, 'production')])
def test_worker_budget_settings_rejected_before_pilot_artifacts_or_server(pilot, monkeypatch, tmp_path, limit, ident):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pilot, 'load_dotenv', lambda *a, **k: None)
    monkeypatch.setattr(pilot, 'load_settings', lambda: SimpleNamespace(
        worker_budget_usd=limit, worker_budget_id=ident))
    def forbidden(*args, **kwargs):
        pytest.fail('mixed budget configuration reached server or provider')
    monkeypatch.setattr(pilot, 'create_app', forbidden)
    monkeypatch.setattr(pilot.anthropic, 'Anthropic', forbidden)
    with pytest.raises(ValueError, match='own --prior-run budget chain'):
        pilot.run(SimpleNamespace(allow_paid=True, prior_run=None))
    assert not (tmp_path / 'data').exists()


def finished(pilot, directory, input_tokens, *, prior_run=None):
    directory.mkdir()
    ledger = pilot.Ledger(directory, prior_run=prior_run)
    record = ledger.reserve(request())
    usage = {'input_tokens': input_tokens, 'output_tokens': 0}
    message = SimpleNamespace(model='claude-sonnet-5-5', stop_reason='end_turn',
        usage=SimpleNamespace(model_dump=lambda **_: usage),
        model_dump=lambda **_: {'model': 'claude-sonnet-5-5', 'usage': usage})
    ledger.settle(record, message, 1.0)
    pilot.write(directory / 'report.json', {'server_stopped': True, 'unknown_requests': 0,
                                           'known_cost_usd': record['actual_nano'] / 1e9})
    return ledger


def test_prior_spending_blocks_a_request_that_would_exceed_total_authorization(pilot, tmp_path):
    prior = tmp_path / 'prior'
    finished(pilot, prior, 450000)  # $0.90 incurred, only $2.10 remains.
    before = {p.name: p.read_bytes() for p in prior.iterdir()}
    current = tmp_path / 'current'
    current.mkdir()
    ledger = pilot.Ledger(current, prior_run=prior)
    assert ledger.data['prior_spent_nano'] == 900000000
    with pytest.raises(RuntimeError, match='budget'):
        ledger.reserve(request())  # Sonnet full-window reservation is $2.16.
    assert not ledger.data['requests']
    assert before == {p.name: p.read_bytes() for p in prior.iterdir()}


def test_chained_spending_is_counted_once_and_original_sources_cannot_change(pilot, tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    finished(pilot, first, 100000)
    finished(pilot, second, 100000, prior_run=first)
    assert pilot.prior_spend(second)[0] == 400000000
    data = json.loads((first / 'requests.json').read_text())
    data['pricing_checked_on'] = 'changed'
    pilot.write(first / 'requests.json', data)
    with pytest.raises(ValueError, match='chain changed'):
        pilot.prior_spend(second)


@pytest.mark.parametrize('change', ['running', 'unknown', 'altered_cost', 'altered_report', 'halted'])
def test_untrusted_prior_accounting_is_rejected_before_credentials(pilot, tmp_path, monkeypatch, change):
    prior = tmp_path / 'prior'
    ledger = finished(pilot, prior, 100000)
    report = json.loads((prior / 'report.json').read_text())
    if change == 'running': report['server_stopped'] = False
    if change == 'unknown': ledger.data['requests'][0]['status'] = 'unknown'
    if change == 'altered_cost': ledger.data['requests'][0]['actual_nano'] = 1
    if change == 'altered_report': report['known_cost_usd'] = 0
    if change == 'halted': ledger.data['halted'] = True
    ledger.save()
    pilot.write(prior / 'report.json', report)
    def forbidden(*args, **kwargs):
        pytest.fail('credentials loaded before accounting was verified')
    monkeypatch.setattr(pilot, 'load_dotenv', forbidden)
    with pytest.raises(ValueError):
        pilot.run(SimpleNamespace(allow_paid=True, prior_run=prior))


def test_legacy_completed_pilot_and_no_overwrite(pilot, tmp_path):
    prior = tmp_path / 'prior'
    ledger = finished(pilot, prior, 100000)
    for key in ('prior_run', 'prior_spent_nano', 'prior_ledger_sha256'):
        ledger.data.pop(key)
    ledger.save()
    assert pilot.prior_spend(prior)[0] == 200000000
    with pytest.raises(FileExistsError):
        pilot.Ledger(prior)


@pytest.mark.parametrize('model,inputs,cached,expected', [
    ('claude-haiku-5-5', 100000, 0, 10000000),
    ('claude-haiku-5-5', 100001, 0, 50000500),
    ('claude-haiku-5-5', 100000, 1, 50000050),
    ('claude-sonnet-5-5', 10, 20, 22000),
])
def test_carried_cost_uses_actual_model_tier_and_cache_usage(pilot, model, inputs, cached, expected):
    assert pilot.usage_cost(model, {'input_tokens': inputs, 'output_tokens': 0,
                                   'cache_read_input_tokens': cached}) == expected

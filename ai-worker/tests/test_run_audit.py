import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from bullbear import audit as audit_module
from bullbear import schemas, semantic
from bullbear.audit import AuditedLLM, RunAudit, canonical_hash
from bullbear.config import load_settings
from bullbear.data import DataUnavailable
from bullbear.llm import Conversation, LLMError
from bullbear.server import service as service_module
from bullbear.server.app import create_app
from bullbear.server.service import Service
from .fakes import NOW, ScriptedDebater, ScriptedModerator, statement
from .http_fixture import TestRunner, fixture_market
from .test_server import AUTH, completed, parse_sse, start


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, 'code_revision', lambda: {'revision': 'a' * 40, 'dirty': False})
    settings = replace(load_settings(), data_dir=tmp_path)
    market = fixture_market(settings)
    yield settings, market
    if close := getattr(market, 'close', None):
        close()


def read_manifest(settings, run_id):
    return json.loads((settings.data_dir / 'audits' / run_id / 'manifest.json').read_text(encoding='utf-8'))


def run_once(setup, factory, run_id='run-1'):
    settings, market = setup
    svc = Service(settings, market, runner_factory=factory)
    try:
        row, _ = svc.store.create(run_id, run_id, '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 1)
        return svc.detail(row['id']), read_manifest(settings, row['id'])
    finally:
        svc.close()


def test_success_records_exact_snapshot_provenance_and_keeps_http_contract(setup):
    settings, market = setup
    app = create_app(settings=settings, market=market, token='test-token',
                     runner_factory=lambda: TestRunner(settings))
    with TestClient(app) as client:
        accepted = start(client).json()
        assert set(accepted) == {'debate_id', 'snapshot_id', 'status', 'reused'}
        result = completed(client, accepted['debate_id'])
        events = parse_sse(client.get(f"/debates/{accepted['debate_id']}/events", headers=AUTH).text)
        snap = client.get('/snapshots/' + result['snapshot_id'], headers=AUTH).json()
        manifest = read_manifest(settings, accepted['debate_id'])
        assert manifest['status'] == 'success'
        assert manifest['snapshot'] == snap
        assert manifest['snapshot_id'] == snap['snapshot_id']
        assert manifest['decision_at'] == snap['created_at']
        assert manifest['snapshot_payload_hash'] == canonical_hash(snap)
        assert manifest['provenance']['code'] == {'revision': 'a' * 40, 'dirty': False}
        assert set(manifest['provenance']['schema_hashes']) == {'statement', 'moderator', 'semantic_review'}
        assert set(manifest['provenance']['prompt_source_hashes']) == {'prompts', 'semantic'}
        assert manifest['usage'] == result['usage']
        assert manifest['runner']['llm_call_observation'] is False
        assert {s['name'] for s in manifest['stages']} == {'snapshot', 'runner_initialization', 'debate'}
        assert all(s['status'] == 'success' and s['elapsed_seconds'] >= 0 for s in manifest['stages'])
        assert manifest['elapsed_seconds'] >= sum(s['elapsed_seconds'] for s in manifest['stages'])
        assert events[0][1] == 'snapshot_created' and events[-1][1] == 'debate_completed'
        assert 'audit' not in str(events) and 'PRIVATE' not in str(manifest)
        assert len(manifest['events']) > 6
        assert len(list((settings.data_dir / 'audits').iterdir())) == 1
        assert start(client).json()['debate_id'] == accepted['debate_id']
        assert len(list((settings.data_dir / 'audits').iterdir())) == 1


def test_snapshot_failure_is_recorded_before_runner_creation(setup):
    settings, market = setup
    called = []
    def snapshot_failure(quote):
        manifest_path = next((settings.data_dir / 'audits').glob('*/manifest.json'))
        assert json.loads(manifest_path.read_text(encoding='utf-8'))['status'] == 'running'
        raise DataUnavailable('API-key=must-not-leak')
    market.snapshot = snapshot_failure
    result, manifest = run_once(setup, lambda: called.append(True))
    assert result['status'] == 'failed' and result['error']['code'] == 'DATA_UNAVAILABLE'
    assert not called and manifest['snapshot'] is None
    assert manifest['status'] == 'failure' and manifest['error_type'] == 'DataUnavailable'
    assert manifest['stages'][0]['status'] == 'failed'
    assert 'must-not-leak' not in json.dumps(manifest)


def test_runner_factory_failure_keeps_snapshot_and_safe_error(setup):
    def broken_factory():
        raise RuntimeError('secret constructor message')
    result, manifest = run_once(setup, broken_factory)
    assert result['status'] == 'failed'
    assert manifest['snapshot_id'] == result['snapshot_id']
    assert manifest['snapshot']['facts']['PX.CLOSE']['value'] > 0
    assert manifest['stages'][-1]['name'] == 'runner_initialization'
    assert manifest['stages'][-1]['status'] == 'failed'
    assert manifest['error_type'] == 'RuntimeError'
    assert 'secret constructor' not in json.dumps(manifest)


def test_partial_client_construction_failure_closes_first_client_and_preserves_plan(setup, monkeypatch):
    settings, _ = setup
    monkeypatch.setenv('BULLBEAR_DEBATER_MODEL', 'selected-debater')
    monkeypatch.setenv('BULLBEAR_MODERATOR_MODEL', 'selected-moderator')
    closed = []
    def llm(model):
        path = next((settings.data_dir / 'audits').glob('*/manifest.json'))
        before = json.loads(path.read_text(encoding='utf-8'))
        assert before['snapshot_id'] and before['decision_at']
        assert before['config']['selected_models']['moderator'] == 'selected-moderator'
        if model == 'selected-moderator':
            raise RuntimeError('ANTHROPIC_API_KEY=private-constructor')
        return NS(client=NS(close=lambda: closed.append(model)), usage_payload=lambda: {'calls': []})
    monkeypatch.setattr(service_module, 'LLM', llm)
    result, manifest = run_once(setup, lambda: service_module.LiveRunner(settings))
    assert result['status'] == 'failed' and result['error']['code'] == 'LLM_ERROR'
    assert closed == ['selected-debater']
    assert manifest['status'] == 'failure' and manifest['usage'] == {'calls': []}
    assert next(s for s in manifest['stages'] if s['name'] == 'moderator_client_initialization')['status'] == 'failed'
    assert 'private-constructor' not in json.dumps(manifest)


def test_live_runner_wires_audited_clients_and_reviews_without_changing_public_usage(setup, monkeypatch):
    settings, _ = setup
    closed = []
    class Provider:
        def __init__(self, model):
            self.model, self.count = model, 0
            self.client = NS(close=lambda: closed.append(model))
        def usage_payload(self):
            return {'calls': [{'model': 'actual-server-fallback', 'input_tokens': self.count * 10,
                               'output_tokens': self.count * 5}]}
        def structured(self, conv, **kwargs):
            path = next((settings.data_dir / 'audits').glob('*/manifest.json'))
            manifest = json.loads(path.read_text(encoding='utf-8'))
            assert manifest['snapshot_id'] and manifest['llm_calls'][-1]['status'] == 'running'
            self.count += 1
            return {}
    class Debater(ScriptedDebater):
        def __init__(self, llm, snapshot, **kwargs):
            self.llm = llm
            super().__init__(statement(('E1', 'PX.CLOSE', snapshot.facts['PX.CLOSE'].value)))
        def speak(self, *args, **kwargs):
            self.llm.structured(Conversation('debater prompt'), schema=schemas.STATEMENT_SCHEMA, effort='medium')
            self.llm.structured(Conversation('review prompt'), schema=semantic.Review.model_json_schema(), effort='medium')
            return super().speak(*args, **kwargs)
    class Moderator(ScriptedModerator):
        def __init__(self, llm, snapshot, **kwargs):
            self.llm = llm
            super().__init__(['verdict'])
        def evaluate(self, *args, **kwargs):
            self.llm.structured(Conversation('moderator prompt'), schema=schemas.MODERATOR_SCHEMA, effort='high')
            self.llm.structured(Conversation('review prompt'), schema=semantic.Review.model_json_schema(), effort='medium')
            return super().evaluate(*args, **kwargs)
    monkeypatch.setattr(service_module, 'LLM', Provider)
    monkeypatch.setattr(service_module, 'Debater', Debater)
    monkeypatch.setattr(service_module, 'Moderator', Moderator)
    result, manifest = run_once(setup, lambda: service_module.LiveRunner(settings))
    assert result['status'] == 'completed' and manifest['status'] == 'success'
    assert len(closed) == 2 and len(manifest['llm_calls']) == 14
    assert manifest['runner']['llm_call_observation'] is True
    assert {role: sum(c['role'] == role for c in manifest['llm_calls'])
            for role in ('debater', 'moderator', 'semantic_reviewer')} == {
                'debater': 6, 'moderator': 1, 'semantic_reviewer': 7}
    assert manifest['usage'] == result['usage']
    assert manifest['usage']['calls'][0]['input_tokens'] == 140
    assert manifest['role_usage']['semantic_reviewer']['calls'][0]['input_tokens'] == 70
    assert all(c['actual_models'] == ['actual-server-fallback'] for c in manifest['llm_calls'])


def test_verification_failure_preserves_rejection_metadata_usage_and_no_public_statement(setup):
    settings, _ = setup
    result, manifest = run_once(setup, lambda: TestRunner(settings, invalid=True))
    assert result['status'] == 'failed' and result['statements'] == []
    assert manifest['status'] == 'failure' and manifest['error_type'] == 'LLMError'
    assert manifest['usage']['calls'][0]['input_tokens'] == 100
    assert any(e['type'] == 'statement_rejected' for e in manifest['events'])
    assert not any(e['type'] == 'statement_accepted' for e in manifest['events'])


@pytest.mark.parametrize('invalid', [False, True])
def test_usage_collection_failure_does_not_prevent_terminal_result(setup, invalid):
    settings, _ = setup
    class MissingUsage(TestRunner):
        def usage(self):
            raise RuntimeError('private usage provider detail')
    result, manifest = run_once(setup, lambda: MissingUsage(settings, invalid=invalid))
    assert result['status'] == ('failed' if invalid else 'completed')
    assert manifest['status'] == ('failure' if invalid else 'success')
    assert result['usage'] == {'calls': []}
    assert manifest['usage_complete'] is False
    assert manifest['usage_errors'] == [{'error_type': 'RuntimeError'}]
    assert manifest.get('error_type') == ('LLMError' if invalid else None)
    assert 'private usage' not in json.dumps(manifest)


def test_cleanup_error_persistence_failure_keeps_successful_result(setup, monkeypatch):
    settings, _ = setup
    class BrokenClose(TestRunner):
        def close(self):
            raise RuntimeError('private close detail')
    def unavailable(*args):
        raise OSError('private disk detail')
    monkeypatch.setattr(RunAudit, 'cleanup_error', unavailable)
    result, manifest = run_once(setup, lambda: BrokenClose(settings))
    assert result['status'] == 'completed' and manifest['status'] == 'success'


def test_two_runs_have_isolated_durable_running_manifests(setup):
    settings, market = setup
    barrier = threading.Barrier(2)
    class ConcurrentRunner(TestRunner):
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            manifest = read_manifest(settings, debate_id)
            assert manifest['snapshot_id'] == snapshot.snapshot_id
            assert manifest['status'] == 'running'
            barrier.wait(timeout=5)
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    svc = Service(settings, market, runner_factory=lambda: ConcurrentRunner(settings))
    try:
        rows = [svc.store.create(f'req-{i}', str(i), ticker, NOW.date().isoformat(), 2)[0]
                for i, ticker in enumerate(('005930', '000660'))]
        quotes = [market.quote(row['ticker']) for row in rows]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(svc.run, row['id'], quote, 1) for row, quote in zip(rows, quotes)]
            for future in futures:
                future.result(timeout=10)
        manifests = [read_manifest(settings, row['id']) for row in rows]
        assert {m['ticker'] for m in manifests} == {'005930', '000660'}
        assert all(m['status'] == 'success' and m['run_id'] == r['id'] for m, r in zip(manifests, rows))
        assert len(list((settings.data_dir / 'audits').glob('*/manifest.json'))) == 2
        assert not list((settings.data_dir / 'audits').glob('*/.manifest-*.tmp'))
    finally:
        svc.close()


def make_audit(settings, run_id='unit-run'):
    return RunAudit(settings.data_dir, run_id, ticker='005930', data_date='2026-10-16',
                    max_extra_rounds=1, models={'debater': 'chosen'}, efforts={'debater': 'medium'})


@pytest.mark.parametrize('fail', [False, True])
def test_call_is_saved_before_provider_and_actual_models_roles_usage_survive_failure(setup, fail):
    settings, market = setup
    audit = make_audit(settings)
    audit.attach_snapshot(market.snapshot(market.quote('005930')))
    class Provider:
        model = 'chosen'
        count = 0
        def usage_payload(self):
            return {'calls': [{'model': 'actual-fallback', 'input_tokens': self.count * 11,
                               'output_tokens': self.count * 3, 'cache_read_input_tokens': self.count * 2}]}
        def structured(self, conv, **kwargs):
            before = read_manifest(settings, 'unit-run')
            assert before['snapshot'] and before['llm_calls'][-1]['status'] == 'running'
            self.count += 1
            if fail:
                raise LLMError('raw exception including token-private')
            return {'issues': []}
    wrapped = AuditedLLM(Provider(), audit, 'debater')
    schema = semantic.Review.model_json_schema()
    kwargs = dict(schema=schema, effort='medium')
    if fail:
        with pytest.raises(LLMError):
            wrapped.structured(Conversation('private prompt'), **kwargs)
    else:
        wrapped.structured(Conversation('private prompt'), **kwargs)
        wrapped.structured(Conversation('other prompt'), **kwargs)
    manifest = read_manifest(settings, 'unit-run')
    for call in manifest['llm_calls']:
        assert call['role'] == 'semantic_reviewer' and call['client_role'] == 'debater'
        assert call['selected_model'] == 'chosen' and call['actual_models'] == ['actual-fallback']
        assert call['usage']['calls'][0]['input_tokens'] == 11
        assert call['schema_hash'] == canonical_hash(schema)
        assert call['status'] == ('failure' if fail else 'success')
    assert 'private prompt' not in json.dumps(manifest) and 'token-private' not in json.dumps(manifest)


def test_redaction_covers_snapshot_result_usage_and_ignores_unselected_environment(setup, monkeypatch):
    settings, market = setup
    monkeypatch.setenv('OPENAI_API_KEY', 'known-private-key')
    monkeypatch.setenv('UNRELATED_PRIVATE_SETTING', 'unselected-private-value')
    audit = make_audit(settings)
    snapshot = market.snapshot(market.quote('005930'))
    snapshot.facts['PX.CLOSE'].note = 'known-private-key api_key=url-secret&other=ok sk-ant-123456789-secret'
    audit.attach_snapshot(snapshot)
    audit.observe_event('token', {'text': 'raw-token-must-not-appear'})
    audit.finish('failure', error=RuntimeError('unknown-exception-private'),
                 usage={'calls': [{'model': 'known-private-key', 'input_tokens': 10, 'api_key': 'vendor-secret'}]},
                 result={'summary': 'known-private-key'})
    manifest = read_manifest(settings, 'unit-run')
    text = json.dumps(manifest)
    for secret in ('known-private-key', 'url-secret', 'sk-ant-123456789-secret',
                   'vendor-secret', 'unknown-exception-private', 'unselected-private-value',
                   'raw-token-must-not-appear'):
        assert secret not in text
    assert manifest['redactions_applied'] is True
    assert manifest['snapshot_id'] == snapshot.snapshot_id
    assert manifest['snapshot']['facts']['PX.CLOSE']['value'] == snapshot.facts['PX.CLOSE'].value


def test_snapshot_warning_never_copies_optional_provider_exception_text(setup):
    settings, market = setup
    def unavailable(*args):
        raise DataUnavailable('unstructured-vendor-private-detail')
    market.source.get_financial_reports = unavailable
    snapshot = market.snapshot(market.quote('005930'))
    assert 'unstructured-vendor-private-detail' in str(snapshot.warnings)
    audit = make_audit(settings)
    audit.attach_snapshot(snapshot)
    manifest = read_manifest(settings, 'unit-run')
    assert 'unstructured-vendor-private-detail' not in json.dumps(manifest)
    assert manifest['snapshot_warning_details_omitted'] is True
    assert manifest['redactions_applied'] is True
    assert manifest['snapshot_payload_hash'] == canonical_hash(snapshot.model_dump(mode='json'))


def test_no_paid_runner_when_initial_audit_cannot_be_flushed(setup, monkeypatch):
    called = []
    monkeypatch.setattr(audit_module.os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('disk-private')))
    settings, market = setup
    svc = Service(settings, market, runner_factory=lambda: called.append(True))
    try:
        row, _ = svc.store.create('failed-write', 'x', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 1)
        assert svc.detail(row['id'])['status'] == 'failed'
        assert not called and not list((settings.data_dir / 'audits').glob('*/.manifest-*.tmp'))
    finally:
        svc.close()

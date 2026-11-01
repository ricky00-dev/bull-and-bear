"""Private HTTP context wiring; deterministic providers, no paid requests."""
import json
import sys
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from bullbear import audit as audit_module
from bullbear.audit import RunAudit, canonical_hash
from bullbear.config import load_settings
from bullbear.rag.context import KnowledgeContext
from bullbear.server.app import create_app
from bullbear.server.service import Service
from .fakes import NOW
from .http_fixture import TestRunner, fixture_market
from .test_server import AUTH, completed, parse_sse, start


def context_for(snapshot, *, status='completed', marker='PRIVATE_KNOWLEDGE', warnings=()):
    return KnowledgeContext.from_payload({
        'schema_version': 'knowledge-context-v1',
        'snapshot_id': snapshot.snapshot_id, 'decision_at': snapshot.created_at.isoformat(),
        'status': status, 'profile_version': 'knowledge-short-v1',
        'warnings': list(warnings),
        'items': [{'kind': 'knowledge', 'text': marker, 'horizons': ['common'],
                   'applicability': 'Definitions only', 'limitations': [], 'study_scope': None}]
                  if status == 'completed' else [],
    })


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, 'code_revision', lambda: {'revision': 'a' * 40, 'dirty': False})
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True,
                       rag_generation_id='generation-fixed', rag_profile='knowledge-short-v1')
    market = fixture_market(settings)
    yield settings, market
    if close := getattr(market, 'close', None):
        close()


def manifest(settings, debate_id):
    return json.loads((settings.data_dir / 'audits' / debate_id / 'manifest.json').read_text(encoding='utf-8'))


def install_retriever(monkeypatch, retrieve):
    class Retriever:
        def __init__(self, store):
            self.store = store
        def retrieve(self, snapshot, *, generation_id, generation_binding=None):
            return retrieve(snapshot, generation_id)
    monkeypatch.setitem(sys.modules, 'bullbear.rag.retrieval', NS(Retriever=Retriever))


def test_http_freezes_once_reuses_date_and_keeps_context_private(setup, monkeypatch):
    settings, market = setup
    calls, observed = [], []
    def retrieve(snapshot, generation_id):
        calls.append((snapshot, generation_id))
        return context_for(snapshot)
    install_retriever(monkeypatch, retrieve)
    class ContextRunner(TestRunner):
        background_context = None
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            observed.append(self.background_context)
            assert self.background_context.snapshot_id == snapshot.snapshot_id
            assert manifest(settings, debate_id)['knowledge_context']['context_id'] == self.background_context.context_id
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    app = create_app(settings=settings, market=market, token='test-token',
                     runner_factory=lambda: ContextRunner(settings))
    with TestClient(app) as client:
        first = start(client).json()
        result = completed(client, first['debate_id'])
        assert result['status'] == 'completed'
        repeated = start(client, key='different-request-same-close').json()
        assert repeated['reused'] and repeated['debate_id'] == first['debate_id']
        events = parse_sse(client.get(f"/debates/{first['debate_id']}/events", headers=AUTH).text)
        assert 'PRIVATE_KNOWLEDGE' not in json.dumps([result, events])
        assert 'context_id' not in json.dumps([result, events])
        private = manifest(settings, first['debate_id'])
        assert private['knowledge_context']['payload']['items'][0]['text'] == 'PRIVATE_KNOWLEDGE'
        assert private['knowledge_context']['retrieval_config']['generation_id'] == 'generation-fixed'
        assert private['run_fingerprint'].startswith('sha256:')
        assert next(s for s in private['stages'] if s['name'] == 'knowledge_context')['status'] == 'success'
        assert len(calls) == len(observed) == 1
        assert calls[0][0].created_at == NOW


@pytest.mark.parametrize('generation,profile', [(None, 'knowledge-short-v1'), ('g', 'unknown-profile')])
def test_enabled_invalid_config_fails_before_runner(setup, generation, profile):
    settings, market = setup
    settings = replace(settings, rag_generation_id=generation, rag_profile=profile)
    called = []
    svc = Service(settings, market, runner_factory=lambda: called.append(True))
    try:
        row, _ = svc.store.create('config-failure', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 1)
        assert svc.detail(row['id'])['status'] == 'failed'
        assert not called
        private = manifest(settings, row['id'])
        assert private['status'] == 'failure' and private['error_type'] == 'ValueError'
        assert 'knowledge_context' not in private
    finally:
        svc.close()


def test_retrieval_exception_is_a_failed_run_and_never_empty_success(setup, monkeypatch):
    settings, market = setup
    called = []
    def broken(snapshot, generation_id):
        raise RuntimeError('API_KEY=private-retrieval-error')
    install_retriever(monkeypatch, broken)
    svc = Service(settings, market, runner_factory=lambda: called.append(True))
    try:
        row, _ = svc.store.create('retrieval-failure', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 1)
        public, private = svc.detail(row['id']), manifest(settings, row['id'])
        assert public['status'] == 'failed' and private['status'] == 'failure'
        assert not called and 'knowledge_context' not in private
        assert 'private-retrieval-error' not in json.dumps([public, private])
    finally:
        svc.close()


@pytest.mark.parametrize('status', ['empty', 'timeout', 'failed'])
def test_retrieval_status_distinguishes_confirmed_empty_from_failure(setup, monkeypatch, status):
    settings, market = setup
    install_retriever(monkeypatch, lambda snapshot, generation: context_for(snapshot, status=status))
    calls = []
    def runner():
        calls.append(True)
        return TestRunner(settings)
    svc = Service(settings, market, runner_factory=runner)
    try:
        row, _ = svc.store.create('retrieval-status', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 1)
        assert svc.detail(row['id'])['status'] == ('completed' if status == 'empty' else 'failed')
        assert bool(calls) == (status == 'empty')
        assert manifest(settings, row['id'])['knowledge_context']['payload']['status'] == status
    finally:
        svc.close()


def new_audit(settings, run_id, snapshot, *, model='fixed-model'):
    audit = RunAudit(settings.data_dir, run_id, ticker=snapshot.ticker, data_date=str(snapshot.as_of),
                     max_extra_rounds=0, models={'debater': model, 'moderator': model},
                     efforts={'debater': 'medium', 'moderator': 'high'})
    audit.attach_snapshot(snapshot)
    return audit


def test_audit_context_is_immutable_and_fingerprint_tracks_model_and_context(setup):
    settings, market = setup
    snapshot = market.snapshot(market.quote('005930'))
    first = new_audit(settings, 'first', snapshot)
    context = context_for(snapshot)
    first.attach_context(context)
    first.attach_context(context)
    with pytest.raises(ValueError, match='already frozen'):
        first.attach_context(context_for(snapshot, marker='changed'))
    with pytest.raises(ValueError, match='already frozen'):
        first.attach_context(None)
    second = new_audit(settings, 'second', snapshot)
    second.attach_context(context)
    assert first.data['run_fingerprint'] == second.data['run_fingerprint']
    third = new_audit(settings, 'third', snapshot, model='different-model')
    third.attach_context(context)
    assert third.data['run_fingerprint'] != first.data['run_fingerprint']
    fourth = new_audit(settings, 'fourth', snapshot)
    fourth.attach_context(None)
    assert fourth.data['run_fingerprint'] != first.data['run_fingerprint']
    assert fourth.data['knowledge_context']['payload'] is None


def test_audit_rejects_mismatched_snapshot_or_decision_time(setup):
    settings, market = setup
    snapshot = market.snapshot(market.quote('005930'))
    audit = new_audit(settings, 'mismatch', snapshot)
    with pytest.raises(ValueError, match='snapshot mismatch'):
        audit.attach_context(NS(snapshot_id='other', payload_json=context_for(snapshot).payload_json))
    payload = json.loads(context_for(snapshot).payload_json)
    payload['decision_at'] = (snapshot.created_at + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='decision time mismatch'):
        audit.attach_context(NS(snapshot_id=snapshot.snapshot_id, payload_json=json.dumps(payload)))


def test_settings_read_explicit_rag_flags(monkeypatch):
    monkeypatch.setenv('BULLBEAR_RAG_ENABLED', 'true')
    monkeypatch.setenv('BULLBEAR_RAG_GENERATION_ID', 'generation-1')
    monkeypatch.setenv('BULLBEAR_RAG_PROFILE', 'knowledge-short-v1')
    settings = load_settings()
    assert settings.rag_enabled and settings.rag_generation_id == 'generation-1'
    assert settings.rag_profile == 'knowledge-short-v1'
    monkeypatch.setenv('BULLBEAR_RAG_ENABLED', 'false')
    assert not load_settings().rag_enabled


@pytest.mark.parametrize('status,warnings,expected', [
    ('empty', (), 'no_matching_knowledge'),
    ('timeout', ('search_deadline',), 'search_deadline'),
])
def test_fallback_persisted_before_runner_and_private_on_replay(setup, monkeypatch, status, warnings, expected):
    settings, market = setup
    install_retriever(monkeypatch, lambda snapshot, generation:
                      context_for(snapshot, status=status, warnings=warnings))
    seen = []
    class Runner(TestRunner):
        background_context = 'unset'
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            assert self.background_context is None
            record = manifest(settings, debate_id)['knowledge_context']
            decision = record['retrieval_config']['execution']
            assert record['payload']['status'] == status
            assert decision['action'] == 'fallback'
            assert decision['fallback_reason'] == expected
            assert decision['effective_profile'] == 'none'
            seen.append(record['context_id'])
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    app = create_app(settings=settings, market=market, token='test-token',
                     runner_factory=lambda: Runner(settings))
    with TestClient(app) as client:
        row = start(client).json()
        public = completed(client, row['debate_id'])
        assert public['status'] == 'completed'
        assert start(client, key='reuse-fallback').json()['debate_id'] == row['debate_id']
        events = client.get(f"/debates/{row['debate_id']}/events", headers=AUTH).text
        assert 'fallback_reason' not in events and 'KCTX.' not in events
        assert len(seen) == 1


@pytest.mark.parametrize('status,warnings', [
    ('failed', ('integrity_error',)),
    ('failed', ('future_generation',)),
    ('failed', ('generation_not_committed_at_decision',)),
    ('failed', ('retrieval_busy',)),
    ('failed', ('retrieval_unavailable',)),
    ('timeout', ('integrity_error',)),
    ('empty', ('historical_reconstruction',)),
    ('completed', ('historical_reconstruction',)),
])
def test_unsafe_retrieval_never_falls_back(setup, monkeypatch, status, warnings):
    settings, market = setup
    install_retriever(monkeypatch, lambda snapshot, generation:
                      context_for(snapshot, status=status, warnings=warnings))
    calls = []
    svc = Service(settings, market, runner_factory=lambda: calls.append(True))
    try:
        row, _ = svc.store.create('unsafe', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 0)
        assert svc.detail(row['id'])['status'] == 'failed' and not calls
        record = manifest(settings, row['id'])['knowledge_context']
        assert record['payload']['warnings'] == list(warnings)
        assert record['retrieval_config']['execution']['action'] == 'abort'
    finally:
        svc.close()


def test_fallback_audit_write_failure_prevents_model_initialization(setup, monkeypatch):
    settings, market = setup
    install_retriever(monkeypatch, lambda snapshot, generation:
                      context_for(snapshot, status='timeout', warnings=['search_deadline']))
    original = RunAudit._write
    def broken(audit):
        if 'knowledge_context' in audit.data:
            raise OSError('fixture audit unavailable')
        return original(audit)
    monkeypatch.setattr(RunAudit, '_write', broken)
    calls = []
    svc = Service(settings, market, runner_factory=lambda: calls.append(True))
    try:
        row, _ = svc.store.create('audit-failure', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 0)
        assert svc.detail(row['id'])['status'] == 'failed' and not calls
    finally:
        svc.close()


@pytest.mark.parametrize('failure', ['timeout', 'integrity', 'persistence'])
def test_real_retriever_persistence_and_execution_decision(setup, monkeypatch, failure):
    from bullbear.rag import retrieval
    from bullbear.rag.store import ArchiveCorruptError, RagStore
    settings, market = setup
    def search(*args, **kwargs):
        if failure == 'integrity':
            raise ArchiveCorruptError('private corrupt source path')
        raise TimeoutError('private blocked search path')
    monkeypatch.setattr(retrieval.Retriever, '_search', search)
    if failure == 'persistence':
        def save(*args):
            raise OSError('private persistence path')
        monkeypatch.setattr(retrieval, 'save_context', save)
    calls = []
    def runner():
        calls.append(True)
        return TestRunner(settings)
    svc = Service(settings, market, runner_factory=runner)
    try:
        row, _ = svc.store.create('actual-search', 'f', '005930', NOW.date().isoformat(), 2)
        svc.run(row['id'], market.quote('005930'), 0)
        public, private = svc.detail(row['id']), manifest(settings, row['id'])
        assert public['status'] == ('completed' if failure == 'timeout' else 'failed')
        assert bool(calls) == (failure == 'timeout')
        assert 'private ' not in json.dumps([public, private])
        if failure == 'persistence':
            assert 'knowledge_context' not in private
        else:
            record = private['knowledge_context']
            with RagStore(settings.data_dir / 'rag') as store:
                frozen = retrieval.Retriever(store).load_context(record['context_id'])
            assert frozen.payload == record['payload']
            assert frozen.payload['warnings'] == [
                'search_deadline' if failure == 'timeout' else 'integrity_error']
    finally:
        svc.close()

"""Private shadow isolation and actual pgvector integration, with no paid requests."""
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from bullbear.config import load_settings
from bullbear.rag.shadow import ShadowRunner
from bullbear.rag.store import RagStore
from bullbear.rag.index import GenerationIndex
from bullbear.rag.retrieval import Retriever, query_terms, _READERS
from bullbear.rag.vectors import VectorIndex
from bullbear.server.app import create_app
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW
from .http_fixture import TestRunner
from .test_rag_http import setup, context_for, install_retriever
from .test_rag_vectors import archive_dsn, vector_service
from .test_rag_retrieval import seed
from .test_server import AUTH, completed, parse_sse, start


def read_record(settings, run_id):
    return json.loads((settings.data_dir / 'rag-shadow' / f'{run_id}.json').read_text())


def test_http_shadow_failure_never_changes_primary_or_public_response(setup, monkeypatch):
    settings, market = setup
    settings = replace(settings, rag_shadow_enabled=True)
    seen = []
    def broken(self, run_id, snapshot, primary, generation):
        seen.append(primary.context_id)
        raise RuntimeError('PRIVATE_SHADOW_ERROR')
    monkeypatch.setattr(ShadowRunner, 'submit', broken)
    install_retriever(monkeypatch, lambda snap, _: context_for(snap))
    class Runner(TestRunner):
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            assert self.background_context.context_id == seen[0]
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    with TestClient(create_app(settings=settings, market=market, token='test-token',
                              runner_factory=lambda: Runner(settings))) as client:
        run_id = start(client).json()['debate_id']
        result = completed(client, run_id)
        assert result['status'] == 'completed'
        public = json.dumps([result, parse_sse(client.get(f'/debates/{run_id}/events', headers=AUTH).text)])
        assert 'PRIVATE_SHADOW' not in public and 'PRIVATE_KNOWLEDGE' not in public
        assert 'context_id' not in public
    assert len(seen) == 1


def test_capacity_is_bounded_and_invalid_config_is_private(tmp_path):
    settings = replace(load_settings(), data_dir=tmp_path, rag_postgres_dsn=None)
    runner = ShadowRunner(settings)
    snapshot = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)
    assert runner.readers is not _READERS
    runner.slot.acquire()
    assert runner.submit('busy', snapshot, None, 'g') is False
    assert read_record(settings, 'busy')['status'] == 'skipped_capacity'
    runner.slot.release()
    assert runner.submit('invalid', snapshot, None, 'g')
    runner.close()
    assert read_record(settings, 'invalid')['status'] == 'invalid_configuration'
    assert runner.slot.acquire(blocking=False)
    runner.slot.release()
    assert not runner.submit('closed', snapshot, None, 'g')


@pytest.mark.parametrize('mode', ['debate', 'single'])
def test_http_completes_while_shadow_is_still_running(setup, monkeypatch, mode):
    settings, market = setup
    settings = replace(settings, rag_shadow_enabled=True)
    entered, release = threading.Event(), threading.Event()
    def blocked(self, run_id, snapshot, primary, generation):
        entered.set()
        try:
            assert release.wait(15)
            self._write(run_id, {'status': 'completed', 'marker': 'PRIVATE_SHADOW'})
        finally:
            self.slot.release()
    monkeypatch.setattr(ShadowRunner, '_run', blocked)
    install_retriever(monkeypatch, lambda snap, _: context_for(snap))
    app = create_app(settings=settings, market=market, token='test-token',
                     runner_factory=lambda: TestRunner(settings))
    with TestClient(app) as client:
        try:
            extra = {}
            if mode == 'single':
                from .test_single_http import seed as seed_snapshot
                snapshot, _ = seed_snapshot(app, settings, market)
                extra['snapshot_id'] = snapshot.snapshot_id
            response = start(client, mode=mode, **extra)
            assert response.status_code == 202, response.text
            run_id = response.json()['debate_id']
            assert entered.wait(5)
            result = completed(client, run_id)
            assert result['status'] == 'completed'
            assert not release.is_set()
            public = json.dumps([result, parse_sse(client.get(f'/debates/{run_id}/events', headers=AUTH).text)])
            assert 'PRIVATE_SHADOW' not in public and 'PRIVATE_KNOWLEDGE' not in public
        finally:
            release.set()
    assert read_record(settings, run_id)['status'] == 'completed'


@pytest.mark.parametrize('future,missing_cache', [(False, False), (True, False), (False, True)])
def test_shadow_pgvector_observed_cutoff_and_cache_only(vector_service, tmp_path, future, missing_cache):
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(vector_service.spec.model_dump_json())
    settings = replace(load_settings(), data_dir=tmp_path, rag_shadow_spec=spec_path,
                       rag_postgres_dsn=vector_service.repository.dsn,
                       rag_archive_backend='sqlite', rag_object_backend='local')
    with RagStore(tmp_path / 'rag') as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        snapshot = build_snapshot(FakeSource(), '000000', '가짜전자',
                                  now=NOW if future else datetime.now(timezone.utc))
        if not missing_cache:
            vector_service.prepare(' '.join(query_terms(snapshot)), 'query', daily_budget_nano=100000)
        primary = Retriever(store).retrieve(snapshot, generation_id=generation)
    runner = ShadowRunner(settings)
    # Editing the spec during a process must not change the frozen version.
    spec_path.write_text('{}')
    before = vector_service.provider.calls
    assert runner.submit('probe', snapshot, primary, generation)
    runner.close()
    record = read_record(settings, 'probe')
    assert record['primary_context_id'] == primary.context_id
    assert record['primary_unchanged'] and record['time_policy'] == 'observed-v1'
    assert vector_service.provider.calls == before
    if future:
        assert record['status'] == 'generation_not_ready_at_decision'
    elif missing_cache:
        assert record['status'] == 'shadow_unavailable'
        assert record['error_type'] == 'EmbeddingUnavailable'
    else:
        assert record['status'] == 'completed', record
        assert {r['strategy'] for r in record['comparisons']} == {'dense', 'hybrid'}
        assert all(r['selected_chunk_ids'] for r in record['comparisons'])


def test_paid_preparation_requires_explicit_positive_budget(tmp_path):
    from .test_rag_vectors import spec
    path = tmp_path / 'spec.json'
    path.write_text(spec().model_copy(update={'provider': 'openai'}).model_dump_json())
    runner = ShadowRunner(replace(load_settings(), data_dir=tmp_path, rag_postgres_dsn='unused',
        rag_shadow_spec=path, rag_shadow_prepare_query=True, rag_shadow_daily_budget_nano=0))
    assert runner.spec is None
    runner.close()


def test_pilot_refuses_budget_before_provider_creation(tmp_path, monkeypatch):
    from pathlib import Path
    from bullbear.rag import embedding_pilot
    from .test_rag_vectors import spec
    monkeypatch.setattr(embedding_pilot, 'OpenAIEmbeddings', lambda: pytest.fail('paid call attempted'))
    with pytest.raises(ValueError, match='budget'):
        embedding_pilot.run_pilot('unused', Path('knowledge/common-short-v1.json'),
            Path('knowledge/embedding-evaluation-v1.json'), tmp_path, [spec()], budget_nano=0)


def test_invalid_judgments_refused_before_paid_work(tmp_path, monkeypatch):
    from pathlib import Path
    from bullbear.rag import embedding_pilot
    from .test_rag_vectors import spec
    dataset = json.loads(Path('knowledge/embedding-evaluation-v1.json').read_text(encoding='utf-8'))
    dataset['cases'][0]['path'] = 'invalid'
    cases = tmp_path / 'invalid.json'
    cases.write_text(json.dumps(dataset), encoding='utf-8')
    monkeypatch.setattr(embedding_pilot, 'OpenAIEmbeddings', lambda: pytest.fail('paid call attempted'))
    with pytest.raises(ValueError, match='judgments'):
        embedding_pilot.run_pilot('unused', Path('knowledge/common-short-v1.json'),
                                 cases, tmp_path / 'output', [spec()], budget_nano=100000)
    assert not (tmp_path / 'output').exists()

"""Publication rollover, immutable migration and crash boundaries without models."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bullbear.config import load_settings
from bullbear.rag.binding import capture_binding, migrate_binding, check_bindings
from bullbear.rag.context import KnowledgeContext
from bullbear.rag.evidence import DocumentRequest
from bullbear.rag.index import GenerationIndex
from bullbear.rag.retrieval import Retriever
from bullbear.rag.store import RagStore
from bullbear.server.app import create_app
from bullbear.server.store import Store
from .http_fixture import fixture_market
from .test_rag_evidence import snapshot
from .test_rag_retrieval import seed
from .test_server import AUTH
from .test_rag_archive_storage import archive_dsn


def prepare(tmp_path):
    with RagStore(tmp_path / 'rag') as archive:
        seed(archive, text='PER 주가수익비율 산식')
        first = GenerationIndex(archive).publish(datetime.now(timezone.utc))
    snap = snapshot().model_copy(update={'created_at': datetime.now(timezone.utc)})
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True,
        rag_generation_id=first, rag_archive_backend='sqlite', rag_context_backend='sqlite',
        rag_object_backend='local', rag_shadow_enabled=False)
    return settings, snap, first


def app_for(settings):
    return create_app(settings=settings, market=fixture_market(settings), token='test-token',
        runner_factory=lambda: pytest.fail('model must not run'))


def test_http_rollover_restart_receipt_loss_restore_and_fact_independence(tmp_path):
    settings, snap, first = prepare(tmp_path)
    body = dict(snapshot_id=snap.snapshot_id, ticker=snap.ticker, question='PER')
    app = app_for(settings)
    with TestClient(app) as client:
        service = app.state.service
        row, _ = service.store.create('seed', 'seed', snap.ticker, str(snap.as_of), 2)
        service.store.save_snapshot(row['id'], snap, binding_factory=service.capture_generation)
        service.store.emit(row['id'], 'debate_completed', {})
        original = service.store.snapshot(snap.snapshot_id)
        initial = client.post('/rag/search', json=body, headers=AUTH)
        assert initial.status_code == 200, initial.text
        assert initial.json()['documents']
        with RagStore(tmp_path / 'rag') as archive:
            second = GenerationIndex(archive).publish(datetime.now(timezone.utc))
        service.settings = replace(settings, rag_generation_id=second)
        assert client.post('/rag/search', json=body, headers=AUTH).json() == initial.json()
        # Reused ID cannot renew the original timestamp or pin.
        service.store.save_snapshot(row['id'], snap.model_copy(update={'created_at': datetime.now(timezone.utc)}),
            binding_factory=lambda _: pytest.fail('must not repin'))
        assert service.store.snapshot(snap.snapshot_id) == original
    app = app_for(replace(settings, rag_generation_id=second))
    with TestClient(app) as client, RagStore(tmp_path / 'rag') as archive:
        assert client.post('/rag/search', json=body, headers=AUTH).json() == initial.json()
        receipt = GenerationIndex(archive).path(first).with_suffix('.ready.json')
        saved = receipt.read_bytes()
        data = json.loads(saved)
        data['committed_at'] = (datetime.fromisoformat(data['committed_at']) - timedelta(seconds=1)).isoformat()
        receipt.write_text(json.dumps(data), encoding='utf-8')
        assert client.post('/rag/search', json=body, headers=AUTH).status_code == 503
        receipt.unlink()
        assert client.post('/rag/search', json=body, headers=AUTH).status_code == 503
        fact = dict(snapshot_id=snap.snapshot_id, ticker=snap.ticker, metric='close')
        assert client.post('/rag/facts', json=fact, headers=AUTH).status_code == 200
        receipt.write_bytes(saved)
        assert client.post('/rag/search', json=body, headers=AUTH).json() == initial.json()
        fresh = snap.model_copy(update={'snapshot_id': 'second', 'created_at': datetime.now(timezone.utc)})
        service = app.state.service
        service.store.save_snapshot('unused', fresh, binding_factory=service.capture_generation)
        assert service.store.generation_binding('second')['generation_id'] == second
        assert service.store.generation_binding(snap.snapshot_id)['generation_id'] == first
        unbound = snap.model_copy(update={'snapshot_id': 'legacy'})
        service.store.save_snapshot('unused', unbound)
        assert client.post('/rag/search', json={**body, 'snapshot_id': 'legacy'}, headers=AUTH).status_code == 503


def test_atomic_first_pin_concurrency_and_rollback(tmp_path):
    settings, snap, first = prepare(tmp_path)
    with RagStore(tmp_path / 'rag') as archive, closing(Store(tmp_path / 'http')) as worker:
        pin = capture_binding(archive, snap, first)
        calls = []
        def factory(value):
            calls.append(value.snapshot_id)
            return pin
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: worker.save_snapshot('unused', snap, binding_factory=factory), range(20)))
        assert calls == [snap.snapshot_id]
        assert worker.generation_binding(snap.snapshot_id) == pin
        def crash(_):
            raise RuntimeError('simulated crash before commit')
        with pytest.raises(RuntimeError):
            worker.save_snapshot('unused', snap.model_copy(update={'snapshot_id': 'crash'}), binding_factory=crash)
        assert worker.db.execute("SELECT count(*) FROM snapshots WHERE id='crash'").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            worker.db.execute('DELETE FROM snapshot_generations')
        worker.db.rollback()


def test_legacy_migration_context_evidence_dry_run_and_conflict(tmp_path):
    settings, snap, first = prepare(tmp_path)
    with RagStore(tmp_path / 'rag') as archive, closing(Store(tmp_path / 'http')) as worker:
        worker.save_snapshot('unused', snap)
        context = Retriever(archive).retrieve(snap, generation_id=first,
            request=DocumentRequest(ticker=snap.ticker, question='PER'))
        assert context.payload['status'] == 'completed'
        original = worker.snapshot(snap.snapshot_id)
        candidate = migrate_binding(worker, archive, snap.snapshot_id, context)
        assert worker.generation_binding(snap.snapshot_id) is None
        assert candidate['source_context_id'] == context.context_id
        bad = KnowledgeContext.from_payload({**context.payload, 'time_policy': 'reconstructed-v1'})
        with pytest.raises(ValueError):
            migrate_binding(worker, archive, snap.snapshot_id, bad, apply=True)
        pinned = migrate_binding(worker, archive, snap.snapshot_id, context, apply=True)
        assert migrate_binding(worker, archive, snap.snapshot_id, context, apply=True) == pinned
        with pytest.raises(ValueError):
            worker.bind_generation(snap.snapshot_id, {**pinned, 'generation_id': 'different'})
        assert worker.snapshot(snap.snapshot_id) == original
        assert Retriever(archive).load_context(context.context_id).payload == context.payload


def test_future_publication_never_becomes_eligible_by_retry(tmp_path):
    settings, snap, first = prepare(tmp_path)
    with RagStore(tmp_path / 'rag') as archive:
        future = GenerationIndex(archive).publish(datetime.now(timezone.utc) + timedelta(days=1))
        with pytest.raises(ValueError):
            capture_binding(archive, snap, future)
    app = app_for(replace(settings, rag_generation_id=future))
    with TestClient(app) as client:
        service = app.state.service
        service.store.save_snapshot('unused', snap, binding_factory=service.capture_generation)
        assert service.store.generation_binding(snap.snapshot_id)['state'] == 'unavailable'
        service.settings = settings
        body = dict(snapshot_id=snap.snapshot_id, ticker=snap.ticker, question='PER')
        assert client.post('/rag/search', json=body, headers=AUTH).status_code == 503


def test_inventory_and_cli_migration_do_not_recover_or_rewrite_legacy(tmp_path, capsys):
    from bullbear.rag.cli import main
    settings, snap, first = prepare(tmp_path)
    with RagStore(tmp_path / 'rag') as archive, closing(Store(tmp_path / 'http')) as worker:
        row, _ = worker.create('running', 'running', snap.ticker, str(snap.as_of), 2)
        worker.save_snapshot(row['id'], snap)
        context = Retriever(archive).retrieve(snap, generation_id=first)
        assert context.payload['status'] == 'completed'
        assert not check_bindings(worker, archive)['all_ready']

    args = ['--data-dir', str(tmp_path), 'bind-snapshot', '--snapshot-id', snap.snapshot_id,
        '--context-id', context.context_id]
    assert main(args) == 0
    assert not json.loads(capsys.readouterr().out)['applied']
    with closing(Store(tmp_path / 'http', maintenance=True, read_only=True)) as worker:
        assert worker.get(row['id'])['status'] == 'running'
        assert worker.generation_binding(snap.snapshot_id) is None
        assert not worker.events(row['id'])
    assert main(args + ['--apply']) == 0
    capsys.readouterr()
    assert main(['--data-dir', str(tmp_path), 'check-bindings']) == 0
    assert json.loads(capsys.readouterr().out)['all_ready']
    with closing(Store(tmp_path / 'http', maintenance=True)) as worker, RagStore(tmp_path / 'rag') as archive:
        assert worker.get(row['id'])['status'] == 'running'
        # Administrative corruption must be detected, never silently repinned.
        changed = snap.model_copy(update={'created_at': datetime.now(timezone.utc)})
        with worker.db:
            worker.db.execute('UPDATE snapshots SET data=? WHERE id=?', (changed.model_dump_json(), snap.snapshot_id))
        assert not check_bindings(worker, archive)['all_ready']


def test_pinned_http_with_real_postgres_archive_and_contexts(tmp_path, archive_dsn):
    from bullbear.rag.archive_repository import PostgresArchive
    from bullbear.rag.context_repository import PostgresContextRepository
    with PostgresArchive(tmp_path / 'rag', archive_dsn) as archive:
        seed(archive, text='PER 주가수익비율 산식')
        first = GenerationIndex(archive).publish(datetime.now(timezone.utc))
    snap = snapshot().model_copy(update={'created_at': datetime.now(timezone.utc)})
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True,
        rag_generation_id=first, rag_postgres_dsn=archive_dsn, rag_archive_backend='postgres',
        rag_context_backend='postgres', rag_object_backend='local', rag_shadow_enabled=False)
    app = app_for(settings)
    with TestClient(app) as client:
        service = app.state.service
        service.store.save_snapshot('unused', snap, binding_factory=service.capture_generation)
        with PostgresArchive(tmp_path / 'rag', archive_dsn) as archive:
            second = GenerationIndex(archive).publish(datetime.now(timezone.utc))
        service.settings = replace(settings, rag_generation_id=second)
        body = dict(snapshot_id=snap.snapshot_id, ticker=snap.ticker, question='PER')
        result = client.post('/rag/search', json=body, headers=AUTH)
        assert result.status_code == 200, result.text
        assert result.json()['documents']
        context = PostgresContextRepository(archive_dsn).load(result.json()['context_id'])
        assert context.payload['generation_id'] == first
        assert context.payload['generation_binding']['generation_id'] == first

"""Opt-in real PostgreSQL tests. Use a dedicated disposable DB, never production."""
import os
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from bullbear.rag.context_repository import PostgresContextRepository, SQLiteContextRepository
from bullbear.rag.storage import migrate, import_sqlite_contexts
from bullbear.rag.store import ArchiveCorruptError, RagStore
from bullbear.rag.index import GenerationIndex
from bullbear.rag.retrieval import Retriever
from bullbear.snapshot import build_snapshot
from .test_rag_context_repository import make_context
from .test_rag_retrieval import seed
from .fakes import FakeSource, NOW
from .http_fixture import TestRunner, fixture_market
from .test_rag_http import context_for, manifest
from bullbear.config import load_settings
from bullbear.server.service import Service
from bullbear.rag.context_repository import ContextStorageError


@pytest.fixture(scope="module")
def repository():
    dsn = os.getenv("BULLBEAR_TEST_RAG_POSTGRES_DSN")
    if not dsn:
        pytest.skip("dedicated BULLBEAR_TEST_RAG_POSTGRES_DSN not set")
    pytest.importorskip("psycopg")
    pytest.importorskip("alembic")
    migrate(dsn)
    migrate(dsn)  # Existing migration must be a no-op, including immutable rows.
    return PostgresContextRepository(dsn)


def test_postgres_roundtrip_concurrent_idempotency(repository):
    context = make_context()
    attempt = "SEARCH." + uuid4().hex
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: repository.save(context, {"status": "empty"}, attempt_id=attempt), range(8)))
    assert results == [attempt] * 8
    assert repository.load(context.context_id) == context
    assert repository.audits(context.context_id) == [{"status": "empty", "attempt_id": attempt}]


def test_postgres_attempt_conflict_rolls_back_new_context(repository):
    context, different = make_context(), make_context()
    attempt = repository.save(context, {})
    with pytest.raises(ArchiveCorruptError):
        repository.save(different, {}, attempt_id=attempt)
    with pytest.raises(KeyError):
        repository.load(different.context_id)


@pytest.mark.parametrize("table,operation", [("contexts", "UPDATE"), ("contexts", "DELETE"),
                                             ("searches", "UPDATE"), ("searches", "DELETE"),
                                             ("searches", "TRUNCATE")])
def test_postgres_database_enforces_immutability(repository, table, operation):
    import psycopg
    context = make_context()
    attempt = repository.save(context, {})
    key = context.context_id if table == "contexts" else attempt
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with psycopg.connect(repository.dsn) as db:
            if operation == "TRUNCATE":
                db.execute("TRUNCATE rag.searches")
            elif operation == "UPDATE":
                db.execute(f"UPDATE rag.{table} SET payload='changed' WHERE id=%s", (key,))
            else:
                db.execute(f"DELETE FROM rag.{table} WHERE id=%s", (key,))
    assert repository.load(context.context_id) == context
    assert len(repository.audits(context.context_id)) == 1


def test_migration_preserves_ids_order_payload_and_is_repeatable(repository, tmp_path):
    local = SQLiteContextRepository(tmp_path / "contexts.sqlite3")
    context = make_context()
    local.save(context, {"status": "empty", "attempt_number": 1})
    local.save(context, {"status": "empty", "attempt_number": 2})
    before = local.path.read_bytes()
    first = import_sqlite_contexts(local.path, repository)
    assert first == import_sqlite_contexts(local.path, repository)
    assert first["contexts"] == 1 and first["searches"] == 2
    assert repository.load(context.context_id) == local.load(context.context_id)
    assert repository.audits(context.context_id) == local.audits(context.context_id)
    assert local.path.read_bytes() == before


def test_import_conflict_rolls_back_entire_batch(repository, tmp_path):
    local = SQLiteContextRepository(tmp_path / "contexts.sqlite3")
    first, second = make_context(), make_context()
    local.save(first, {})
    conflict = local.save(second, {"source": "sqlite"})
    repository.save(second, {"source": "postgres"}, attempt_id=conflict)
    with pytest.raises(ArchiveCorruptError, match="conflict"):
        import_sqlite_contexts(local.path, repository)
    with pytest.raises(KeyError):
        repository.load(first.context_id)
    assert len(repository.audits(second.context_id)) == 1


def test_real_retrieval_persists_to_postgres_and_replays(repository, tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        retriever = Retriever(store, context_repository=repository)
        context = retriever.retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert context.payload["status"] == "completed"
        assert retriever.load_context(context.context_id) == context
        assert repository.audits(context.context_id)
        assert not (store.directory / "contexts.sqlite3").exists()


def test_import_rejects_reordered_existing_history(repository, tmp_path):
    local = SQLiteContextRepository(tmp_path / "contexts.sqlite3")
    context = make_context()
    local.save(context, {"order": 1})
    second = local.save(context, {"order": 2})
    repository.save(context, {"order": 2}, attempt_id=second)
    with pytest.raises(ArchiveCorruptError, match="history conflict"):
        import_sqlite_contexts(local.path, repository)
    assert len(repository.audits(context.context_id)) == 1


@pytest.mark.parametrize("storage_failure", [False, True])
def test_http_selected_repository_is_private_and_failure_stops_runner(repository, tmp_path, monkeypatch, storage_failure):
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True,
                       rag_generation_id="fixture-generation", rag_context_backend="postgres",
                       rag_postgres_dsn=repository.dsn)
    market = fixture_market(settings)
    calls, contexts = [], []

    def search(self, snapshot, *args, **kwargs):
        payload = context_for(snapshot, marker="PRIVATE-" + uuid4().hex).payload
        return {key: payload[key] for key in ("status", "items", "warnings")}
    monkeypatch.setattr(Retriever, "_search", search)
    if storage_failure:
        def fail(*args, **kwargs):
            raise ContextStorageError("fixture storage unavailable")
        monkeypatch.setattr(PostgresContextRepository, "save", fail)

    class Runner(TestRunner):
        background_context = None
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            contexts.append(self.background_context)
            assert repository.load(self.background_context.context_id) == self.background_context
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    def factory():
        calls.append(True)
        return Runner(settings)
    service = Service(settings, market, runner_factory=factory)
    try:
        row, _ = service.store.create("postgres-http", "f", "005930", NOW.date().isoformat(), 2)
        service.run(row["id"], market.quote("005930"), 1)
        public, private = service.detail(row["id"]), manifest(settings, row["id"])
        assert public["status"] == ("failed" if storage_failure else "completed")
        assert bool(calls) is not storage_failure
        assert repository.dsn not in json.dumps([public, private])
        assert "PRIVATE-" not in json.dumps(public)
        if not storage_failure:
            assert len(contexts) == 1
            assert private["knowledge_context"]["retrieval_config"]["context_backend"] == "postgres"
    finally:
        service.close()
        market.close()

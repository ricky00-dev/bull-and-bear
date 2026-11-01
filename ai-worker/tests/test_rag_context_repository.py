"""Storage contract, historical migration and explicit failure behavior."""
import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest

from bullbear.config import load_settings
from bullbear.rag.context import KnowledgeContext
from bullbear.rag.context_repository import (SQLiteContextRepository, PostgresContextRepository,
                                            configured_repository, ContextStorageError)
from bullbear.rag.schemas import canonical_json
from bullbear.rag.storage import read_sqlite_contexts, main
from bullbear.rag.store import ArchiveCorruptError


def make_context():
    return KnowledgeContext.from_payload({
        "schema_version": "knowledge-context-v1", "profile_version": "knowledge-short-v1",
        "snapshot_id": "fixture-" + uuid4().hex, "decision_at": "2026-10-30T08:00:00Z",
        "status": "empty", "items": [], "warnings": [], "time_policy": "observed-v1",
    })


def test_sqlite_preserves_history_and_rejects_conflicting_attempt_atomically(tmp_path):
    repo = SQLiteContextRepository(tmp_path / "contexts.sqlite3")
    context = make_context()
    attempt = repo.save(context, {"status": "empty"})
    assert repo.load(context.context_id) == context
    assert repo.save(context, {"status": "empty"}, attempt_id=attempt) == attempt
    assert len(repo.audits(context.context_id)) == 1
    different = make_context()
    with pytest.raises(ArchiveCorruptError, match="attempt id"):
        repo.save(different, {"status": "empty"}, attempt_id=attempt)
    with pytest.raises(KeyError):
        repo.load(different.context_id)


def test_readonly_import_validation_and_dry_run_need_no_postgres(tmp_path, monkeypatch, capsys):
    path = tmp_path / "contexts.sqlite3"
    repo = SQLiteContextRepository(path)
    context = make_context()
    first = repo.save(context, {"status": "empty", "search_elapsed_seconds": 0.1})
    second = repo.save(context, {"status": "empty", "search_elapsed_seconds": 0.2})
    before = path.read_bytes()
    data = read_sqlite_contexts(path)
    assert [row[0] for row in data["searches"]] == [first, second]
    assert data["contexts"] == [[context.context_id, context.payload_json]]
    monkeypatch.delenv("BULLBEAR_RAG_POSTGRES_DSN", raising=False)
    assert main(["import-contexts", str(path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["contexts"] == 1 and report["searches"] == 2
    assert path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["hash", "orphan", "audit_context"])
def test_source_corruption_is_rejected(tmp_path, corruption):
    path = tmp_path / "contexts.sqlite3"
    repo = SQLiteContextRepository(path)
    context = make_context()
    repo.save(context, {"status": "empty"})
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER contexts_update")
        db.execute("DROP TRIGGER searches_update")
        if corruption == "hash":
            db.execute("UPDATE contexts SET payload=?", (make_context().payload_json,))
        elif corruption == "orphan":
            db.execute("UPDATE searches SET context_id=?", (make_context().context_id,))
        else:
            db.execute("UPDATE searches SET payload=?", (canonical_json({"context_id": make_context().context_id}),))
    with pytest.raises((ArchiveCorruptError, ValueError)):
        read_sqlite_contexts(path)


def test_missing_source_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        read_sqlite_contexts(path)
    assert not path.exists()


def test_configuration_is_explicit_and_secret_not_in_repr(monkeypatch):
    monkeypatch.setenv("BULLBEAR_RAG_POSTGRES_DSN", "postgresql://user:private-secret@localhost/rag")
    monkeypatch.setenv("BULLBEAR_RAG_CONTEXT_BACKEND", "postgres")
    settings = load_settings()
    repo = configured_repository(settings)
    assert isinstance(repo, PostgresContextRepository)
    assert "private-secret" not in repr(settings) + repr(repo)
    assert configured_repository(replace(settings, rag_context_backend="sqlite")) is None
    with pytest.raises(ValueError, match="missing"):
        configured_repository(replace(settings, rag_postgres_dsn=None))
    with pytest.raises(ValueError, match="unsupported"):
        configured_repository(replace(settings, rag_context_backend="unknown"))


def test_driver_failure_is_sanitized(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    def fail(*args, **kwargs):
        raise psycopg.OperationalError("password=private-secret")
    monkeypatch.setattr(psycopg, "connect", fail)
    repo = PostgresContextRepository("password=private-secret")
    with pytest.raises(ContextStorageError) as exc:
        repo.save(make_context(), {})
    assert "private-secret" not in str(exc.value)


def test_cli_does_not_print_dsn(monkeypatch, capsys):
    monkeypatch.setenv("BULLBEAR_RAG_POSTGRES_DSN", "private-secret-invalid-dsn")
    assert main(["migrate"]) == 1
    output = capsys.readouterr()
    assert "private-secret" not in output.out + output.err

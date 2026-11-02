"""Immutable context/audit persistence. PostgreSQL is opt-in; no runtime DDL there."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .context import KnowledgeContext
from .schemas import canonical_json
from .store import ArchiveCorruptError


class ContextStorageError(RuntimeError):
    """Safe failure message; never include database credentials or driver details."""


class ContextRepository(Protocol):
    def save(self, context: KnowledgeContext, audit: dict, *, attempt_id: str | None = None) -> str: ...
    def load(self, context_id: str) -> KnowledgeContext: ...
    def audits(self, context_id: str) -> list[dict]: ...


def checked_context(context_id: str, payload: str) -> KnowledgeContext:
    check_id(context_id)
    try:
        context = KnowledgeContext(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise ArchiveCorruptError("saved context is invalid") from exc
    if context.context_id != context_id:
        raise ArchiveCorruptError("saved context hash mismatch")
    return context


def check_id(context_id: str) -> None:
    if not re.fullmatch(r"KCTX\.[0-9a-f]{64}", context_id):
        raise ValueError("invalid context id")


def prepare(context: KnowledgeContext, audit: dict, attempt_id: str | None) -> tuple[str, str]:
    checked_context(context.context_id, context.payload_json)
    if not isinstance(audit, dict) or "attempt_id" in audit:
        raise ValueError("invalid retrieval audit")
    if audit.get("context_id", context.context_id) != context.context_id:
        raise ValueError("audit context mismatch")
    attempt_id = attempt_id or "SEARCH." + uuid4().hex
    if not re.fullmatch(r"SEARCH\.[0-9a-f]{32}", attempt_id):
        raise ValueError("invalid attempt id")
    return attempt_id, canonical_json(audit)


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS contexts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS searches(id TEXT PRIMARY KEY,context_id TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS searches_update BEFORE UPDATE ON searches BEGIN SELECT RAISE(ABORT,'immutable search'); END;
CREATE TRIGGER IF NOT EXISTS searches_delete BEFORE DELETE ON searches BEGIN SELECT RAISE(ABORT,'immutable search'); END;
CREATE TRIGGER IF NOT EXISTS contexts_update BEFORE UPDATE ON contexts BEGIN SELECT RAISE(ABORT,'immutable context'); END;
CREATE TRIGGER IF NOT EXISTS contexts_delete BEFORE DELETE ON contexts BEGIN SELECT RAISE(ABORT,'immutable context'); END;
"""


@dataclass(frozen=True)
class SQLiteContextRepository:
    path: Path

    def save(self, context, audit, *, attempt_id=None):
        attempt_id, audit_json = prepare(context, audit, attempt_id)
        with closing(sqlite3.connect(self.path, timeout=1)) as db:
            db.executescript(SQLITE_SCHEMA)
            with db:
                db.execute("INSERT OR IGNORE INTO contexts VALUES (?,?)", (context.context_id, context.payload_json))
                if db.execute("SELECT payload FROM contexts WHERE id=?", (context.context_id,)).fetchone()[0] != context.payload_json:
                    raise ArchiveCorruptError("saved context mismatch")
                db.execute("INSERT OR IGNORE INTO searches VALUES (?,?,?)", (attempt_id, context.context_id, audit_json))
                if db.execute("SELECT context_id,payload FROM searches WHERE id=?", (attempt_id,)).fetchone() != (context.context_id, audit_json):
                    raise ArchiveCorruptError("attempt id reused with different content")
        return attempt_id

    def load(self, context_id):
        check_id(context_id)
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT payload FROM contexts WHERE id=?", (context_id,)).fetchone()
        if row is None:
            raise KeyError(context_id)
        return checked_context(context_id, row[0])

    def audits(self, context_id):
        check_id(context_id)
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return [{**json.loads(row[1]), "attempt_id": row[0]} for row in db.execute(
                "SELECT id,payload FROM searches WHERE context_id=? ORDER BY rowid", (context_id,))]


@dataclass(frozen=True)
class PostgresContextRepository:
    # One connection per operation avoids shared transactions across HTTP threads.
    dsn: str = field(repr=False)

    def __post_init__(self):
        if not self.dsn.strip():
            raise ValueError("missing RAG PostgreSQL DSN")

    @contextmanager
    def _connection(self):
        try:
            import psycopg
        except ImportError:
            raise ContextStorageError("install the rag-postgres optional dependencies") from None
        try:
            with psycopg.connect(self.dsn, connect_timeout=3) as db:
                db.execute("SET LOCAL statement_timeout = '3000ms'")
                db.execute("SET LOCAL lock_timeout = '1000ms'")
                yield db
        except psycopg.Error:
            raise ContextStorageError("RAG PostgreSQL storage unavailable or inconsistent") from None

    def save(self, context, audit, *, attempt_id=None):
        attempt_id, audit_json = prepare(context, audit, attempt_id)
        with self._connection() as db:
            db.execute("INSERT INTO rag.contexts(id,payload) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                       (context.context_id, context.payload_json))
            if db.execute("SELECT payload FROM rag.contexts WHERE id=%s", (context.context_id,)).fetchone()[0] != context.payload_json:
                raise ArchiveCorruptError("saved context mismatch")
            db.execute("INSERT INTO rag.searches(id,context_id,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                       (attempt_id, context.context_id, audit_json))
            if db.execute("SELECT context_id,payload FROM rag.searches WHERE id=%s", (attempt_id,)).fetchone() != (context.context_id, audit_json):
                raise ArchiveCorruptError("attempt id reused with different content")
        return attempt_id

    def load(self, context_id):
        check_id(context_id)
        with self._connection() as db:
            row = db.execute("SELECT payload FROM rag.contexts WHERE id=%s", (context_id,)).fetchone()
        if row is None:
            raise KeyError(context_id)
        return checked_context(context_id, row[0])

    def audits(self, context_id):
        check_id(context_id)
        with self._connection() as db:
            rows = db.execute("SELECT id,payload FROM rag.searches WHERE context_id=%s ORDER BY seq", (context_id,)).fetchall()
        return [{**json.loads(row[1]), "attempt_id": row[0]} for row in rows]


def configured_repository(settings) -> ContextRepository | None:
    """None retains the caller's existing archive-local SQLite database."""
    backend = settings.rag_context_backend
    if backend == "sqlite":
        return None
    if backend == "postgres":
        if not settings.rag_postgres_dsn:
            raise ValueError("missing RAG PostgreSQL DSN")
        return PostgresContextRepository(settings.rag_postgres_dsn)
    raise ValueError("unsupported RAG context backend")

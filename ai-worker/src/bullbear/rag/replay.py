"""Private, append-only context and retrieval-attempt records, separate from events."""
import json
import re
import sqlite3
from contextlib import closing
from uuid import uuid4

from .context import KnowledgeContext
from .schemas import canonical_json
from .store import ArchiveCorruptError


def save_context(store, context: KnowledgeContext, audit: dict) -> str:
    attempt_id = "SEARCH." + uuid4().hex
    with closing(sqlite3.connect(store.directory / "contexts.sqlite3", timeout=1)) as db, db:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS contexts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS searches(id TEXT PRIMARY KEY,context_id TEXT NOT NULL,payload TEXT NOT NULL);"
            "CREATE TRIGGER IF NOT EXISTS searches_update BEFORE UPDATE ON searches BEGIN SELECT RAISE(ABORT,'immutable search'); END;"
            "CREATE TRIGGER IF NOT EXISTS searches_delete BEFORE DELETE ON searches BEGIN SELECT RAISE(ABORT,'immutable search'); END;"
            "CREATE TRIGGER IF NOT EXISTS contexts_update BEFORE UPDATE ON contexts BEGIN SELECT RAISE(ABORT,'immutable context'); END;"
            "CREATE TRIGGER IF NOT EXISTS contexts_delete BEFORE DELETE ON contexts BEGIN SELECT RAISE(ABORT,'immutable context'); END;")
        db.execute("INSERT OR IGNORE INTO contexts VALUES (?,?)", (context.context_id, context.payload_json))
        if db.execute("SELECT payload FROM contexts WHERE id=?", (context.context_id,)).fetchone()[0] != context.payload_json:
            raise ArchiveCorruptError("saved context mismatch")
        db.execute("INSERT INTO searches VALUES (?,?,?)", (attempt_id, context.context_id, canonical_json(audit)))
    return attempt_id


def load_context(store, context_id: str) -> KnowledgeContext:
    if not re.fullmatch(r"KCTX\.[0-9a-f]{64}", context_id):
        raise ValueError("invalid context id")
    path = store.directory / "contexts.sqlite3"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT payload FROM contexts WHERE id=?", (context_id,)).fetchone()
    if row is None:
        raise KeyError(context_id)
    context = KnowledgeContext(row[0])
    if context.context_id != context_id:
        raise ArchiveCorruptError("saved context hash mismatch")
    return context


def retrieval_audits(store, context_id: str) -> list[dict]:
    path = store.directory / "contexts.sqlite3"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return [{"attempt_id": row[0], **json.loads(row[1])} for row in db.execute(
            "SELECT id,payload FROM searches WHERE context_id=? ORDER BY rowid", (context_id,))]

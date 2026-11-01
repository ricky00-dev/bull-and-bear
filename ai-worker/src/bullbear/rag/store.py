"""SQLite archive v1. Short serialized writes; separate WAL readers; immutable history."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .schemas import AnnotationInput, ChunkInput, CollectionBatch, CollectionResult, DocumentInput, canonical_json, digest, stamp, utc

from .objects import ArchiveCorruptError, LocalObjectStore, ObjectStorageError

SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
 document_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_item_id TEXT NOT NULL,
 kind TEXT NOT NULL, canonical_url TEXT NOT NULL, UNIQUE(source, source_item_id));
CREATE TABLE IF NOT EXISTS collection_runs(
 collection_id TEXT PRIMARY KEY, source TEXT NOT NULL, query_key TEXT NOT NULL,
 window_start TEXT NOT NULL, window_end TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
 observation_mode TEXT NOT NULL CHECK(observation_mode IN ('current','archive')),
 status TEXT NOT NULL CHECK(status IN ('completed','empty','partial','failed')),
 coverage TEXT NOT NULL CHECK(coverage IN ('complete','partial','unknown')),
 pages INTEGER NOT NULL CHECK(pages>=0), safe_error TEXT, fingerprint TEXT NOT NULL,
 input_json TEXT NOT NULL, result_json TEXT NOT NULL, stored_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_revisions(
 revision_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
 content_hash TEXT NOT NULL, object_path TEXT NOT NULL, content_json TEXT NOT NULL,
 title TEXT NOT NULL, text TEXT NOT NULL, published_at TEXT, published_on TEXT,
 source_updated_at TEXT, first_observed_at TEXT NOT NULL, timestamp_precision TEXT NOT NULL,
 content_level TEXT NOT NULL, unit TEXT NOT NULL, quarantine_reason TEXT,
 UNIQUE(document_id,content_hash));
CREATE TABLE IF NOT EXISTS collection_items(
 collection_id TEXT NOT NULL REFERENCES collection_runs(collection_id), ordinal INTEGER NOT NULL,
 revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id), observed_at TEXT NOT NULL,
 input_json TEXT NOT NULL, quarantine_reason TEXT, PRIMARY KEY(collection_id,ordinal));
CREATE INDEX IF NOT EXISTS collection_items_revision_at ON collection_items(revision_id,observed_at);
CREATE TABLE IF NOT EXISTS document_events(
 event_seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
 document_id TEXT NOT NULL REFERENCES documents(document_id),
 revision_id TEXT REFERENCES document_revisions(revision_id),
 collection_id TEXT REFERENCES collection_runs(collection_id),
 item_ordinal INTEGER,
 kind TEXT NOT NULL CHECK(kind IN ('revision_activated','withdrawn','deleted')),
 observed_at TEXT NOT NULL, source_ref TEXT NOT NULL,
 FOREIGN KEY(collection_id,item_ordinal) REFERENCES collection_items(collection_id,ordinal));
CREATE INDEX IF NOT EXISTS document_events_at ON document_events(document_id,observed_at,event_seq);
CREATE TABLE IF NOT EXISTS source_watermarks(
 source TEXT NOT NULL, query_key TEXT NOT NULL, covered_from TEXT NOT NULL,
 completed_through TEXT NOT NULL, cursor TEXT, updated_at TEXT NOT NULL,
 collection_id TEXT NOT NULL REFERENCES collection_runs(collection_id), PRIMARY KEY(source,query_key));
CREATE TABLE IF NOT EXISTS chunks(
 chunk_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id),
 ordinal INTEGER NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL,
 source_locator TEXT NOT NULL, chunker_version TEXT NOT NULL,
 UNIQUE(revision_id,chunker_version,ordinal));
CREATE TABLE IF NOT EXISTS chunk_annotations(
 annotation_seq INTEGER PRIMARY KEY AUTOINCREMENT, annotation_id TEXT NOT NULL UNIQUE,
 chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id), review_status TEXT NOT NULL,
 created_at TEXT NOT NULL, reviewed_at TEXT, tagging_policy_version TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunk_horizons(
 annotation_id TEXT NOT NULL REFERENCES chunk_annotations(annotation_id), horizon_tag TEXT NOT NULL
 CHECK(horizon_tag IN ('common','short','medium','long')), PRIMARY KEY(annotation_id,horizon_tag));
CREATE INDEX IF NOT EXISTS chunk_annotations_at ON chunk_annotations(chunk_id,reviewed_at,annotation_seq);
"""


def quarantine_reason(item: DocumentInput) -> str | None:
    if not item.publication_verified:
        return "publication_unverified"
    if item.timestamp_precision == "unknown":
        return "publication_time_unknown"
    if item.published_at and item.published_at > item.observed_at:
        return "publication_after_observation"
    if item.published_on and item.published_on > item.observed_at.astimezone(KST).date():
        return "publication_date_after_observation"
    if item.source_updated_at and item.source_updated_at > item.observed_at:
        return "update_after_observation"
    return None


class RagStore:
    def __init__(self, directory: Path | str, *, object_store=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.objects = self.directory / "objects"
        self.objects.mkdir(exist_ok=True)
        self.object_store = object_store if object_store is not None else LocalObjectStore(self.objects)
        self.path = self.directory / "rag.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError(f"unsupported archive schema version: {version}")
            self.db.execute("PRAGMA journal_mode=WAL")
            immutable = ("documents", "document_revisions", "document_events", "collection_runs", "collection_items",
                         "chunks", "chunk_annotations", "chunk_horizons")
            triggers = "\n".join(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'archive rows are immutable'); END;"
                for table in immutable for op in ("UPDATE", "DELETE"))
            self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + triggers +
                                 f"\nPRAGMA user_version={SCHEMA_VERSION};\n" +
                                 f"INSERT OR IGNORE INTO schema_migrations VALUES ({SCHEMA_VERSION},'{stamp(datetime.now(timezone.utc))}');\nCOMMIT;")
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        with self.lock:
            self.db.close()

    def open_reader(self) -> sqlite3.Connection:
        """Caller owns/closes this read-only connection (and its optional snapshot transaction)."""
        reader = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
        reader.row_factory = sqlite3.Row
        reader.execute("PRAGMA query_only=ON")
        return reader

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    @contextmanager
    def _read_snapshot(self):
        # A document lookup spans event, revision and observation queries. Pin all
        # of them to one WAL snapshot even when another Store instance commits.
        with self.lock:
            own_transaction = not self.db.in_transaction
            if own_transaction:
                self.db.execute("BEGIN")
            try:
                yield
                if own_transaction:
                    self.db.execute("COMMIT")
            except BaseException:
                if own_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def _object(self, item: DocumentInput) -> str:
        payload = canonical_json(item.content()).encode("utf-8")
        self.object_store.put(item.content_hash, payload)
        return f"objects/{item.content_hash}"

    def import_collection(self, batch: CollectionBatch) -> CollectionResult:
        batch = CollectionBatch.model_validate(batch.model_dump(mode="json"))
        fingerprint = digest(batch.model_dump(mode="json"))
        # Files are written before taking SQLite's writer lock; rollback may leave an
        # unreferenced content-addressed object, never a committed dangling reference.
        objects = {item.content_hash: self._object(item) for item in batch.items}
        with self.transaction() as db:
            return self._import_collection(db, batch, objects, fingerprint)

    def _import_collection(self, db, batch, objects, fingerprint):
        """Internal transaction participant; caller validates input and uploads objects."""
        old = db.execute("SELECT fingerprint,result_json FROM collection_runs WHERE collection_id=?", (batch.collection_id,)).fetchone()
        if old:
            if old["fingerprint"] != fingerprint:
                raise ValueError("collection_id was reused with different input")
            return CollectionResult.model_validate_json(old["result_json"]).model_copy(update={"reused": True})
        # Validate ambiguous observations before publishing any database records.
        observed = {}
        for item in batch.items:
            key = item.document_id, stamp(item.observed_at)
            if key in observed and observed[key] != item.revision_id:
                raise ValueError("different revisions at the same observation timestamp are ambiguous")
            observed[key] = item.revision_id
        # Child records and the final immutable collection row commit together.
        db.execute("PRAGMA defer_foreign_keys=ON")
        revisions = events = quarantined = 0
        for ordinal, item in sorted(enumerate(batch.items), key=lambda pair: pair[1].observed_at):
            db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)", (item.document_id, item.source, item.source_item_id, item.kind, item.url))
            identity = db.execute("SELECT kind FROM documents WHERE document_id=?", (item.document_id,)).fetchone()
            if identity["kind"] != item.kind:
                raise ValueError("document source identity cannot change kind")
            reason = quarantine_reason(item)
            quarantined += reason is not None
            object_path = objects[item.content_hash]
            inserted = db.execute("INSERT OR IGNORE INTO document_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                item.revision_id, item.document_id, item.content_hash, object_path, canonical_json(item.content()),
                item.title, item.text, stamp(item.published_at) if item.published_at else None,
                item.published_on.isoformat() if item.published_on else None,
                stamp(item.source_updated_at) if item.source_updated_at else None, stamp(item.observed_at),
                item.timestamp_precision, item.content_level, item.unit, reason)).rowcount
            revisions += inserted
            db.execute("INSERT INTO collection_items VALUES (?,?,?,?,?,?)", (batch.collection_id, ordinal, item.revision_id,
                       stamp(item.observed_at), canonical_json(item.model_dump(mode="json")), reason))
            if batch.observation_mode == "current":
                last = db.execute("SELECT e.kind,e.revision_id,e.observed_at,i.quarantine_reason FROM document_events e LEFT JOIN collection_items i ON i.collection_id=e.collection_id AND i.ordinal=e.item_ordinal WHERE e.document_id=? AND e.observed_at<=? ORDER BY e.observed_at DESC,e.event_seq DESC LIMIT 1", (item.document_id, stamp(item.observed_at))).fetchone()
                if last and last["observed_at"] == stamp(item.observed_at) and last["kind"] == "revision_activated" and last["revision_id"] != item.revision_id:
                    raise ValueError("different revisions at the same observation timestamp are ambiguous")
                if not last or last["kind"] != "revision_activated" or last["revision_id"] != item.revision_id or last["quarantine_reason"] != reason:
                    db.execute("INSERT INTO document_events(event_id,document_id,revision_id,collection_id,item_ordinal,kind,observed_at,source_ref) VALUES (?,?,?,?,?,?,?,?)",
                               ("E." + digest([batch.collection_id, ordinal, "revision_activated"]), item.document_id,
                                item.revision_id, batch.collection_id, ordinal, "revision_activated", stamp(item.observed_at), item.source_ref))
                    events += 1
        advanced, reason = self._watermark(db, batch)
        result = CollectionResult(collection_id=batch.collection_id, status=batch.status, imported_items=len(batch.items),
                                  new_revisions=revisions, new_events=events, quarantined_items=quarantined,
                                  rejected_items=batch.rejected_items,
                                  watermark_advanced=advanced, watermark_reason=reason)
        db.execute("INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            batch.collection_id, batch.source, batch.query_key, stamp(batch.window_start), stamp(batch.window_end),
            stamp(batch.started_at), stamp(batch.finished_at), batch.observation_mode, batch.status, batch.coverage,
            batch.pages, batch.safe_error, fingerprint, canonical_json(batch.model_dump(mode="json")),
            result.model_dump_json(), stamp(datetime.now(timezone.utc))))
        return result

    @staticmethod
    def _watermark(db, batch):
        if batch.completed_through is None:
            return False, "not_requested"
        old = db.execute("SELECT * FROM source_watermarks WHERE source=? AND query_key=?", (batch.source, batch.query_key)).fetchone()
        through = stamp(batch.completed_through)
        if old and stamp(batch.window_start) > old["completed_through"]:
            return False, "coverage_gap"
        if old and through <= old["completed_through"]:
            return False, "not_newer"
        covered_from = min(old["covered_from"], stamp(batch.window_start)) if old else stamp(batch.window_start)
        db.execute("INSERT INTO source_watermarks VALUES (?,?,?,?,?,?,?) ON CONFLICT(source,query_key) DO UPDATE SET covered_from=excluded.covered_from,completed_through=excluded.completed_through,cursor=excluded.cursor,updated_at=excluded.updated_at,collection_id=excluded.collection_id", (
            batch.source, batch.query_key, covered_from, through, batch.cursor, stamp(batch.finished_at), batch.collection_id))
        return True, "advanced"

    def collection(self, collection_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM collection_runs WHERE collection_id=?", (collection_id,)).fetchone()
            return dict(row) if row else None

    def watermark(self, source: str, query_key: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM source_watermarks WHERE source=? AND query_key=?", (source, query_key)).fetchone()
            return dict(row) if row else None

    def revision(self, revision_id: str) -> dict | None:
        with self._read_snapshot():
            row = self.db.execute("SELECT * FROM document_revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if not row:
                return None
            value = dict(row)
            try:
                content = json.loads(value["content_json"])
                if value["object_path"] != f"objects/{value['content_hash']}":
                    raise ValueError("object path mismatch")
                if digest(content) != value["content_hash"] or self.object_store.get(value["content_hash"]) != canonical_json(content).encode("utf-8"):
                    raise ValueError("hash mismatch")
            except (OSError, ValueError, TypeError, ObjectStorageError):
                raise ArchiveCorruptError("saved document object failed integrity check") from None
            value["content"] = content
            # Captures can be imported out of order. Preserve the original immutable
            # row for audit, but derive the earliest actual current observation.
            earliest = self.db.execute("SELECT MIN(i.observed_at) FROM collection_items i JOIN collection_runs c USING(collection_id) WHERE i.revision_id=? AND c.observation_mode='current'", (revision_id,)).fetchone()[0]
            value["first_recorded_observation_at"] = value["first_observed_at"]
            if earliest is not None:
                value["first_observed_at"] = earliest
            return value

    def document_at(self, document_id: str, decision_at: datetime) -> dict | None:
        cutoff = stamp(decision_at)
        with self._read_snapshot():
            event = self.db.execute("SELECT e.*,i.quarantine_reason AS observation_quarantine_reason FROM document_events e LEFT JOIN collection_items i ON i.collection_id=e.collection_id AND i.ordinal=e.item_ordinal WHERE e.document_id=? AND e.observed_at<=? ORDER BY e.observed_at DESC,e.event_seq DESC LIMIT 1", (document_id, cutoff)).fetchone()
            if not event or event["kind"] != "revision_activated":
                return None
            value = self.revision(event["revision_id"])
            if event["observation_quarantine_reason"] or value["first_observed_at"] > cutoff:
                return None
            if value["published_at"] and value["published_at"] > cutoff:
                return None
            value["activation_event_id"] = event["event_id"]
            value["initial_quarantine_reason"] = value["quarantine_reason"]
            value["quarantine_reason"] = event["observation_quarantine_reason"]
            return value

    def record_event(self, *, event_id: str, document_id: str, kind: str, observed_at: datetime, source_ref: str) -> None:
        """Explicit provider-confirmed removal; a missing search result is never a deletion."""
        if kind not in {"withdrawn", "deleted"} or not event_id or not source_ref:
            raise ValueError("explicit removal event and source_ref required")
        values = (event_id, document_id, None, None, None, kind, stamp(observed_at), source_ref)
        with self.transaction() as db:
            old = db.execute("SELECT event_id,document_id,revision_id,collection_id,item_ordinal,kind,observed_at,source_ref FROM document_events WHERE event_id=?", (event_id,)).fetchone()
            if old and tuple(old) != values:
                raise ValueError("event_id was reused with different input")
            db.execute("INSERT OR IGNORE INTO document_events(event_id,document_id,revision_id,collection_id,item_ordinal,kind,observed_at,source_ref) VALUES (?,?,?,?,?,?,?,?)", values)

    def add_chunk(self, chunk: ChunkInput) -> str:
        chunk = ChunkInput.model_validate(chunk.model_dump(mode="json"))
        with self.transaction() as db:
            revision = self.revision(chunk.revision_id)
            if not revision or chunk.text not in revision["title"] + "\n" + revision["text"]:
                raise ValueError("chunk must quote the saved source text")
            db.execute("INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?,?,?)", (chunk.chunk_id, chunk.revision_id,
                       chunk.ordinal, chunk.text, digest(chunk.text), chunk.source_locator, chunk.chunker_version))
            row = db.execute("SELECT chunk_id FROM chunks WHERE revision_id=? AND chunker_version=? AND ordinal=?", (chunk.revision_id, chunk.chunker_version, chunk.ordinal)).fetchone()
            if row["chunk_id"] != chunk.chunk_id:
                raise ValueError("chunk ordinal already has different immutable content")
        return chunk.chunk_id

    def annotate(self, annotation: AnnotationInput, *, initial_only: bool = False) -> str:
        annotation = AnnotationInput.model_validate(annotation.model_dump(mode="json"))
        data = annotation.model_dump(mode="json")
        annotation_id = "A." + digest(data)
        with self.transaction() as db:
            if initial_only:
                # Importers must not renew approval or override a later human
                # rejection/proposal merely by observing the same revision again.
                existing = db.execute("SELECT annotation_id FROM chunk_annotations WHERE chunk_id=? "
                                      "ORDER BY annotation_seq DESC LIMIT 1", (annotation.chunk_id,)).fetchone()
                if existing:
                    return existing["annotation_id"]
            original = db.execute("SELECT revision_id FROM chunks WHERE chunk_id=?", (annotation.chunk_id,)).fetchone()
            revision = self.revision(original["revision_id"]) if original else None
            if not revision or stamp(annotation.created_at) < revision["first_observed_at"]:
                raise ValueError("annotation must follow source observation")
            db.execute("INSERT OR IGNORE INTO chunk_annotations(annotation_id,chunk_id,review_status,created_at,reviewed_at,tagging_policy_version,data_json) VALUES (?,?,?,?,?,?,?)", (
                annotation_id, annotation.chunk_id, annotation.review_status, stamp(annotation.created_at),
                stamp(annotation.reviewed_at) if annotation.reviewed_at else None, annotation.tagging_policy_version, canonical_json(data)))
            db.executemany("INSERT OR IGNORE INTO chunk_horizons VALUES (?,?)", [(annotation_id, tag) for tag in annotation.horizons])
        return annotation_id

    def annotation_at(self, chunk_id: str, decision_at: datetime) -> dict | None:
        """Latest review outcome wins; a rejection cannot resurrect an older approval."""
        cutoff = stamp(decision_at)
        with self.lock:
            row = self.db.execute("SELECT * FROM chunk_annotations WHERE chunk_id=? AND reviewed_at<=? ORDER BY reviewed_at DESC,annotation_seq DESC LIMIT 1", (chunk_id, cutoff)).fetchone()
            if not row or row["review_status"] != "approved":
                return None
            value = json.loads(row["data_json"])
            if value["valid_from"] and stamp(datetime.fromisoformat(value["valid_from"])) > cutoff:
                return None
            if value["valid_until"] and stamp(datetime.fromisoformat(value["valid_until"])) <= cutoff:
                return None
            return {"annotation_id": row["annotation_id"], **value}

    def counts(self) -> dict:
        with self.lock:
            return {table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("documents", "document_revisions", "document_events", "collection_runs", "chunks", "chunk_annotations")}

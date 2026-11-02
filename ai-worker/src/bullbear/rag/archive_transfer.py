"""Offline, all-or-nothing archive cutover. Source is always opened read-only."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .objects import ArchiveCorruptError
from .schemas import AnnotationInput, ChunkInput, CollectionBatch, DocumentInput, canonical_json, digest, stamp
from .store import SCHEMA, quarantine_reason
from .jobs import SCHEMA as JOB_SCHEMA

TABLES = ("documents", "collection_runs", "document_revisions", "collection_items",
          "document_events", "source_watermarks", "chunks", "chunk_annotations", "chunk_horizons",
          "ingest_jobs", "ingest_attempts")
OPTIONAL_TABLES = {"ingest_jobs", "ingest_attempts"}


def _require(value):
    if not value:
        raise ArchiveCorruptError("source archive validation failed")


def read_archive(path: Path, *, objects=None):
    path = path.resolve()
    # No mkdir or schema initialization on the source.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        _require(db.execute("PRAGMA user_version").fetchone()[0] == 1)
        _require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok")
        _require(not db.execute("PRAGMA foreign_key_check").fetchall())
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Never interpolate column names supplied by an arbitrary source schema.
        with closing(sqlite3.connect(":memory:")) as expected:
            expected.executescript(SCHEMA + JOB_SCHEMA)
            for table in TABLES:
                if table in OPTIONAL_TABLES and table not in present:
                    continue
                _require([r[1] for r in db.execute(f"PRAGMA table_info({table})")] ==
                         [r[1] for r in expected.execute(f"PRAGMA table_info({table})")])
        data = {table: sorted([dict(row) for row in db.execute(f"SELECT * FROM {table}")],
                              key=canonical_json) if table in present else [] for table in TABLES}
    # Retain bytes from the verified snapshot, so a later local file change cannot
    # introduce an unchecked object during transfer. First-week tool is in-memory.
    payloads = {}
    for row in data["document_revisions"]:
        content = json.loads(row["content_json"])
        doc = DocumentInput.model_validate({**content, "observed_at": row["first_observed_at"]})
        _require(doc.revision_id == row["revision_id"] and doc.document_id == row["document_id"])
        _require(doc.content_hash == row["content_hash"] and row["object_path"] == f"objects/{doc.content_hash}")
        for key in ("title", "text", "unit", "timestamp_precision", "content_level"):
            _require(row[key] == getattr(doc, key))
        for key in ("published_at", "source_updated_at"):
            _require(row[key] == (stamp(getattr(doc, key)) if getattr(doc, key) else None))
        _require(row["published_on"] == (doc.published_on.isoformat() if doc.published_on else None))
        _require(row["quarantine_reason"] == quarantine_reason(doc))
        if objects is None:
            target = path.parent / row["object_path"]
            _require(not target.is_symlink())
            payload = target.read_bytes()
        else:
            payload = objects.get(doc.content_hash)
        _require(payload == canonical_json(content).encode("utf-8"))
        payloads[doc.content_hash] = payload
    revisions = {r["revision_id"]: r for r in data["document_revisions"]}
    documents = {r["document_id"]: r for r in data["documents"]}
    for row in data["documents"]:
        _require(row["document_id"] == "D." + digest([row["source"], row["source_item_id"]]))
    for row in data["document_revisions"]:
        content = json.loads(row["content_json"])
        document = documents[row["document_id"]]
        _require(all(document[k] == content[k] for k in ("source", "source_item_id", "kind")))
    batches = {}
    for row in data["collection_runs"]:
        batch = CollectionBatch.model_validate_json(row["input_json"])
        _require(batch.collection_id == row["collection_id"] and digest(batch.model_dump(mode="json")) == row["fingerprint"])
        for key in ("source", "query_key", "observation_mode", "status", "coverage", "pages", "safe_error"):
            _require(row[key] == getattr(batch, key))
        for key in ("window_start", "window_end", "started_at", "finished_at"):
            _require(row[key] == stamp(getattr(batch, key)))
        batches[batch.collection_id] = batch
    items = {(r["collection_id"], r["ordinal"]): r for r in data["collection_items"]}
    _require(len(items) == sum(len(b.items) for b in batches.values()))
    for (collection, ordinal), row in items.items():
        _require(0 <= ordinal < len(batches[collection].items))
        doc = batches[collection].items[ordinal]
        _require(row["input_json"] == canonical_json(doc.model_dump(mode="json")))
        _require(row["revision_id"] == doc.revision_id and row["observed_at"] == stamp(doc.observed_at))
        _require(row["quarantine_reason"] == quarantine_reason(doc))
    for row in data["source_watermarks"]:
        batch = batches[row["collection_id"]]
        _require(batch.completed_through is not None)
        _require(row["source"] == batch.source and row["query_key"] == batch.query_key)
        _require(row["completed_through"] == stamp(batch.completed_through))
        _require(row["updated_at"] == stamp(batch.finished_at) and row["cursor"] == batch.cursor)
        _require(row["covered_from"] <= row["completed_through"])
    for row in data["document_events"]:
        _require(row["event_seq"] > 0)
        if row["kind"] == "revision_activated":
            item = items[(row["collection_id"], row["item_ordinal"])]
            _require(row["event_id"] == "E." + digest([row["collection_id"], row["item_ordinal"], "revision_activated"]))
            _require(row["revision_id"] == item["revision_id"] and row["observed_at"] == item["observed_at"])
            _require(revisions[row["revision_id"]]["document_id"] == row["document_id"])
        else:
            _require(row["kind"] in {"withdrawn", "deleted"} and bool(row["source_ref"]))
    for row in data["chunks"]:
        chunk = ChunkInput.model_validate({k: row[k] for k in ChunkInput.model_fields})
        original = revisions[chunk.revision_id]
        _require(chunk.chunk_id == row["chunk_id"] and digest(chunk.text) == row["text_hash"])
        _require(chunk.text in original["title"] + "\n" + original["text"])
    horizons = {}
    for row in data["chunk_horizons"]:
        horizons.setdefault(row["annotation_id"], set()).add(row["horizon_tag"])
    for row in data["chunk_annotations"]:
        annotation = AnnotationInput.model_validate_json(row["data_json"])
        _require(row["annotation_seq"] > 0 and row["annotation_id"] == "A." + digest(annotation.model_dump(mode="json")))
        for key in ("chunk_id", "review_status", "tagging_policy_version"):
            _require(row[key] == getattr(annotation, key))
        _require(row["created_at"] == stamp(annotation.created_at))
        _require(row["reviewed_at"] == (stamp(annotation.reviewed_at) if annotation.reviewed_at else None))
        _require(horizons.get(row["annotation_id"], set()) == set(annotation.horizons))
    for row in data["ingest_jobs"]:
        # Stop/drain workers before cutover; never transplant active lease owners.
        _require(row["state"] != "running" and row["lease_token"] is None and row["lease_until"] is None)
        batch = CollectionBatch.model_validate_json(row["payload"])
        _require(row["job_id"] == "JOB." + digest([batch.source, batch.collection_id]))
        _require(row["fingerprint"] == digest([row["ticker"], batch.model_dump(mode="json"), row["max_attempts"]]))
        _require(row["collection_id"] == batch.collection_id and row["source"] == batch.source)
        _require(row["query_key"] == batch.query_key == row["ticker"])
        _require(row["window_start"] == stamp(batch.window_start) and row["window_end"] == stamp(batch.window_end))
    for row in data["ingest_attempts"]:
        _require(row["event_id"] == "JE." + digest([row["lease_token"], row["event"]]))
    return data, payloads


def import_archive(path: Path, destination=None, *, dry_run=False, source_objects=None):
    data, payloads = read_archive(path, objects=source_objects)
    report = {"source_hash": digest(data), "tables": {t: len(data[t]) for t in TABLES},
              "objects": len(payloads), "dry_run": dry_run}
    if dry_run:
        return report
    # An interrupted transfer can leave verified unreferenced objects. Re-run is
    # safe; never delete source objects or publish a dangling DB reference.
    for key, payload in payloads.items():
        destination.object_store.put(key, payload)
    with destination.transaction() as db:
        # Also exclude administrative SQL writers not using the advisory lock.
        db.execute("LOCK TABLE " + ",".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE")
        existing = {t: sorted([dict(r) for r in db.execute(f"SELECT * FROM {t}")], key=canonical_json) for t in TABLES}
        if any(existing.values()):
            if existing != data:
                raise ArchiveCorruptError("destination must be empty or an exact prior import")
            return report
        for table in TABLES:
            for row in data[table]:
                columns = ",".join(row)
                db.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        # Preserve tie-breaking sequence values and ensure future events/reviews
        # advance beyond them. Sequence gaps after rollback are harmless.
        for table, column in (("document_events", "event_seq"), ("chunk_annotations", "annotation_seq")):
            if data[table]:
                db.execute(f"SELECT setval(pg_get_serial_sequence('rag.{table}', '{column}'), "
                           f"GREATEST((SELECT MAX({column}) FROM {table}), "
                           f"nextval(pg_get_serial_sequence('rag.{table}', '{column}'))), true)")
    return report


def copy_objects(path: Path, destination, *, dry_run=False):
    """Move bytes to another backend while keeping the SQLite metadata unchanged."""
    data, payloads = read_archive(path)
    if not dry_run:
        for key, payload in payloads.items():
            destination.put(key, payload)
    return {"source_hash": digest(data), "objects": len(payloads), "dry_run": dry_run}

"""Offline immutable FTS5 generations; BM25 never sees another generation's rows."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .schemas import canonical_json, digest, stamp
from .store import ArchiveCorruptError, RagStore

NORMALIZER_VERSION = "unicode61-nfc-alias-v2"
INDEX_VERSION = "observed-background-fts5-v2"


def normalize(text: str) -> list[str]:
    return sorted(set(re.findall(r"[\w]+", unicodedata.normalize("NFC", text).lower(), flags=re.UNICODE)))


def current_member(db, store: RagStore, chunk_id: str, cutoff: str) -> tuple[dict | None, str]:
    row = db.execute("SELECT c.*,r.document_id,r.content_hash,r.content_json,r.object_path,"
                     "r.title,r.published_at,r.published_on,r.timestamp_precision,d.kind,d.canonical_url "
                     "FROM chunks c JOIN document_revisions r USING(revision_id) "
                     "JOIN documents d USING(document_id) WHERE c.chunk_id=?", (chunk_id,)).fetchone()
    if not row:
        return None, "missing_chunk"
    item = dict(row)
    if item["kind"] not in {"knowledge", "research"}:
        return None, "kind"
    event = db.execute("SELECT e.*,i.quarantine_reason FROM document_events e LEFT JOIN collection_items i "
                       "ON i.collection_id=e.collection_id AND i.ordinal=e.item_ordinal "
                       "WHERE e.document_id=? AND e.observed_at<=? ORDER BY e.observed_at DESC,e.event_seq DESC LIMIT 1",
                       (item["document_id"], cutoff)).fetchone()
    if not event or event["kind"] != "revision_activated" or event["revision_id"] != item["revision_id"]:
        return None, "inactive_revision"
    if event["quarantine_reason"] or (item["published_at"] and item["published_at"] > cutoff):
        return None, "publication"
    annotation = db.execute("SELECT * FROM chunk_annotations WHERE chunk_id=? AND reviewed_at<=? "
                            "ORDER BY reviewed_at DESC,annotation_seq DESC LIMIT 1", (chunk_id, cutoff)).fetchone()
    if not annotation or annotation["review_status"] != "approved":
        return None, "review"
    data = json.loads(annotation["data_json"])
    if (data["valid_from"] and stamp(datetime.fromisoformat(data["valid_from"])) > cutoff or
            data["valid_until"] and stamp(datetime.fromisoformat(data["valid_until"])) <= cutoff):
        return None, "validity"
    if not set(data["horizons"]) & {"common", "short"}:
        return None, "horizon"
    try:
        content = json.loads(item["content_json"])
        if item["object_path"] != f"objects/{item['content_hash']}" or digest(content) != item["content_hash"]:
            raise ValueError("invalid object")
        if store.directory.joinpath(item["object_path"]).read_bytes() != canonical_json(content).encode("utf-8"):
            raise ValueError("invalid object")
        if digest(item["text"]) != item["text_hash"] or item["text"] not in content["title"] + "\n" + content["text"]:
            raise ValueError("invalid chunk")
    except (OSError, ValueError, TypeError):
        raise ArchiveCorruptError("knowledge source integrity check failed") from None
    earliest = db.execute("SELECT MIN(i.observed_at) FROM collection_items i JOIN collection_runs r USING(collection_id) "
                          "WHERE i.revision_id=? AND r.observation_mode='current' AND i.quarantine_reason IS NULL",
                          (item["revision_id"],)).fetchone()[0]
    if earliest is None or earliest > cutoff:
        return None, "observation"
    return {"chunk_id": chunk_id, "revision_id": item["revision_id"], "document_id": item["document_id"],
            "annotation_id": annotation["annotation_id"], "text": item["text"], "text_hash": item["text_hash"],
            "content_hash": item["content_hash"], "title": item["title"], "kind": item["kind"],
            "url": item["canonical_url"], "source_locator": item["source_locator"],
            "chunker_version": item["chunker_version"], "published_at": item["published_at"],
            "published_on": item["published_on"], "timestamp_precision": item["timestamp_precision"],
            "first_observed_at": earliest, "activation_event_id": event["event_id"],
            "reviewed_at": annotation["reviewed_at"], **{key: data[key] for key in (
                "horizons", "topics", "markets", "tickers", "study_scope", "applicability", "limitations", "duplicate_group_id")}}, "eligible"


class GenerationIndex:
    def __init__(self, store: RagStore):
        self.store = store
        self.directory = store.directory / "generations"
        self.directory.mkdir(exist_ok=True)

    def path(self, generation_id: str) -> Path:
        if not re.fullmatch(r"G\.[0-9a-f]{64}", generation_id):
            raise ValueError("invalid generation id")
        return self.directory / generation_id / "index.sqlite3"

    def publish(self, as_of: datetime) -> str:
        cutoff = stamp(as_of)
        db = self.store.open_reader()
        members, exclusions = [], {}
        try:
            db.execute("BEGIN")
            for row in db.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id").fetchall():
                member, reason = current_member(db, self.store, row[0], cutoff)
                if member:
                    members.append(member)
                else:
                    exclusions[reason] = exclusions.get(reason, 0) + 1
        finally:
            db.close()
        payload = {"index_version": INDEX_VERSION, "normalizer_version": NORMALIZER_VERSION,
                   "sqlite_version": sqlite3.sqlite_version, "as_of": cutoff, "members": members}
        generation_id = "G." + digest(payload)
        target = self.path(generation_id)
        if target.exists():
            existing, _ = self.open(generation_id)
            existing.close()
            return generation_id
        staging = self.directory / f".{uuid4().hex}"
        staging.mkdir()
        temp = staging / "index.sqlite3"
        receipt_temp = temp.with_suffix(".ready.json")
        try:
            with closing(sqlite3.connect(temp)) as writer, writer:
                writer.executescript("CREATE TABLE manifest(payload TEXT NOT NULL);"
                                     "CREATE TABLE members(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);"
                                     "CREATE VIRTUAL TABLE corpus USING fts5(search_text,tokenize='unicode61');")
                writer.execute("INSERT INTO manifest VALUES (?)", (canonical_json(payload),))
                for number, member in enumerate(members, 1):
                    writer.execute("INSERT INTO members VALUES (?,?)", (number, canonical_json(member)))
                    text = unicodedata.normalize("NFC", " ".join([member["title"], member["text"], *member["topics"]]))
                    writer.execute("INSERT INTO corpus(rowid,search_text) VALUES (?,?)", (number, text))
            # Publish only a closed, committed file. A reader opens it read-only.
            with temp.open("rb+") as handle:
                os.fsync(handle.fileno())
            receipt = {"sha256": hashlib.sha256(temp.read_bytes()).hexdigest(),
                       "committed_at": stamp(datetime.now(timezone.utc))}
            with receipt_temp.open("x", encoding="utf-8") as handle:
                handle.write(canonical_json(receipt))
                handle.flush()
                os.fsync(handle.fileno())
            # Publish DB and receipt together. Never replace an existing generation.
            try:
                os.rename(staging, target.parent)
            except OSError:
                if not target.exists():
                    raise
                existing, _ = self.open(generation_id)
                existing.close()
        finally:
            if staging.exists():
                temp.unlink(missing_ok=True)
                receipt_temp.unlink(missing_ok=True)
                staging.rmdir()
        return generation_id

    def open(self, generation_id: str, *, check=lambda: None):
        path = self.path(generation_id)
        receipt = json.loads(path.with_suffix(".ready.json").read_text(encoding="utf-8"))
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(65536):
                check()
                checksum.update(block)
        if checksum.hexdigest() != receipt["sha256"]:
            raise ArchiveCorruptError("generation file hash mismatch")
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            manifest = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
            if "G." + digest(manifest) != generation_id or manifest["index_version"] != INDEX_VERSION:
                raise ArchiveCorruptError("generation manifest hash/version mismatch")
            return db, {**manifest, "committed_at": receipt["committed_at"]}
        except BaseException:
            db.close()
            raise


def publish_generation(store: RagStore, as_of: datetime) -> str:
    return GenerationIndex(store).publish(as_of)

"""Explicit prewarming of sealed BM25 files, preserving their original receipt."""
import hashlib
import json
import os
from uuid import uuid4

from .index import GenerationIndex
from .objects import ArchiveCorruptError


def push_generation(store, generation_id):
    index = GenerationIndex(store)
    db, manifest = index.open(generation_id)
    db.close()
    path = index.path(generation_id)
    payload = path.read_bytes()
    receipt = path.with_suffix(".ready.json").read_bytes()
    index_hash, receipt_hash = (hashlib.sha256(data).hexdigest() for data in (payload, receipt))
    if json.loads(receipt)["sha256"] != index_hash:
        raise ArchiveCorruptError("generation changed during transfer")
    store.object_store.put(index_hash, payload)
    store.object_store.put(receipt_hash, receipt)
    values = (generation_id, index_hash, receipt_hash, manifest["committed_at"])
    with store.transaction() as db:
        db.execute("INSERT OR IGNORE INTO generations VALUES (?,?,?,?)", values)
        old = db.execute("SELECT * FROM generations WHERE generation_id=?", (generation_id,)).fetchone()
        if tuple(old) != values:
            raise ArchiveCorruptError("generation registry conflict; fetch the existing sealed generation")
    return {"generation_id": generation_id, "index_hash": index_hash, "committed_at": manifest["committed_at"]}


def fetch_generation(store, generation_id):
    index = GenerationIndex(store)
    path = index.path(generation_id)
    with store.lock:
        row = store.db.execute("SELECT * FROM generations WHERE generation_id=?", (generation_id,)).fetchone()
    if row is None:
        raise KeyError("generation not published")
    payload = store.object_store.get(row["index_hash"])
    receipt = store.object_store.get(row["receipt_hash"])
    saved = json.loads(receipt)
    if saved["sha256"] != row["index_hash"] or saved["committed_at"] != row["committed_at"]:
        raise ArchiveCorruptError("generation receipt mismatch")
    staging = index.directory / f".{uuid4().hex}"
    staging.mkdir()
    try:
        for name, content in (("index.sqlite3", payload), ("index.ready.json", receipt)):
            with (staging / name).open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        # Verify manifest identity before making the cache directory visible.
        import sqlite3
        from .schemas import digest
        from .index import INDEX_VERSION
        db = sqlite3.connect((staging / "index.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            manifest = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
            if "G." + digest(manifest) != generation_id or manifest["index_version"] != INDEX_VERSION:
                raise ArchiveCorruptError("generation manifest mismatch")
        finally:
            db.close()
        # Avoid per-document network I/O during the one-second retrieval budget.
        # This is a separate deployment/prewarm command, never a search callback.
        for key in {member["content_hash"] for member in manifest["members"]}:
            store.object_store.get(key)
        try:
            os.rename(staging, path.parent)
        except OSError:
            if not path.exists():
                raise
        db, _ = index.open(generation_id)
        db.close()
        if path.read_bytes() != payload or path.with_suffix(".ready.json").read_bytes() != receipt:
            raise ArchiveCorruptError("existing generation cache conflicts with registry")
    finally:
        if staging.exists():
            for name in ("index.sqlite3", "index.ready.json"):
                (staging / name).unlink(missing_ok=True)
            staging.rmdir()
    return {"generation_id": generation_id, "committed_at": row["committed_at"]}

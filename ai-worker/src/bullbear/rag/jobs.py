"""Durable, bounded ingestion of captured batches; never calls a provider or LLM."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .schemas import CollectionBatch, canonical_json, digest, stamp, utc
from .objects import ArchiveCorruptError, ObjectStorageError
from .context_repository import ContextStorageError

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_jobs (
 job_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL UNIQUE,
 source TEXT NOT NULL, query_key TEXT NOT NULL, ticker TEXT NOT NULL,
 window_start TEXT NOT NULL, window_end TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','retry','succeeded','partial','failed')),
 attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
 available_at TEXT NOT NULL, lease_until TEXT, lease_token TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, safe_error TEXT);
CREATE INDEX IF NOT EXISTS ingest_jobs_due ON ingest_jobs(state,available_at,lease_until);
CREATE INDEX IF NOT EXISTS ingest_jobs_scope ON ingest_jobs(source,query_key,state,window_start,window_end);
CREATE TABLE IF NOT EXISTS ingest_attempts (
 event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES ingest_jobs(job_id),
 lease_token TEXT NOT NULL, attempt INTEGER NOT NULL, event TEXT NOT NULL,
 occurred_at TEXT NOT NULL, safe_error TEXT);
CREATE INDEX IF NOT EXISTS ingest_attempts_job ON ingest_attempts(job_id,attempt,occurred_at);
"""


class LeaseLost(RuntimeError):
    pass


def incremental_window(store, source, query_key, *, start, end, overlap_seconds=3600):
    """Overlap is intentional: corrections are new revisions, not duplicate work."""
    start, end = utc(start), utc(end)
    if start >= end or not 0 <= overlap_seconds <= 7 * 86400:
        raise ValueError("invalid incremental window")
    watermark = store.watermark(source, query_key)
    if watermark:
        through = datetime.fromisoformat(watermark["completed_through"])
        if through > end:
            raise ValueError("end precedes existing watermark")
        start = max(start, through - timedelta(seconds=overlap_seconds))
    return {"source": source, "query_key": query_key, "window_start": stamp(start), "window_end": stamp(end)}


class IngestJobs:
    def __init__(self, store):
        self.store = store
        # SQLite additive side tables; PG DDL is only applied by Alembic.
        if isinstance(store.db, sqlite3.Connection):
            with store.lock:
                triggers = "\n".join(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_ingest_attempts_{op.lower()} BEFORE {op} "
                    "ON ingest_attempts BEGIN SELECT RAISE(ABORT,'attempts are immutable'); END;"
                    for op in ("UPDATE", "DELETE"))
                store.db.executescript("BEGIN IMMEDIATE;" + SCHEMA + triggers + "COMMIT;")

    def _now(self, db, now=None):
        if now is not None:
            return utc(now)
        if isinstance(self.store.db, sqlite3.Connection):
            return datetime.now(timezone.utc)
        # Worker clock skew cannot reclaim another PostgreSQL worker's lease.
        return db.execute("SELECT clock_timestamp()").fetchone()[0]

    def enqueue(self, batch, *, ticker, max_attempts=3, now=None):
        batch = CollectionBatch.model_validate(batch.model_dump(mode="json"))
        if not re.fullmatch(r"\d{6}", ticker) or not 1 <= max_attempts <= 10:
            raise ValueError("invalid ticker or retry limit")
        if batch.query_key != ticker or any(item.tickers and ticker not in item.tickers for item in batch.items):
            raise ValueError("capture query/ticker mismatch")
        payload = canonical_json(batch.model_dump(mode="json"))
        fingerprint = digest([ticker, batch.model_dump(mode="json"), max_attempts])
        job_id = "JOB." + digest([batch.source, batch.collection_id])
        with self.store.transaction() as db:
            at = stamp(self._now(db, now))
            old = db.execute("SELECT * FROM ingest_jobs WHERE collection_id=?", (batch.collection_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("collection job identity conflict")
                return old["job_id"]
            db.execute("INSERT INTO ingest_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                job_id, batch.collection_id, batch.source, batch.query_key, ticker, stamp(batch.window_start), stamp(batch.window_end), fingerprint, payload,
                "pending", 0, max_attempts, at, None, None, at, at, None))
        return job_id

    def _event(self, db, row, event, at, error=None):
        db.execute("INSERT INTO ingest_attempts VALUES (?,?,?,?,?,?,?)", (
            "JE." + digest([row["lease_token"], event]), row["job_id"], row["lease_token"],
            row["attempts"], event, stamp(at), error))

    def claim(self, *, lease_seconds=60, now=None):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid lease duration")
        with self.store.transaction() as db:
            at = self._now(db, now)
            # An expired last attempt must become terminal, not stay running forever.
            expired = db.execute("SELECT * FROM ingest_jobs WHERE state='running' AND lease_until<=?", (stamp(at),)).fetchall()
            for row in expired:
                self._event(db, row, "expired", at, "lease_expired")
                state = "failed" if row["attempts"] >= row["max_attempts"] else "retry"
                db.execute("UPDATE ingest_jobs SET state=?,available_at=?,lease_until=NULL,lease_token=NULL,updated_at=?,safe_error=? WHERE job_id=?",
                    (state, stamp(at), stamp(at), "lease_expired", row["job_id"]))
            row = db.execute("SELECT j.* FROM ingest_jobs j WHERE j.state IN ('pending','retry') AND j.available_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM ingest_jobs p WHERE p.source=j.source AND p.query_key=j.query_key "
                "AND p.job_id<>j.job_id AND (p.state='running' OR (p.state IN ('pending','retry') AND "
                "(p.window_start,p.window_end,p.created_at,p.job_id)<(j.window_start,j.window_end,j.created_at,j.job_id)))) "
                "ORDER BY j.available_at,j.window_start,j.window_end,j.created_at,j.job_id LIMIT 1", (stamp(at),)).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            db.execute("UPDATE ingest_jobs SET state='running',attempts=attempts+1,lease_until=?,lease_token=?,updated_at=?,safe_error=NULL WHERE job_id=?",
                (stamp(at + timedelta(seconds=lease_seconds)), token, stamp(at), row["job_id"]))
            claimed = dict(db.execute("SELECT * FROM ingest_jobs WHERE job_id=?", (row["job_id"],)).fetchone())
            self._event(db, claimed, "started", at)
            return claimed

    def _owned(self, db, job, at):
        row = db.execute("SELECT * FROM ingest_jobs WHERE job_id=?", (job["job_id"],)).fetchone()
        if not row or row["state"] != "running" or row["lease_token"] != job["lease_token"] or row["lease_until"] <= stamp(at):
            raise LeaseLost("ingestion lease expired or replaced")
        return row

    def heartbeat(self, job, *, lease_seconds=60, now=None):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid lease duration")
        with self.store.transaction() as db:
            at = self._now(db, now)
            self._owned(db, job, at)
            db.execute("UPDATE ingest_jobs SET lease_until=?,updated_at=? WHERE job_id=?",
                       (stamp(at + timedelta(seconds=lease_seconds)), stamp(at), job["job_id"]))

    def execute(self, job, *, now=None):
        # Read authoritative payload, never trust a caller-modified claim dict.
        with self.store.transaction() as db:
            at = self._now(db, now)
            row = dict(self._owned(db, job, at))
        try:
            batch = CollectionBatch.model_validate_json(row["payload"])
            if digest([row["ticker"], batch.model_dump(mode="json"), row["max_attempts"]]) != row["fingerprint"]:
                raise ArchiveCorruptError("job payload mismatch")
            if (row["source"], row["query_key"], row["collection_id"], row["window_start"], row["window_end"]) != (
                    batch.source, batch.query_key, batch.collection_id, stamp(batch.window_start), stamp(batch.window_end)):
                raise ArchiveCorruptError("job metadata mismatch")
            objects = {item.content_hash: self.store._object(item) for item in batch.items}
            with self.store.transaction() as db:
                at = self._now(db, now)
                self._owned(db, job, at)  # Fence stale workers AFTER slow object I/O.
                result = self.store._import_collection(db, batch, objects, digest(batch.model_dump(mode="json")))
                state = "succeeded" if result.status in {"completed", "empty"} else result.status
                self._event(db, row, state, at, batch.safe_error)
                db.execute("UPDATE ingest_jobs SET state=?,lease_until=NULL,lease_token=NULL,updated_at=?,safe_error=? WHERE job_id=?",
                           (state, stamp(at), batch.safe_error, job["job_id"]))
                return state
        except LeaseLost:
            raise
        except (ObjectStorageError, ContextStorageError, sqlite3.OperationalError):
            return self._fail(job, "storage_unavailable", retry=True, now=now)
        except (ValueError, ArchiveCorruptError, sqlite3.IntegrityError):
            return self._fail(job, "invalid_capture_or_conflict", retry=False, now=now)

    def _fail(self, job, error, *, retry, now=None):
        with self.store.transaction() as db:
            at = self._now(db, now)
            row = self._owned(db, job, at)
            state = "retry" if retry and row["attempts"] < row["max_attempts"] else "failed"
            delay = min(300, 5 * 2 ** (row["attempts"] - 1))
            self._event(db, row, state, at, error)
            db.execute("UPDATE ingest_jobs SET state=?,available_at=?,lease_until=NULL,lease_token=NULL,updated_at=?,safe_error=? WHERE job_id=?",
                       (state, stamp(at + timedelta(seconds=delay)), stamp(at), error, job["job_id"]))
            return state

    def run(self, *, limit=30, lease_seconds=60):
        if not 1 <= limit <= 1000:
            raise ValueError("invalid run limit")
        outcomes = []
        for _ in range(limit):
            job = self.claim(lease_seconds=lease_seconds)
            if job is None:
                break
            try:
                state = self.execute(job)
            except LeaseLost:
                state = "lease_lost"
            outcomes.append({"job_id": job["job_id"], "ticker": job["ticker"], "state": state})
        return outcomes

    def status(self):
        with self.store.lock:
            return [dict(row) for row in self.store.db.execute(
                "SELECT job_id,collection_id,source,ticker,window_start,window_end,state,attempts,max_attempts,available_at,lease_until,safe_error "
                "FROM ingest_jobs ORDER BY created_at,job_id")]


def main(argv=None):
    from pathlib import Path
    from ..config import load_settings
    from .archive_repository import configured_archive
    from .ingest import normalize_capture
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("manifest", type=Path, help="JSON list of {ticker,batch} or {ticker,capture}")
    enqueue.add_argument("--max-attempts", type=int, default=3)
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int, default=30)
    run.add_argument("--lease-seconds", type=int, default=60)
    sub.add_parser("status")
    plan = sub.add_parser("plan")
    plan.add_argument("--source", required=True)
    plan.add_argument("--tickers", required=True, help="comma-separated six-digit tickers")
    plan.add_argument("--start", type=datetime.fromisoformat, required=True)
    plan.add_argument("--end", type=datetime.fromisoformat, required=True)
    plan.add_argument("--overlap-seconds", type=int, default=3600)
    args = parser.parse_args(argv)
    try:
        with configured_archive(load_settings()) as store:
            jobs = IngestJobs(store)
            if args.command == "enqueue":
                entries = json.loads(args.manifest.read_text(encoding="utf-8"))
                if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
                    raise ValueError("invalid manifest")
                normalized = [(e["ticker"], normalize_capture(e["capture"]) if "capture" in e
                               else CollectionBatch.model_validate(e["batch"])) for e in entries]
                report = [jobs.enqueue(b, ticker=t, max_attempts=args.max_attempts) for t, b in normalized]
            elif args.command == "run":
                report = jobs.run(limit=args.limit, lease_seconds=args.lease_seconds)
            elif args.command == "plan":
                tickers = list(dict.fromkeys(args.tickers.split(",")))
                if not 1 <= len(tickers) <= 1000 or any(not re.fullmatch(r"\d{6}", t) for t in tickers):
                    raise ValueError("invalid tickers")
                report = [incremental_window(store, args.source, t, start=args.start, end=args.end,
                           overlap_seconds=args.overlap_seconds) for t in tickers]
            else:
                report = jobs.status()
        print(json.dumps(report, ensure_ascii=False))
        return 1 if args.command == "run" and any(r["state"] != "succeeded" for r in report) else 0
    except Exception:
        print(json.dumps({"error": "ingest_job_operation_failed", "command": args.command}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

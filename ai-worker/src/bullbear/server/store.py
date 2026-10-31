"""Durable HTTP event log. One worker process owns this directory at a time."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from ..snapshot import KST
from .errors import ApiError


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        # A separate SQLite database is used only as a cross-process ownership lock.
        self.owner = sqlite3.connect(directory / "owner.sqlite3", timeout=0, check_same_thread=False)
        try:
            self.owner.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            self.owner.close()
            raise RuntimeError("같은 데이터 디렉터리는 워커 프로세스 하나만 사용할 수 있습니다 (--workers 1)") from None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "worker.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS debates (
                id TEXT PRIMARY KEY, ticker TEXT NOT NULL, data_date TEXT NOT NULL,
                snapshot_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, debate_id TEXT NOT NULL REFERENCES debates(id));
            CREATE TABLE IF NOT EXISTS events (
                debate_id TEXT NOT NULL REFERENCES debates(id), seq INTEGER NOT NULL,
                type TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(debate_id, seq));
            CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        # Existing databases and their request fingerprints remain valid.
        if 'mode' not in {row['name'] for row in self.db.execute('PRAGMA table_info(debates)')}:
            with self.db:
                self.db.execute("ALTER TABLE debates ADD COLUMN mode TEXT NOT NULL DEFAULT 'debate'")
        for row in self.db.execute("SELECT id FROM debates WHERE status='running'").fetchall():
            self.emit(row['id'], 'debate_failed', {
                'error': {'code': 'LLM_ERROR', 'message': '워커 재시작으로 토론이 중단되었습니다. 새 요청으로 재시도하세요.'}})

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def close(self):
        self.db.close()
        self.owner.close()

    def request(self, request_id, fingerprint):
        with self.lock:
            row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if row is None:
                return None
            if row['fingerprint'] != fingerprint:
                raise ApiError(409, 'INVALID_REQUEST', 'request_id를 다른 요청 본문에 재사용할 수 없습니다')
            return self.get(row['debate_id'])

    def create(self, request_id, fingerprint, ticker, data_date, max_running, *, mode='debate', snapshot_id=None):
        with self.transaction() as db:
            prior = self.request(request_id, fingerprint)
            if prior:
                return prior, True
            selector, values = ('snapshot_id=?', (snapshot_id,)) if snapshot_id else (
                'ticker=? AND data_date=?', (ticker, data_date))
            row = db.execute(f"SELECT * FROM debates WHERE {selector} AND mode=? AND status IN ('running','completed') ORDER BY created_at DESC LIMIT 1",
                             (*values, mode)).fetchone()
            reused = row is not None
            if row is None:
                if db.execute("SELECT count(*) FROM debates WHERE status='running'").fetchone()[0] >= max_running:
                    raise ApiError(429, 'BUSY', '동시 토론 한도에 도달했습니다')
                debate_id = uuid4().hex
                db.execute("INSERT INTO debates (id,ticker,data_date,snapshot_id,status,created_at,mode) VALUES (?,?,?,?,'running',?,?)",
                           (debate_id, ticker, data_date, snapshot_id, datetime.now(KST).isoformat(), mode))
            else:
                debate_id = row['id']
            db.execute('INSERT INTO requests VALUES (?,?,?)', (request_id, fingerprint, debate_id))
            return self.get(debate_id), reused

    def get(self, debate_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM debates WHERE id=?', (debate_id,)).fetchone()
            if row is None:
                raise ApiError(404, 'NOT_FOUND', '토론을 찾을 수 없습니다')
            return dict(row)

    def snapshot(self, snapshot_id):
        with self.lock:
            row = self.db.execute('SELECT data FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
            if row is None:
                raise ApiError(404, 'NOT_FOUND', '스냅샷을 찾을 수 없습니다')
            return json.loads(row[0])

    def save_snapshot(self, debate_id, snapshot):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?)', (snapshot.snapshot_id, snapshot.model_dump_json()))
            db.execute('UPDATE debates SET snapshot_id=? WHERE id=?', (snapshot.snapshot_id, debate_id))

    def emit(self, debate_id, event, data):
        encoded = json.dumps(jsonable_encoder(data), ensure_ascii=False, allow_nan=False)
        with self.transaction() as db:
            if self.get(debate_id)['status'] != 'running':
                return
            seq = db.execute('SELECT coalesce(max(seq),0)+1 FROM events WHERE debate_id=?', (debate_id,)).fetchone()[0]
            db.execute('INSERT INTO events VALUES (?,?,?,?)', (debate_id, seq, event, encoded))
            if event in ('debate_completed', 'debate_failed'):
                db.execute('UPDATE debates SET status=? WHERE id=?',
                           ('completed' if event == 'debate_completed' else 'failed', debate_id))

    def events(self, debate_id, after=0):
        with self.lock:
            return [dict(row) for row in self.db.execute(
                'SELECT seq,type,data FROM events WHERE debate_id=? AND seq>? ORDER BY seq', (debate_id, after))]

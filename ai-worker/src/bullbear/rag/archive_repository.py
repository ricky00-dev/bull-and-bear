"""PostgreSQL archive using the same domain rules as the SQLite archive.

The internal SQL bridge accepts only the project's static qmark queries. It is
not a general SQLite emulator. FTS5 remains a derived, immutable local index.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

from .context_repository import ContextStorageError
from .objects import CachedObjectStore, LocalObjectStore, S3ObjectStore
from .store import RagStore

ARCHIVE_LOCK = 7348201102


class _Row(tuple):
    def __new__(cls, names, values):
        obj = super().__new__(cls, values)
        obj.names = names
        return obj

    def keys(self):
        return self.names

    def __getitem__(self, key):
        return super().__getitem__(self.names.index(key) if isinstance(key, str) else key)


class _Result:
    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        names = [column.name for column in cursor.description] if cursor.description else []
        self.rows = iter([_Row(names, row) for row in cursor.fetchall()] if names else [])

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


def _sql(query):
    if query == "PRAGMA busy_timeout=1":
        return "SET lock_timeout = '1ms'"
    if query == "PRAGMA defer_foreign_keys=ON":
        return "SET CONSTRAINTS ALL DEFERRED"
    if query == "BEGIN IMMEDIATE":
        return "BEGIN"
    if query.startswith("INSERT OR IGNORE INTO "):
        query = query.replace("INSERT OR IGNORE INTO ", "INSERT INTO ", 1) + " ON CONFLICT DO NOTHING"
    # Only static repository SQL is accepted. Values always remain parameters.
    return query.replace("?", "%s")


class _Connection:
    def __init__(self, dsn, *, reader=False):
        try:
            import psycopg
        except ImportError:
            raise ContextStorageError("install the rag-postgres optional dependencies") from None
        self.driver_error = psycopg.Error
        self.progress = None
        try:
            self.raw = psycopg.connect(dsn, autocommit=True, connect_timeout=3,
                options="-c search_path=rag,pg_catalog -c statement_timeout=10000 -c lock_timeout=3000")
            self.raw.execute("SET default_transaction_isolation = 'repeatable read'" if reader
                             else "SET default_transaction_isolation = 'read committed'")
            if reader:
                self.raw.execute("SET default_transaction_read_only = on")
                self.raw.execute("SET statement_timeout = '1000ms'")
        except psycopg.Error:
            if hasattr(self, "raw"):
                self.raw.close()
            raise ContextStorageError("archive connection failed") from None

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != 0

    def set_progress_handler(self, callback, _steps):
        self.progress = callback

    def execute(self, query, params=()):
        if self.progress and query not in {"COMMIT", "ROLLBACK"} and self.progress():
            raise TimeoutError("search deadline")
        try:
            with self.raw.cursor() as cursor:
                cursor.execute(_sql(query), params)
                return _Result(cursor)
        except self.driver_error:
            raise ContextStorageError("archive database operation failed") from None

    def executemany(self, query, params):
        try:
            with self.raw.cursor() as cursor:
                cursor.executemany(_sql(query), params)
                return _Result(cursor)
        except self.driver_error:
            raise ContextStorageError("archive database operation failed") from None

    def close(self):
        self.raw.close()


class PostgresArchive(RagStore):
    def __init__(self, directory, dsn, *, object_store=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.objects = self.directory / "objects"
        self.object_store = object_store if object_store is not None else LocalObjectStore(self.objects)
        self._dsn = dsn
        self.lock = threading.RLock()
        self.db = _Connection(dsn)

    def open_reader(self):
        return _Connection(self._dsn, reader=True)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN")
            try:
                # Domain decisions (current revision, initial review, watermark)
                # must serialize across writer processes, not just Python threads.
                self.db.execute("SELECT pg_advisory_xact_lock(?)", (ARCHIVE_LOCK,))
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    @contextmanager
    def _read_snapshot(self):
        with self.lock:
            own = not self.db.in_transaction
            if own:
                self.db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                yield
                if own:
                    self.db.execute("COMMIT")
            except BaseException:
                if own:
                    self.db.execute("ROLLBACK")
                raise


def configured_objects(settings, directory):
    if settings.rag_object_backend == "local":
        return LocalObjectStore(Path(directory) / "objects")
    if settings.rag_object_backend == "s3":
        return CachedObjectStore(S3ObjectStore(settings.rag_s3_bucket, prefix=settings.rag_s3_prefix,
                             endpoint_url=settings.rag_s3_endpoint), Path(directory) / "cache" / "objects")
    raise ValueError("unsupported object backend")


def configured_archive(settings, directory=None):
    directory = directory if directory is not None else settings.data_dir / "rag"
    if settings.rag_archive_backend not in {"sqlite", "postgres"}:
        raise ValueError("unsupported archive backend")
    if settings.rag_archive_backend == "postgres" and not settings.rag_postgres_dsn:
        raise ValueError("missing archive DSN")
    objects = configured_objects(settings, directory)
    if settings.rag_archive_backend == "postgres":
        return PostgresArchive(directory, settings.rag_postgres_dsn, object_store=objects)
    return RagStore(directory, object_store=objects)

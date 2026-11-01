"""Explicit schema migration and read-only SQLite context import. No provider/model calls."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .context_repository import (PostgresContextRepository,
                                 checked_context, prepare)
from .schemas import canonical_json, digest
from .store import ArchiveCorruptError


def migrate(dsn: str) -> None:
    """Alembic owns only RAG tables; runtime readers/writers do not run DDL."""
    import psycopg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    # DSN is never stored in Alembic config/logging or parsed through % interpolation.
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn, connect_timeout=3), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3000ms'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '30000ms'")
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(7348201101)")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def read_sqlite_contexts(path: Path) -> dict:
    """Pin one SQLite read transaction; reject corruption before touching destination.

    First-week importer holds the context archive in memory. Large archive streaming
    requires staging validation and is not silently approximated by partial commits.
    """
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ArchiveCorruptError("source database integrity check failed")
        contexts = [list(row) for row in db.execute("SELECT id,payload FROM contexts ORDER BY id")]
        searches = [list(row) for row in db.execute("SELECT id,context_id,payload FROM searches ORDER BY rowid")]
        by_id = {key: checked_context(key, payload) for key, payload in contexts}
        for attempt_id, context_id, payload in searches:
            if context_id not in by_id:
                raise ArchiveCorruptError("orphan retrieval audit")
            audit = json.loads(payload)
            _, normalized = prepare(by_id[context_id], audit, attempt_id)
            if normalized != payload:
                raise ArchiveCorruptError("audit is not canonical JSON")
        db.rollback()
    data = {"contexts": contexts, "searches": searches}
    return {**data, "source_hash": digest(data)}


def import_sqlite_contexts(path: Path, repository: PostgresContextRepository, *, dry_run=False) -> dict:
    data = read_sqlite_contexts(path)
    report = {"source_hash": data["source_hash"], "contexts": len(data["contexts"]),
              "searches": len(data["searches"]), "dry_run": dry_run}
    if dry_run:
        return report
    # A conflicting existing ID aborts the entire import. No overwrite/upsert update.
    with repository._connection() as db:
        # Import is an explicit maintenance operation. Prevent a live writer from
        # interleaving historical attempts and changing their original order.
        db.execute("LOCK TABLE rag.contexts, rag.searches IN SHARE ROW EXCLUSIVE MODE")
        source_attempts = {}
        for attempt_id, context_id, _ in data["searches"]:
            source_attempts.setdefault(context_id, []).append(attempt_id)
        for context_id, payload in data["contexts"]:
            existing = [row[0] for row in db.execute(
                "SELECT id FROM rag.searches WHERE context_id=%s ORDER BY seq", (context_id,))]
            source = source_attempts.get(context_id, [])
            if existing != source[:len(existing)]:
                raise ArchiveCorruptError("destination audit history conflict")
            db.execute("INSERT INTO rag.contexts(id,payload) VALUES (%s,%s) ON CONFLICT DO NOTHING", (context_id, payload))
            if db.execute("SELECT payload FROM rag.contexts WHERE id=%s", (context_id,)).fetchone()[0] != payload:
                raise ArchiveCorruptError("destination context conflict")
        for attempt_id, context_id, payload in data["searches"]:
            db.execute("INSERT INTO rag.searches(id,context_id,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                       (attempt_id, context_id, payload))
            if db.execute("SELECT context_id,payload FROM rag.searches WHERE id=%s", (attempt_id,)).fetchone() != (context_id, payload):
                raise ArchiveCorruptError("destination audit conflict")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    command = sub.add_parser("import-contexts")
    command.add_argument("source", type=Path, help="existing contexts.sqlite3, read-only")
    command.add_argument("--dry-run", action="store_true")
    for name in ("import-archive", "copy-objects"):
        command = sub.add_parser(name)
        command.add_argument("source", type=Path, help="existing rag.sqlite3, read-only")
        command.add_argument("--dry-run", action="store_true")
    for name in ("push-generation", "fetch-generation"):
        command = sub.add_parser(name)
        command.add_argument("generation_id")
    replay = sub.add_parser("replay")
    replay.add_argument("context_id")
    args = parser.parse_args(argv)
    try:
        dry_run = getattr(args, "dry_run", False)
        dsn = os.getenv("BULLBEAR_RAG_POSTGRES_DSN", "")
        if not dry_run and args.command != "copy-objects" and not dsn.strip():
            raise ValueError("missing DSN")
        if args.command == "migrate":
            migrate(dsn)
            report = {"schema": "rag", "migration": "head", "status": "completed"}
        elif args.command == "import-contexts":
            report = import_sqlite_contexts(args.source, PostgresContextRepository(dsn) if not dry_run else None,
                                            dry_run=dry_run)
        elif args.command in {"import-archive", "copy-objects"}:
            from ..config import load_settings
            from .archive_repository import PostgresArchive, configured_objects
            from .archive_transfer import import_archive, copy_objects
            settings = load_settings()
            if dry_run:
                report = import_archive(args.source, dry_run=True)
            else:
                objects = configured_objects(settings, settings.data_dir / "rag")
                if args.command == "copy-objects":
                    report = copy_objects(args.source, objects)
                else:
                    with PostgresArchive(settings.data_dir / "rag", dsn, object_store=objects) as archive:
                        report = import_archive(args.source, archive)
        elif args.command in {"push-generation", "fetch-generation"}:
            from ..config import load_settings
            from .archive_repository import PostgresArchive, configured_objects
            from .generation_transfer import push_generation, fetch_generation
            settings = load_settings()
            with PostgresArchive(settings.data_dir / "rag", dsn,
                    object_store=configured_objects(settings, settings.data_dir / "rag")) as archive:
                operation = push_generation if args.command == "push-generation" else fetch_generation
                report = operation(archive, args.generation_id)
        else:
            context = PostgresContextRepository(dsn).load(args.context_id)
            report = {"context_id": context.context_id, "payload": context.payload}
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception:
        # Driver/Alembic/OS messages can contain a DSN or private payload. CLI is
        # deliberately bounded; failures exit nonzero and preserve source data.
        print(json.dumps({"error": "rag_storage_operation_failed", "command": args.command}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

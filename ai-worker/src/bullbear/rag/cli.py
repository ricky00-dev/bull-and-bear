"""Local-only CLI: bullbear rag import/sync/inspect; never calls data providers."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..config import load_settings
from .ingest import import_payload, sync_payload
from .store import ArchiveCorruptError, RagStore
from .archive_repository import configured_archive
from .objects import ObjectStorageError
from .context_repository import ContextStorageError, configured_repository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bullbear rag")
    parser.add_argument("--data-dir", type=Path, help="worker data directory; archive is stored under rag/")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "sync"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path, help="local UTF-8 JSON capture; no HTTP fetch")
    inspect = sub.add_parser("inspect")
    group = inspect.add_mutually_exclusive_group()
    group.add_argument("--document")
    group.add_argument("--collection")
    inspect.add_argument("--at", type=datetime.fromisoformat, help="timezone-aware decision time required with --document")
    publish = sub.add_parser("publish")
    publish.add_argument("--as-of", required=True, type=datetime.fromisoformat)
    readiness = sub.add_parser("check-generation", help="verify publication before collecting snapshots; no network")
    readiness.add_argument("--generation", required=True)
    readiness.add_argument("--snapshot", type=Path, action="append", default=[])
    bind = sub.add_parser('bind-snapshot', help='offline legacy migration from a saved observed context; worker must be stopped')
    bind.add_argument('--snapshot-id', required=True)
    bind.add_argument('--context-id', required=True)
    bind.add_argument('--apply', action='store_true', help='persist immutable binding; default validates only')
    sub.add_parser('check-bindings', help='offline snapshot/publication inventory; worker must be stopped')
    search = sub.add_parser("retrieve")
    search.add_argument("snapshot", type=Path)
    search.add_argument("--generation", help="required for document search; unused for structured facts")
    search.add_argument("--strategy", choices=("bm25", "dense", "hybrid"), default="bm25")
    search.add_argument("--embedding-spec", type=Path)
    search.add_argument("--selection-policy", type=Path)
    search.add_argument("--request", type=Path, help="Explicit mode=documents or mode=facts JSON")
    search.add_argument("--reconstructed", action="store_true", help="explicit historical evaluation, not observed operation")
    replay = sub.add_parser("replay")
    replay.add_argument("context_id")
    args = parser.parse_args(argv)
    if args.command == "inspect" and bool(args.document) != bool(args.at):
        parser.error("--document and --at must be used together")
    try:
        directory = (args.data_dir if args.data_dir is not None else load_settings().data_dir) / "rag"
        with configured_archive(load_settings(), directory) as store:
            if args.command in {'bind-snapshot', 'check-bindings'}:
                from ..server.store import Store
                from .binding import migrate_binding, check_bindings
                from .replay import load_context
                from contextlib import closing
                if not (directory.parent / 'http' / 'worker.sqlite3').is_file():
                    raise ValueError('existing HTTP store required')
                apply = args.command == 'bind-snapshot' and args.apply
                with closing(Store(directory.parent / 'http', maintenance=True, read_only=not apply)) as worker:
                    if args.command == 'check-bindings':
                        report = check_bindings(worker, store)
                        print(json.dumps(report, ensure_ascii=False))
                        return 0 if report['all_ready'] else 1
                    context = load_context(store, args.context_id, repository=configured_repository(load_settings()))
                    binding = migrate_binding(worker, store, args.snapshot_id, context, apply=args.apply)
                print(json.dumps({'applied': args.apply, 'binding': binding}, ensure_ascii=False))
                return 0
            if args.command == "check-generation":
                from .readiness import check_generation
                from ..snapshot import Snapshot
                snapshots = [Snapshot.model_validate_json(path.read_text(encoding='utf-8')) for path in args.snapshot]
                report = check_generation(store, args.generation, snapshots=snapshots)
                print(json.dumps(report, ensure_ascii=False))
                return 0 if report['ready_for_new_snapshot'] and report['all_snapshots_eligible'] else 1
            if args.command == "publish":
                from .index import GenerationIndex
                print(json.dumps({"generation_id": GenerationIndex(store).publish(args.as_of)}))
                return 0
            if args.command in {"retrieve", "replay"}:
                from .retrieval import Retriever
                from ..snapshot import Snapshot
                repository = configured_repository(load_settings())
                options = {}
                if args.command == "retrieve" and args.strategy != "bm25":
                    from .vector_cli import cached_index
                    settings = load_settings()
                    if not args.embedding_spec or not settings.rag_postgres_dsn:
                        raise ValueError("embedding spec and PostgreSQL DSN required")
                    options = {"strategy": args.strategy, "vector_index": cached_index(settings.rag_postgres_dsn, args.embedding_spec)}
                if args.command == "retrieve" and args.selection_policy:
                    from .selection import SelectionPolicy
                    options["selection_policy"] = SelectionPolicy.model_validate_json(args.selection_policy.read_text(encoding="utf-8"))
                retriever = Retriever(store, context_repository=repository, **options)
                if args.command == "replay":
                    context = retriever.load_context(args.context_id)
                else:
                    snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
                    request = None
                    if args.request:
                        from .evidence import REQUEST_ADAPTER
                        request = REQUEST_ADAPTER.validate_json(args.request.read_text(encoding="utf-8"))
                    if not args.generation and (request is None or request.mode != 'facts'):
                        raise ValueError('document search requires a generation')
                    context = retriever.retrieve(snapshot, generation_id=args.generation or '', request=request,
                                                time_policy="reconstructed-v1" if args.reconstructed else "observed-v1")
                print(json.dumps({"context_id": context.context_id, "payload": context.payload}, ensure_ascii=False))
                return 0 if context.payload["status"] in {"completed", "empty"} else 1
            if args.command in {"import", "sync"}:
                payload = json.loads(args.input.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("collection must be a JSON object")
                result = (import_payload if args.command == "import" else sync_payload)(store, payload)
                print(result.model_dump_json())
                return 1 if result.status in {"failed", "partial"} else 0
            if args.document:
                output = store.document_at(args.document, args.at)
            elif args.collection:
                output = store.collection(args.collection)
                if output:
                    output = {k: v for k, v in output.items() if k not in {"input_json", "fingerprint"}}
            else:
                output = store.counts()
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ValidationError, sqlite3.Error, ArchiveCorruptError, ContextStorageError, ObjectStorageError):
        # Never echo provider payloads, credentials, local paths or request details.
        print("오류: invalid_archive_input_or_storage", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

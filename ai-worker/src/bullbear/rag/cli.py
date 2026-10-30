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
    search = sub.add_parser("retrieve")
    search.add_argument("snapshot", type=Path)
    search.add_argument("--generation", required=True)
    search.add_argument("--reconstructed", action="store_true", help="explicit historical evaluation, not observed operation")
    replay = sub.add_parser("replay")
    replay.add_argument("context_id")
    args = parser.parse_args(argv)
    if args.command == "inspect" and bool(args.document) != bool(args.at):
        parser.error("--document and --at must be used together")
    try:
        directory = (args.data_dir if args.data_dir is not None else load_settings().data_dir) / "rag"
        with RagStore(directory) as store:
            if args.command == "publish":
                from .index import GenerationIndex
                print(json.dumps({"generation_id": GenerationIndex(store).publish(args.as_of)}))
                return 0
            if args.command in {"retrieve", "replay"}:
                from .retrieval import Retriever
                from ..snapshot import Snapshot
                retriever = Retriever(store)
                if args.command == "replay":
                    context = retriever.load_context(args.context_id)
                else:
                    snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
                    context = retriever.retrieve(snapshot, generation_id=args.generation,
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
    except (OSError, ValueError, TypeError, KeyError, ValidationError, sqlite3.Error, ArchiveCorruptError):
        # Never echo provider payloads, credentials, local paths or request details.
        print("오류: invalid_archive_input_or_storage", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

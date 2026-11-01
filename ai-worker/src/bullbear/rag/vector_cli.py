"""Explicit embedding preparation and cache-only vector comparison. S3 is not required."""
import argparse
import json
from pathlib import Path

from ..config import load_settings
from ..snapshot import Snapshot
from .archive_repository import configured_archive
from .context_repository import PostgresContextRepository
from .embeddings import EmbeddingService, EmbeddingSpec, OpenAIEmbeddings
from .selection import SelectionPolicy, query_text
from .vectors import VectorIndex, install_vectors


def cached_index(dsn, spec_path):
    spec = EmbeddingSpec.model_validate_json(Path(spec_path).read_text(encoding="utf-8"))
    return VectorIndex(EmbeddingService(dsn, spec))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    for command in ("build", "prepare-query", "compare", "ledger"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--spec", type=Path, required=True)
        if command in {"build", "compare"}:
            cmd.add_argument("--generation", required=True)
        if command in {"build", "prepare-query"}:
            cmd.add_argument("--daily-budget-nano", type=int, required=True, help="USD nanodollars, 1 USD = 1000000000")
        cmd.add_argument("--selection-policy", type=Path)
        if command == "prepare-query":
            cmd.add_argument("snapshot", type=Path)
        if command == "compare":
            cmd.add_argument("cases", type=Path)
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--time-policy", choices=("observed-v1", "reconstructed-v1"), default="reconstructed-v1")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        if not settings.rag_postgres_dsn:
            raise ValueError("missing DSN")
        if args.command == "install":
            install_vectors(settings.rag_postgres_dsn)
            report = {"status": "installed", "search": "exact_pgvector"}
        else:
            index = cached_index(settings.rag_postgres_dsn, args.spec)
            policy = SelectionPolicy.model_validate_json(args.selection_policy.read_text(encoding="utf-8")) if args.selection_policy else None
            if policy and policy.embedding_version != index.version_id:
                raise ValueError("selection policy embedding version mismatch")
            if args.command in {"build", "prepare-query"}:
                if index.embeddings.spec.provider != "openai":
                    raise ValueError("fixture embeddings are test-only")
                index.embeddings.provider = OpenAIEmbeddings()
            if args.command == "prepare-query":
                snapshot = Snapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
                key, _ = index.embeddings.prepare(query_text(snapshot, policy), "query", daily_budget_nano=args.daily_budget_nano)
                report = {"query_embedding_id": key, "version_id": index.version_id}
            elif args.command == "ledger":
                report = index.embeddings.ledger()
            else:
                with configured_archive(settings) as store:
                    if args.command == "build":
                        report = {"vector_generation_id": index.build(store, args.generation, daily_budget_nano=args.daily_budget_nano)}
                    else:
                        from .vector_evaluation import ComparisonCase, compare
                        cases = [ComparisonCase.model_validate(c) for c in json.loads(args.cases.read_text(encoding="utf-8"))]
                        report = compare(store, index, args.generation, cases,
                            context_repository=PostgresContextRepository(settings.rag_postgres_dsn), time_policy=args.time_policy, selection_policy=policy)
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report = {"result": report}
        print(json.dumps(report, ensure_ascii=False))
        if args.command == "compare":
            return int(any(v["failures"] or v["forbidden_hits"] or v["unexpected_answers"]
                           for v in report["result"]["summary"].values()))
        return 0
    except Exception:
        print(json.dumps({"error": "vector_operation_failed", "command": args.command}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

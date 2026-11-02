"""Explicit paid pilot against an agent-reviewed corpus; never an operational enable switch."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..snapshot import Fact, Snapshot
from .context_repository import PostgresContextRepository
from .corpus import Corpus, import_corpus
from .embeddings import EmbeddingService, EmbeddingSpec, OpenAIEmbeddings
from .index import GenerationIndex
from .retrieval import query_terms
from .schemas import digest
from .store import RagStore
from .vector_evaluation import ComparisonCase, compare
from .vectors import VectorIndex


def run_pilot(dsn, corpus_path, cases_path, output, specs, *, budget_nano):
    corpus = Corpus.model_validate_json(corpus_path.read_text(encoding="utf-8"))
    dataset = json.loads(cases_path.read_text(encoding="utf-8"))
    rows = dataset["cases"]
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("empty or duplicate evaluation cases")
    if any(r["path"] not in {"common", "short"}
           or (r["expect_empty"] and r["relevant"])
           or len(set(r["relevant"])) != len(r["relevant"]) for r in rows):
        raise ValueError("invalid evaluation judgments")
    if not specs or budget_nano < 0:
        raise ValueError("specs and a nonnegative budget are required")
    output.mkdir(parents=True, exist_ok=True)
    state_file = output / "pilot-state.json"
    inputs = {"corpus_hash": digest(corpus.model_dump(mode="json")), "dataset_hash": digest(dataset)}
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if any(state[k] != v for k, v in inputs.items()):
            raise ValueError("pilot input changed; use a new output directory")
    else:
        state = {**inputs, "observed_at": datetime.now(timezone.utc).isoformat()}
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    observed = datetime.fromisoformat(state["observed_at"])
    with RagStore(output / "archive") as store:
        imported = import_corpus(store, corpus, allow_agent_reviewed=True, observed_at=observed)
        lookup = {row["id"]: row["chunk_id"] for row in imported["notes"]}
        generation = GenerationIndex(store).publish(observed)
        cases = []
        for row in dataset["cases"]:
            fact = Fact(id="EVAL.PROBE", category="valuation", label=row["label"], value=None,
                        unit="text", as_of=observed.date(), source="agent_authored_evaluation")
            snapshot = Snapshot(snapshot_id="EVAL." + digest([inputs, row["id"], state["observed_at"]]),
                ticker="005930", name="평가종목", as_of=observed.date(), created_at=observed,
                provider="synthetic_concept_probe", facts={fact.id: fact})
            cases.append(ComparisonCase(id=row["id"], snapshot=snapshot, path=row["path"],
                relevant=[lookup[key] for key in row["relevant"]], expect_empty=row["expect_empty"]))
        # Refuse the complete planned run before its first request if it exceeds the budget.
        db, manifest = GenerationIndex(store).open(generation)
        db.close()
        upper = sum((sum(len((s.document_prefix + m["text"]).encode("utf-8")) for m in manifest["members"]) +
                     sum(len((s.query_prefix + " ".join(query_terms(c.snapshot))).encode("utf-8")) for c in cases))
                    * s.nano_usd_per_token for s in specs)
        if upper > budget_nano:
            raise ValueError("planned token upper bound exceeds pilot budget")
        summary = {**state, "generation_id": generation, "human_reviewed": False,
            "evidence_type": "real_embedding_models_agent_authored_small_corpus_probe",
            "budget_nano": budget_nano, "planned_upper_bound_nano": upper,
            "documents": len(manifest["members"]), "cases": len(cases), "models": []}
        (output / "cases.json").write_text(json.dumps([c.model_dump(mode="json") for c in cases], ensure_ascii=False, indent=2), encoding="utf-8")
        for spec in specs:
            service = EmbeddingService(dsn, spec, OpenAIEmbeddings())
            index = VectorIndex(service)
            try:
                index.build(store, generation, daily_budget_nano=budget_nano)
                for case in cases:
                    service.prepare(" ".join(query_terms(case.snapshot)), "query", daily_budget_nano=budget_nano)
                report = compare(store, index, generation, cases, context_repository=PostgresContextRepository(dsn))
                # Exhaustive labels are agent judgments, and apply to the whole selected bundle.
                gold = {c.id: set(c.relevant) for c in cases}
                for result in report["results"]:
                    context = PostgresContextRepository(dsn).load(result["context_id"]).payload
                    selected = {m["chunk_id"] for m in context["items"]}
                    result["unnecessary_selected"] = len(selected - gold[result["case_id"]])
                    result["selected_precision"] = len(selected & gold[result["case_id"]]) / len(selected) if selected else None
                report["embedding_spec"] = spec.model_dump(mode="json")
                report["evidence_type"] = summary["evidence_type"]
                report["human_reviewed"] = False
                (output / (spec.model + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                summary["models"].append({"spec": spec.model_dump(mode="json"), "status": "completed", "summary": report["summary"]})
            except Exception:
                summary["models"].append({"spec": spec.model_dump(mode="json"), "status": "failed_or_unknown"})
                summary["ledger"] = service.ledger()
                (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                raise
            finally:
                if service.provider.client is not None:
                    service.provider.client.close()
            summary["ledger"] = service.ledger()
            (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--spec", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-nano", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        specs = [EmbeddingSpec.model_validate_json(p.read_text(encoding="utf-8")) for p in args.spec]
        if any(s.provider != "openai" or s.nano_usd_per_token <= 0 for s in specs):
            raise ValueError("explicit real API specs and prices required")
        result = run_pilot(os.environ["BULLBEAR_RAG_POSTGRES_DSN"], args.corpus, args.cases, args.output, specs, budget_nano=args.budget_nano)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"error": "embedding_pilot_failed", "inspect": "private ledger and pilot summary"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

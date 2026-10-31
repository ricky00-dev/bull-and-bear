"""Offline retrieval quality evaluation; never calls providers or evaluates returns.

Questions are synthetic Snapshot concept-label probes, not a new user-question API.
Ranks are scored separately per retrieval path: cross-path BM25 is never compared.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..snapshot import Fact, Snapshot
from .index import GenerationIndex
from .replay import retrieval_audits
from .retrieval import POLICY_VERSION, Retriever
from .schemas import AnnotationInput, ChunkInput, CollectionBatch, DocumentInput, canonical_json, digest, utc
from .store import RagStore


class FixtureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    text: str = Field(min_length=1)
    horizons: list[Literal["common", "short", "medium", "long"]] = ["common"]
    markets: list[str] = ["KR"]
    tickers: list[str] = []
    kind: Literal["knowledge", "research", "news"] = "knowledge"
    observed_hours: int = -24
    published_hours: int = -48
    review_status: Literal["approved", "rejected"] = "approved"
    basis_urls: list[str] = []


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    description: str
    concept_label: str
    path: Literal["common", "short"] = "common"
    relevant: list[str] = []
    forbidden: list[str] = []
    generation_mode: Literal["ready", "missing"] = "ready"
    relevance_scope: Literal["exhaustive", "subset"] = "subset"


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["rag-search-evaluation-v1"]
    dataset_version: str
    evidence_type: Literal["synthetic_not_human_reviewed"]
    as_of: datetime
    ticker: str = "000000"
    documents: list[FixtureDocument] = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        utc(self.as_of)
        keys = [d.key for d in self.documents]
        if len(keys) != len(set(keys)) or len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("duplicate document/case IDs")
        for case in self.cases:
            if len(case.relevant) != len(set(case.relevant)) or len(case.forbidden) != len(set(case.forbidden)):
                raise ValueError("duplicate judgments")
            if not set(case.relevant + case.forbidden) <= set(keys):
                raise ValueError("judgment references unknown document")
            if set(case.relevant) & set(case.forbidden):
                raise ValueError("relevant and forbidden overlap")
        return self


def score_ranking(ranked: list[str], relevant: list[str], k: int = 20) -> dict:
    """No-positive queries have undefined recall/MRR, not perfect relevance scores."""
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and the per-path candidate limit 20")
    ranked = list(dict.fromkeys(ranked))[:k]
    gold = set(relevant)
    hits = [i for i, key in enumerate(ranked, 1) if key in gold]
    return {"recall_at_k": len(set(ranked) & gold) / len(gold) if gold else None,
            "reciprocal_rank_at_k": 1 / hits[0] if hits else (0.0 if gold else None)}


def score_selection(selected: list[str], relevant: list[str], *, exhaustive: bool) -> dict:
    """Only exhaustive judgments can classify unlisted selections as unnecessary.

    Scope covers the entire selected common/short bundle, not only one path.
    Empty selection has no precision denominator; its unnecessary count is zero.
    """
    if not exhaustive:
        return {"selected_precision": None, "unnecessary_selected_count": None}
    keys, gold = set(selected), set(relevant)
    return {"selected_precision": len(keys & gold) / len(keys) if keys else None,
            "unnecessary_selected_count": len(keys - gold)}


def _seed(store: RagStore, dataset: EvaluationDataset) -> dict[str, str]:
    lookup = {}
    for row in dataset.documents:
        observed = dataset.as_of + timedelta(hours=row.observed_hours)
        published = dataset.as_of + timedelta(hours=row.published_hours)
        doc = DocumentInput(source="synthetic-rag-evaluation", source_item_id=row.key,
                            source_ref=row.key, kind=row.kind, url=f"https://example.invalid/{digest(row.key)}",
                            title="평가용 문단", text=row.text, content_level="full_text",
                            observed_at=observed, published_at=published,
                            timestamp_precision="instant", publication_verified=True,
                            metadata={"evidence_type": dataset.evidence_type,
                                      "simulated_publication_not_source_timestamp": True,
                                      "basis_urls": row.basis_urls})
        store.import_collection(CollectionBatch(
            collection_id=row.key, source=doc.source, query_key="evaluation", window_start=published,
            window_end=max(published, observed), started_at=observed, finished_at=observed,
            observation_mode="current", status="completed", coverage="complete", pages=1, items=(doc,)))
        chunk = ChunkInput(revision_id=doc.revision_id, ordinal=0, text=row.text,
                           source_locator="synthetic-paragraph:1", chunker_version="evaluation-v1")
        store.add_chunk(chunk)
        store.annotate(AnnotationInput(chunk_id=chunk.chunk_id, horizons=tuple(row.horizons),
                                      markets=tuple(row.markets), tickers=tuple(row.tickers),
                                      review_status=row.review_status, created_at=observed, reviewed_at=observed,
                                      tagging_policy_version="synthetic-evaluation-v1"))
        lookup[chunk.chunk_id] = row.key
    return lookup


def _snapshot(dataset, case, dataset_hash):
    fact = Fact(id="EVAL.PROBE", category="valuation", label=case.concept_label, value=None,
                unit="text", as_of=dataset.as_of.date(), source="synthetic_concept_probe")
    return Snapshot(snapshot_id="EVAL." + digest([dataset_hash, case.id]), ticker=dataset.ticker,
                    name="평가종목", as_of=dataset.as_of.date(), created_at=dataset.as_of,
                    provider="synthetic_evaluation", facts={fact.id: fact})


def _percentile95(values):
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def evaluate(dataset: EvaluationDataset | dict, output: Path, *, k: int = 20) -> dict:
    dataset = EvaluationDataset.model_validate(dataset)
    score_ranking([], [], k)  # Validate before creating an output directory.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous run.
    dataset_payload = dataset.model_dump(mode="json")
    dataset_hash = digest(dataset_payload)
    (output / "dataset.json").write_text(canonical_json(dataset_payload), encoding="utf-8")
    results = []
    with RagStore(output / "archive") as store:
        lookup = _seed(store, dataset)
        generation = GenerationIndex(store).publish(dataset.as_of)
        docs = {d.key: d for d in dataset.documents}
        for case in dataset.cases:
            started = time.monotonic()
            row = {"case_id": case.id, "path": case.path, "relevant": case.relevant,
                   "generation_mode": case.generation_mode, "relevance_scope": case.relevance_scope}
            try:
                context = Retriever(store).retrieve(_snapshot(dataset, case, dataset_hash),
                    generation_id=generation if case.generation_mode == "ready" else "G." + "0" * 64,
                    time_policy="reconstructed-v1")
                payload = context.payload
                row.update(status=payload["status"], context_id=context.context_id,
                           query_terms=payload["query_terms"], warnings=payload.get("warnings", []))
                assert Retriever(store).load_context(context.context_id) == context
                row["search_seconds"] = retrieval_audits(store, context.context_id)[-1]["search_elapsed_seconds"]
                successful = payload["status"] in {"completed", "empty"}
                candidates = [lookup[c["chunk_id"]] for c in payload.get("candidates", []) if c["path"] == case.path]
                selected = [lookup[c["chunk_id"]] for c in payload["items"]]
                row.update(candidates=candidates[:k], selected=selected,
                           metrics=score_ranking(candidates, case.relevant, k) if successful else None,
                           selected_recall=(len(set(selected) & set(case.relevant)) / len(case.relevant)
                                            if successful and case.relevant else None),
                           false_positive=bool(selected) if successful and not case.relevant else None)
                row.update(score_selection(selected, case.relevant,
                                           exhaustive=successful and case.relevance_scope == "exhaustive"))
                # Independent fixture checks, not just the retriever's exclusion labels.
                selected_docs = [docs[key] for key in selected]
                row["violations"] = {
                    "time": sum(d.observed_hours > 0 or d.published_hours > 0 for d in selected_docs),
                    "market": sum(not set(d.markets) & {"KR", "KOSPI", "global"} for d in selected_docs),
                    "ticker": sum(bool(d.tickers) and dataset.ticker not in d.tickers for d in selected_docs),
                    "forbidden": len(set(selected) & set(case.forbidden)),
                }
            except Exception as exc:
                # Do not serialize exception text or turn operational failure into recall=0.
                row.update(status="exception", error_type=type(exc).__name__, metrics=None,
                           selected_recall=None, selected_precision=None, unnecessary_selected_count=None,
                           false_positive=None, violations=None)
            row["elapsed_including_persistence_seconds"] = time.monotonic() - started
            results.append(row)
            (output / "progress.json").write_text(canonical_json(results), encoding="utf-8")
    counts = Counter(row["status"] for row in results)
    scored = [r for r in results if r["metrics"] and r["metrics"]["recall_at_k"] is not None]
    negatives = [r for r in results if r["false_positive"] is not None]
    precision_scored = [r for r in results if r["selected_precision"] is not None]
    exhaustive_scored = [r for r in results if r["unnecessary_selected_count"] is not None]
    total_violations = {key: sum((r["violations"] or {}).get(key, 0) for r in results)
                        for key in ("time", "market", "ticker", "forbidden")}
    successful = counts["completed"] + counts["empty"]
    report = {"schema_version": "rag-search-evaluation-report-v1", "dataset_version": dataset.dataset_version,
              "dataset_hash": dataset_hash, "evidence_type": dataset.evidence_type, "generation_id": generation,
              "policy_version": POLICY_VERSION, "candidate_k_per_path": k,
              "attempts": len(results), "status_counts": dict(counts), "successful_searches": successful,
              "search_availability": successful / len(results),
              "positive_attempts": sum(bool(c.relevant) for c in dataset.cases), "scored_positive_queries": len(scored),
              "macro_recall_at_k_successful": sum(r["metrics"]["recall_at_k"] for r in scored) / len(scored) if scored else None,
              "mrr_at_k_successful": sum(r["metrics"]["reciprocal_rank_at_k"] for r in scored) / len(scored) if scored else None,
              "selected_recall_successful": sum(r["selected_recall"] for r in scored) / len(scored) if scored else None,
              "scored_selected_precision_queries": len(precision_scored),
              "selected_precision_successful": (sum(r["selected_precision"] for r in precision_scored) /
                                                len(precision_scored)) if precision_scored else None,
              "exhaustive_successful_queries": len(exhaustive_scored),
              "unnecessary_selected_count_successful": (sum(r["unnecessary_selected_count"] for r in exhaustive_scored)
                                                        if exhaustive_scored else None),
              "scored_negative_queries": len(negatives), "negative_false_positives": sum(r["false_positive"] for r in negatives),
              "violations": total_violations,
              "search_p95_seconds": _percentile95([r["search_seconds"] for r in results if "search_seconds" in r]),
              "total_p95_seconds": _percentile95([r["elapsed_including_persistence_seconds"] for r in results]),
              "cost_usd": None, "accuracy": None, "usage_status": "no_model_calls",
              "operational_activation_eligible": False, "results": results}
    report["quality_gate_passed"] = (successful == len(results) and bool(scored) and
        report["macro_recall_at_k_successful"] == 1 and report["selected_recall_successful"] == 1 and
        report["negative_false_positives"] == 0 and not any(total_violations.values()))
    (output / "report.json").write_text(canonical_json(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args(argv)
    dataset = EvaluationDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    report = evaluate(dataset, args.output, k=args.k)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    return 0 if report["quality_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Paired BM25/dense/RRF evaluation with fixed snapshots, generation and judgments."""
import math
import time

from pydantic import BaseModel, ConfigDict, Field

from ..snapshot import Snapshot
from .retrieval import Retriever
from .schemas import digest


class ComparisonCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    snapshot: Snapshot
    path: str = "common"
    relevant: list[str]
    forbidden: list[str] = []
    expect_empty: bool = False


def metrics(ranked, relevant, k):
    relevant = set(relevant)
    if not relevant:
        return {"recall": None, "mrr": None, "ndcg": None}
    hits = [i in relevant for i in ranked]
    dcg = sum(1 / math.log2(i + 2) for i, hit in enumerate(hits) if hit)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return {"recall": len(set(ranked) & relevant) / len(relevant),
            "mrr": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
            "ndcg": dcg / ideal if ideal else 0}


def bundle_summary(rows):
    """Precision excludes empty selections; missed answerable queries remain visible."""
    total = sum(len(r['bundle_selected']) for r in rows)
    unnecessary = sum(r['unnecessary_selected'] or 0 for r in rows)
    return {'bundle_micro_precision': (total - unnecessary) / total if total else None,
            'false_abstentions': sum(r['abstained'] is True and r['bundle_recall'] is not None for r in rows),
            'unnecessary_selected': unnecessary}


def compare(store, vector_index, generation_id, cases, *, context_repository, time_policy="reconstructed-v1", selection_policy=None):
    from .index import GenerationIndex
    db, manifest = GenerationIndex(store).open(generation_id)
    db.close()
    known = {m["chunk_id"] for m in manifest["members"]}
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("empty or duplicate evaluation cases")
    for case in cases:
        if (case.path not in {"common", "short"} or set(case.relevant) & set(case.forbidden)
                or (case.expect_empty and case.relevant)
                or not set(case.relevant) <= known or len(set(case.relevant)) != len(case.relevant)):
            raise ValueError("invalid evaluation judgments")
    results = []
    for case in cases:
        for strategy in ("bm25", "dense", "hybrid"):
            retriever = Retriever(store, strategy=strategy, vector_index=vector_index if strategy != "bm25" else None,
                                  context_repository=context_repository, selection_policy=selection_policy)
            started = time.perf_counter()
            context = retriever.retrieve(case.snapshot, generation_id=generation_id, time_policy=time_policy)
            elapsed = time.perf_counter() - started
            payload = context.payload
            ranked = [m["chunk_id"] for m in payload["items"] if m["path"] == case.path]
            valid = payload["status"] in {"completed", "empty"}
            scores = metrics(ranked, case.relevant, 2 if case.path == "common" else 3) if valid else {k: None for k in ("recall", "mrr", "ndcg")}
            results.append({"case_id": case.id, "strategy": strategy, "status": payload["status"],
                "context_id": context.context_id, "selected": ranked, "path": case.path,
                "k": 2 if case.path == "common" else 3, "cached_retrieval_seconds": elapsed,
                "forbidden_hits": len(set(case.forbidden) & {m["chunk_id"] for m in payload["items"]}),
                "candidate_count": len(payload.get("candidates", [])), **scores})
            bundle = {m["chunk_id"] for m in payload["items"]}
            gold = set(case.relevant)
            results[-1].update(bundle_selected=sorted(bundle),
                bundle_precision=len(bundle & gold) / len(bundle) if valid and bundle else None,
                bundle_recall=len(bundle & gold) / len(gold) if valid and gold else None,
                unnecessary_selected=len(bundle - gold) if valid else None,
                abstained=not bundle if valid else None)
            results[-1]["unexpected_answer"] = bool(case.expect_empty and bundle) if valid else None
    summaries = {}
    for strategy in ("bm25", "dense", "hybrid"):
        rows = [r for r in results if r["strategy"] == strategy]
        latencies = sorted(r["cached_retrieval_seconds"] for r in rows)
        summaries[strategy] = {
            "failures": sum(r["status"] not in {"completed", "empty"} for r in rows),
            "forbidden_hits": sum(r["forbidden_hits"] for r in rows),
            "unexpected_answers": sum(r["unexpected_answer"] is True for r in rows),
            "p95_cached_seconds": latencies[math.ceil(.95 * len(latencies)) - 1],
            **{name: (sum(r[name] for r in rows if r[name] is not None) / sum(r[name] is not None for r in rows)
                      if any(r[name] is not None for r in rows) else None) for name in ("recall", "mrr", "ndcg", "bundle_precision", "bundle_recall")},
            **bundle_summary(rows)}
    return {"schema": "rag-vector-comparison-v1", "generation_id": generation_id,
            "metric_scope": "whole_bundle_negative_and_precision_v2",
            "embedding_version": vector_index.version_id, "time_policy": time_policy,
            "selection_policy": selection_policy.model_dump(mode="json") if selection_policy else None,
            "judgments_hash": digest([c.model_dump(mode="json") for c in cases]),
            "latency_scope": "cached_search_and_context_persistence_excludes_embedding_and_index_build",
            "evidence_type": "caller_supplied_judgments_not_independently_reviewed",
            "summary": summaries, "results": results, "embedding_ledger": vector_index.embeddings.ledger()}

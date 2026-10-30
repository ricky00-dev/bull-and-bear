"""Source-grounded AI-authored notes; separate from synthetic tokenizer probes."""
import json
from datetime import timedelta

from bullbear.rag.corpus import import_corpus
from bullbear.rag.evaluation import score_ranking
from bullbear.rag.index import GenerationIndex
from bullbear.rag.replay import retrieval_audits
from bullbear.rag.retrieval import Retriever
from bullbear.rag.schemas import digest
from bullbear.rag.store import RagStore
from bullbear.snapshot import Fact, Snapshot
from .test_rag_corpus import corpus


CASES = [
    ("per", "common", "PER 주가수익비율", ["per-definition"]),
    ("margin", "common", "영업이익률", ["operating-margin"]),
    ("volatility", "common", "변동성은", ["volatility-direction"]),
    ("expectations", "short", "실적 발표 기대 차이", ["earnings-expectations"]),
    ("filing", "short", "공시 공개 시각", ["release-vs-filing"]),
    ("momentum", "short", "momentum 추세", ["momentum-limit"]),
    ("unrelated_common", "common", "광합성 식물세포", []),
    ("unrelated_short", "short", "광합성 식물세포", []),
]


def snapshot(at, label, key):
    fact = Fact(id="EVAL.PROBE", category="valuation", label=label, value=None,
                unit="text", as_of=at.date(), source="editorial_evaluation_concept_probe")
    return Snapshot(snapshot_id="EDITORIAL."+digest([key, at.isoformat()]), ticker="000000",
                    name="평가종목", as_of=at.date(), created_at=at,
                    provider="editorial_evaluation", facts={fact.id: fact})


def test_source_grounded_editorial_search_evaluation(tmp_path):
    package = corpus()
    observed = package.reviewed_at + timedelta(seconds=1)
    rows = []
    with RagStore(tmp_path / "archive") as store:
        imported = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        mapping = {n["chunk_id"]: n["id"] for n in imported["notes"]}
        generation = GenerationIndex(store).publish(observed)
        for key, path, label, gold in CASES:
            request = snapshot(observed, label, key)
            before = request.model_dump_json()
            context = Retriever(store).retrieve(request, generation_id=generation,
                                                time_policy="reconstructed-v1")
            data = context.payload
            assert data["status"] in {"completed", "empty"}
            assert request.model_dump_json() == before
            assert Retriever(store).load_context(context.context_id) == context
            candidates = [mapping[i["chunk_id"]] for i in data["candidates"] if i["path"] == path]
            selected = [mapping[i["chunk_id"]] for i in data["items"] if i["path"] == path]
            metrics = score_ranking(candidates, gold)
            rows.append({"case": key, "path": path, "concept": label, "relevant": gold,
                         "candidates": candidates, "selected": selected, "metrics": metrics,
                         "selected_recall": len(set(selected) & set(gold)) / len(gold) if gold else None,
                         "negative_background_returned": bool(selected) if not gold else None,
                         "query_terms": data["query_terms"],
                         "search_seconds": retrieval_audits(store, context.context_id)[-1]["search_elapsed_seconds"]})
        # The actual authored notes cannot be made available at a source's old publication date.
        old_generation = GenerationIndex(store).publish(observed-timedelta(seconds=1))
        early = Retriever(store).retrieve(snapshot(observed-timedelta(seconds=1), "PER", "early"),
                                          generation_id=old_generation, time_policy="reconstructed-v1")
        assert early.payload["status"] == "empty"
        for note in imported["notes"]:
            revision = store.revision(note["revision_id"])
            assert revision["content"]["metadata"]["human_reviewed"] is False
            assert revision["content"]["metadata"]["authorship"] == "original_Korean_paraphrase_not_source_quote"
            assert revision["content"]["published_at"] == package.authored_at.isoformat().replace("+00:00", "Z")
    positive = [r for r in rows if r["relevant"]]
    report = {"evidence_type": "source_grounded_agent_authored_not_human_reviewed",
              "corpus_hash": imported["corpus_hash"], "case_version": "editorial-direct-concepts-v1",
              "cases": len(rows), "positive_cases": len(positive),
              "macro_recall_at_20": sum(r["metrics"]["recall_at_k"] for r in positive)/len(positive),
              "mrr_at_20": sum(r["metrics"]["reciprocal_rank_at_k"] for r in positive)/len(positive),
              "selected_recall": sum(r["selected_recall"] for r in positive)/len(positive),
              "negative_background_returned": sum(bool(r["negative_background_returned"]) for r in rows),
              "operational_activation_eligible": False, "accuracy": None, "cost_usd": None,
              "results": rows}
    (tmp_path / "editorial-quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EDITORIAL_EVALUATION=" + json.dumps(report, ensure_ascii=False))
    assert report["macro_recall_at_20"] == 1
    assert report["mrr_at_20"] == 1
    assert report["selected_recall"] == 1
    assert next(r for r in rows if r["case"] == "unrelated_common")["selected"] == []


def test_editorial_review_fields_cannot_be_relabelled_as_human():
    package = corpus()
    assert package.review_kind == "agent_source_review"
    assert package.human_reviewed is False and package.release_status == "experimental"
    assert all(note.limitations and note.source_section for note in package.notes)
    for source in package.sources:
        assert source.observed_at <= package.reviewed_at
        assert source.published_on is None or source.published_on <= source.observed_at.date()

"""Checkpoint tests: generation construction, NOT end-to-end retrieval acceptance."""
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from bullbear.rag import AnnotationInput, ChunkInput, RagStore
from bullbear.rag.context import KnowledgeContext, MAX_TOKENS, token_upper_bound
from bullbear.rag.index import GenerationIndex
from .test_rag_ingest import T, batch, document


def context_payload(items=()):
    return {"schema_version": "knowledge-context-v1", "profile_version": "knowledge-short-v1",
            "snapshot_id": "fixture-snapshot", "decision_at": T.isoformat(),
            "status": "completed" if items else "empty", "items": list(items)}


def item(**changes):
    data = dict(text="변동성은 방향을 보장하지 않는다.", horizons=["common"],
                applicability="정의", limitations=[], study_scope=None, kind="knowledge")
    data.update(changes)
    return data


def seed(store, source_item_id="concept", kind="knowledge", text="volatility direction"):
    doc = document(text, kind=kind, source_item_id=source_item_id)
    store.import_collection(batch([doc], source_item_id))
    chunk = ChunkInput(revision_id=doc.revision_id, ordinal=0, text=text,
                       source_locator="paragraph:1", chunker_version="fixture-v1")
    store.add_chunk(chunk)
    store.annotate(AnnotationInput(chunk_id=chunk.chunk_id, horizons=("common", "short"),
                                  markets=("KR",), review_status="approved", created_at=T,
                                  reviewed_at=T, tagging_policy_version="fixture-v1"))
    return doc, chunk


def test_context_is_deeply_detached_canonical_and_deterministic():
    source = context_payload([item()])
    first = KnowledgeContext.from_payload(source)
    second = KnowledgeContext.from_payload(dict(reversed(list(source.items()))))
    source["items"][0]["text"] = "changed"
    detached = first.payload
    detached["items"].clear()
    assert first.context_id == second.context_id
    assert len(first.payload["items"]) == 1
    assert token_upper_bound(first.rendered) <= MAX_TOKENS
    with pytest.raises(FrozenInstanceError):
        first.payload_json = "{}"


def test_context_rejects_market_facts_failed_partial_and_token_overflow():
    with pytest.raises(ValueError, match="market facts"):
        KnowledgeContext.from_payload(context_payload([item(kind="news")]))
    payload = context_payload([item()])
    payload["status"] = "timeout"
    with pytest.raises(ValueError, match="selected items"):
        KnowledgeContext.from_payload(payload)
    with pytest.raises(ValueError, match="token upper"):
        KnowledgeContext.from_payload(context_payload([item(text="가" * 1000)]))


def test_generation_fixed_fts_corpus_excludes_news_and_future_reviews(tmp_path):
    with RagStore(tmp_path / "rag") as store:
        doc, chunk = seed(store)
        seed(store, "news", kind="news")
        index = GenerationIndex(store)
        generation = index.publish(T)
        path_bytes = index.path(generation).read_bytes()
        db, manifest = index.open(generation)
        try:
            assert [m["chunk_id"] for m in manifest["members"]] == [chunk.chunk_id]
            original_score = db.execute("SELECT bm25(corpus) FROM corpus WHERE corpus MATCH 'volatility'").fetchone()[0]
        finally:
            db.close()
        seed(store, "later", text="volatility volatility later")
        assert index.publish(T) != generation
        assert index.path(generation).read_bytes() == path_bytes
        db, manifest = index.open(generation)
        try:
            assert db.execute("SELECT bm25(corpus) FROM corpus WHERE corpus MATCH 'volatility'").fetchone()[0] == original_score
            assert manifest["members"][0]["revision_id"] == doc.revision_id
        finally:
            db.close()


def test_generation_uses_active_revision_and_latest_review_at_cutoff(tmp_path):
    with RagStore(tmp_path / "rag") as store:
        doc, chunk = seed(store)
        store.annotate(AnnotationInput(chunk_id=chunk.chunk_id, horizons=("common",),
                                      review_status="rejected", created_at=T + timedelta(minutes=1),
                                      reviewed_at=T + timedelta(minutes=1), tagging_policy_version="fixture-v2"))
        index = GenerationIndex(store)
        historical = index.publish(T)
        later = index.publish(T + timedelta(minutes=2))
        db, earlier = index.open(historical)
        db.close()
        db, latest = index.open(later)
        db.close()
        assert len(earlier["members"]) == 1
        assert latest["members"] == []

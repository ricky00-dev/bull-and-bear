"""Real archive -> sealed FTS -> retrieval tests; provider/model inputs are fixtures."""
import json
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bullbear.benchmark import BenchmarkConfig, run_rag_comparison
from bullbear.config import load_settings
from bullbear.events import EventLog
from bullbear.rag import AnnotationInput, ChunkInput, RagStore
from bullbear.rag.context import KnowledgeContext, token_upper_bound
from bullbear.rag.index import GenerationIndex
from bullbear.rag.replay import retrieval_audits
from bullbear.rag.retrieval import Retriever
from bullbear.server.app import create_app
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW
from .http_fixture import TestRunner, fixture_market
from .test_rag_ingest import document, batch
from .test_server import AUTH, completed, parse_sse, start


def seed(store, key="concept", *, text="변동성 volatility 방향 보장 없음", horizons=("common", "short"),
         markets=("KR",), tickers=(), kind="knowledge", at=NOW-timedelta(days=1),
         duplicate=None, review="approved", published=None):
    doc = document(text, observed=at, published_at=published or at-timedelta(hours=1),
                   kind=kind, source_item_id=key, title="금융 개념")
    store.import_collection(batch([doc], key + str(at)))
    chunk = ChunkInput(revision_id=doc.revision_id, ordinal=0, text=text,
                       source_locator="paragraph:1", chunker_version="test-v1")
    store.add_chunk(chunk)
    annotation = AnnotationInput(chunk_id=chunk.chunk_id, horizons=horizons, markets=markets,
                                 tickers=tickers, review_status=review, created_at=at,
                                 reviewed_at=at, tagging_policy_version="test-v1",
                                 duplicate_group_id=duplicate)
    store.annotate(annotation)
    return doc, chunk, annotation


@pytest.fixture
def snapshot():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def retrieve(store, snapshot, generation=None):
    generation = generation or GenerationIndex(store).publish(NOW)
    return Retriever(store).retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")


def test_real_search_caps_audit_replay_and_fixed_statistics(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        for i in range(25):
            seed(store, f"common{i}", text=f"volatility 공통 {i}", horizons=("common",))
            seed(store, f"short{i}", text=f"volatility 단기 {i}", horizons=("short",))
        generation = GenerationIndex(store).publish(NOW)
        before = snapshot.model_dump_json()
        first = retrieve(store, snapshot, generation)
        assert first.payload["status"] == "completed"
        assert [i["path"] for i in first.payload["items"]] == ["common"] * 2 + ["short"] * 3
        assert len(first.payload["candidates"]) == 40
        assert token_upper_bound(first.rendered) <= 2000
        assert sum(len(i["text"]) for i in first.payload["items"]) <= 6000
        seed(store, "new-document", text="volatility " * 10)
        GenerationIndex(store).publish(NOW)
        again = retrieve(store, snapshot, generation)
        assert first.payload_json == again.payload_json
        assert snapshot.model_dump_json() == before
        assert Retriever(store).load_context(first.context_id) == first
        assert len(retrieval_audits(store, first.context_id)) == 2
        assert all(a["search_elapsed_seconds"] < 1 for a in retrieval_audits(store, first.context_id))


def test_filters_precede_limit_and_future_correction_does_not_leak(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        doc, chunk, annotation = seed(store)
        for i in range(25):
            seed(store, f"foreign{i}", text="volatility " * 3 + str(i), markets=("US",))
        seed(store, "other-ticker", tickers=("999999",))
        seed(store, "news", kind="news")
        seed(store, "long", horizons=("long",))
        seed(store, "future-publication", published=NOW+timedelta(days=1))
        generation = GenerationIndex(store).publish(NOW)
        original = retrieve(store, snapshot, generation)
        assert [i["chunk_id"] for i in original.payload["items"]] == [chunk.chunk_id]
        assert {e["reason"] for e in original.payload["exclusions"]} == {"market", "ticker"}
        corrected = document("future correction", observed=NOW+timedelta(minutes=1),
                             published_at=NOW-timedelta(days=3), kind="knowledge", source_item_id="concept")
        store.import_collection(batch([corrected], "correction"))
        assert retrieve(store, snapshot, generation).payload_json == original.payload_json
        later = snapshot.model_copy(update={"created_at": NOW+timedelta(minutes=2)})
        after = retrieve(store, later, generation)
        assert after.payload["status"] == "empty"
        assert "inactive_revision" in {e["reason"] for e in after.payload["exclusions"]}
        assert Retriever(store).load_context(original.context_id) == original


@pytest.mark.parametrize("change", ["rejected", "approved", "withdrawn", "expired"])
def test_latest_review_validity_or_withdrawal_excludes_stale_generation(tmp_path, snapshot, change):
    with RagStore(tmp_path / "rag") as store:
        doc, chunk, annotation = seed(store)
        generation = GenerationIndex(store).publish(NOW-timedelta(hours=1))
        if change == "withdrawn":
            store.record_event(event_id="withdraw", document_id=doc.document_id, kind="withdrawn",
                               observed_at=NOW, source_ref="test")
        else:
            updates = {"created_at": NOW, "reviewed_at": NOW,
                       "review_status": "rejected" if change == "rejected" else "approved"}
            if change == "expired":
                updates["valid_until"] = NOW
            store.annotate(annotation.model_copy(update=updates))
        context = retrieve(store, snapshot, generation)
        assert context.payload["status"] == "empty"
        assert context.payload["exclusions"]


def test_dedup_and_whole_paragraph_budget(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        seed(store, "a", text="volatility 중복", duplicate="same-event")
        seed(store, "b", text="volatility 사건", duplicate="same-event")
        seed(store, "c", text="volatility 중복")
        seed(store, "oversize", text="volatility " + "가" * 2001)
        context = retrieve(store, snapshot)
        reasons = {c["reason"] for c in context.payload["candidates"]}
        assert {"duplicate", "context_budget"} <= reasons
        for item in context.payload["items"]:
            assert store.revision(item["revision_id"])["text"] == item["text"]


@pytest.mark.parametrize("damage", ["missing", "object", "members", "fts", "receipt"])
def test_corruption_is_failure_not_empty(tmp_path, snapshot, damage):
    with RagStore(tmp_path / "rag") as store:
        doc, _, _ = seed(store)
        index = GenerationIndex(store)
        generation = index.publish(NOW)
        if damage == "object":
            (store.objects / doc.content_hash).write_text("bad", encoding="utf-8")
        elif damage in {"members", "fts"}:
            with sqlite3.connect(index.path(generation)) as db:
                db.execute("UPDATE members SET payload='{}'" if damage == "members" else
                           "UPDATE corpus SET search_text='changed'")
        elif damage == "receipt":
            index.path(generation).with_suffix(".ready.json").unlink()
        else:
            generation = "G." + "0" * 64
        result = retrieve(store, snapshot, generation)
        assert result.payload["status"] == "failed" and not result.payload["items"]
        assert Retriever(store).load_context(result.context_id) == result


def test_empty_unmatched_and_future_generation_are_distinct(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        seed(store, text="unrelatedword", horizons=("common",))
        assert retrieve(store, snapshot).payload["status"] == "empty"
        future = GenerationIndex(store).publish(NOW+timedelta(days=1))
        assert retrieve(store, snapshot, future).payload["warnings"] == ["future_generation"]
        current = GenerationIndex(store).publish(NOW)
        assert Retriever(store).retrieve(snapshot, generation_id=current).payload["warnings"] == [
            "generation_not_committed_at_decision"]


def test_timeout_returns_no_partial_or_late_context(tmp_path, snapshot, monkeypatch):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        release.wait(5)
        exited.set()
        return {"status": "empty", "items": [], "warnings": []}
    with RagStore(tmp_path / "rag") as store:
        monkeypatch.setattr(Retriever, "_search", blocked)
        started = time.monotonic()
        context = retrieve(store, snapshot)
        elapsed = time.monotonic() - started
        try:
            assert entered.is_set() and context.payload["status"] == "timeout"
            assert 0.9 <= elapsed < 1.5  # scheduling/storage tolerance; not a hard real-time claim
            assert not context.payload["items"]
        finally:
            release.set()
            assert exited.wait(2)
        assert Retriever(store).load_context(context.context_id) == context
        assert len(retrieval_audits(store, context.context_id)) == 1


def test_context_rejects_path_overflow():
    payload = {"schema_version": "knowledge-context-v1", "profile_version": "knowledge-short-v1",
               "snapshot_id": "x", "decision_at": NOW.isoformat(), "status": "completed",
               "items": [{"kind": "knowledge", "text": "x", "horizons": ["common"], "path": "common",
                          "applicability": "", "limitations": [], "study_scope": None}] * 3}
    with pytest.raises(ValueError, match="path limit"):
        KnowledgeContext.from_payload(payload)


def test_alias_nfc_and_suitability_ranking(tmp_path, snapshot):
    import unicodedata
    with RagStore(tmp_path / "rag") as store:
        _, targeted, _ = seed(store, "targeted", text=unicodedata.normalize("NFD", "주가수익비율 정의"),
                               tickers=(snapshot.ticker,))
        seed(store, "global", text="per " * 20, markets=("global",))
        context = retrieve(store, snapshot)
        assert context.payload["items"][0]["chunk_id"] == targeted.chunk_id
        assert context.payload["candidates"][0]["suitability_grade"] == 0


def test_future_review_and_late_observation_do_not_rewrite_past(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        _, _, annotation = seed(store)
        generation = GenerationIndex(store).publish(NOW)
        before = retrieve(store, snapshot, generation)
        store.annotate(annotation.model_copy(update={"created_at": NOW+timedelta(hours=1),
                       "reviewed_at": NOW+timedelta(hours=1), "review_status": "rejected"}))
        seed(store, "late", at=NOW+timedelta(hours=1), published=NOW-timedelta(days=4))
        assert retrieve(store, snapshot, generation) == before
        historical = GenerationIndex(store).publish(NOW)
        assert retrieve(store, snapshot, historical).payload["items"] == before.payload["items"]


def test_cli_publish_retrieve_replay(tmp_path, snapshot, capsys):
    from bullbear.rag.cli import main
    with RagStore(tmp_path / "rag") as store:
        seed(store)
    prefix = ["--data-dir", str(tmp_path)]
    assert main(prefix + ["publish", "--as-of", NOW.isoformat()]) == 0
    generation = json.loads(capsys.readouterr().out)["generation_id"]
    path = snapshot.save(tmp_path)
    assert main(prefix + ["retrieve", str(path), "--generation", generation, "--reconstructed"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert main(prefix + ["replay", saved["context_id"]]) == 0
    assert json.loads(capsys.readouterr().out) == saved


def test_persistence_failure_never_returns_unsaved_success(tmp_path, snapshot, monkeypatch):
    from bullbear.rag import retrieval as module
    def fail(*args):
        raise OSError("fixture storage failure")
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        monkeypatch.setattr(module, "save_context", fail)
        with pytest.raises(OSError):
            retrieve(store, snapshot)


def test_publish_failure_preserves_previous_ready_generation(tmp_path, snapshot, monkeypatch):
    from bullbear.rag import index as module
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        index = GenerationIndex(store)
        generation = index.publish(NOW)
        original = retrieve(store, snapshot, generation)
        seed(store, "new", text="volatility 신규")
        def fail(*args):
            raise OSError("fixture publish failure")
        monkeypatch.setattr(module.os, "rename", fail)
        with pytest.raises(OSError):
            index.publish(NOW)
        assert retrieve(store, snapshot, generation) == original


def test_concurrent_publish_is_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        index = GenerationIndex(store)
        with ThreadPoolExecutor(max_workers=4) as pool:
            generations = list(pool.map(lambda _: index.publish(NOW), range(4)))
        assert len(set(generations)) == 1
        db, manifest = index.open(generations[0])
        db.close()
        assert len(manifest["members"]) == 1
        assert not list(index.directory.glob(".*"))


def test_sqlite_long_query_obeys_caller_deadline(tmp_path, snapshot, monkeypatch):
    import bullbear.rag.retrieval as module
    original = module.current_member
    def slow(db, *args):
        db.execute("WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n").fetchone()
        return original(db, *args)
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        monkeypatch.setattr(module, "current_member", slow)
        before = time.monotonic()
        result = retrieve(store, snapshot, generation)
        assert result.payload["status"] == "timeout"
        assert time.monotonic() - before < 1.5


def test_real_archive_search_benchmark_and_saved_report(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        context = retrieve(store, snapshot)
        assert context.payload["status"] == "completed"
        result = run_rag_comparison(snapshot, BenchmarkConfig(), tmp_path / "comparison", context)
        assert result["completed_arms"] == 4 and result["accuracy"] is None and result["cost_usd"] is None
        for arm in ("single", "debate"):
            events = EventLog.read(tmp_path / "comparison" / "common_short" / arm / "generations.jsonl")
            assert all(context.rendered in e["system"] for e in events if e["type"] == "generation_started")
        assert (tmp_path / "comparison" / "rag-comparison.json").exists()
        print("RAG_COMPARISON_MEASURED=" + json.dumps(result, ensure_ascii=False))


def test_repeated_search_latency_and_replay_evaluation(tmp_path, snapshot):
    with RagStore(tmp_path / "rag") as store:
        for i in range(50):
            seed(store, f"latency{i}", text=f"volatility 정의 {i}",
                 horizons=("common",) if i < 25 else ("short",))
        generation = GenerationIndex(store).publish(NOW)
        contexts, totals = [], []
        for _ in range(30):
            start_time = time.monotonic()
            contexts.append(retrieve(store, snapshot, generation))
            totals.append(time.monotonic()-start_time)
        assert len({c.context_id for c in contexts}) == 1
        assert all(c.payload["status"] == "completed" for c in contexts)
        timings = sorted(a["search_elapsed_seconds"] for a in retrieval_audits(store, contexts[0].context_id))
        assert len(timings) == 30 and max(timings) < 1
        report = {"corpus_documents": 50, "runs": 30, "completed": 30, "unique_contexts": 1,
                  "search_p95_seconds": timings[28], "search_max_seconds": max(timings),
                  "including_persistence_p95_seconds": sorted(totals)[28],
                  "cost_usd": None, "accuracy": None, "usage_status": "no_model_calls"}
        (tmp_path / "retrieval-evaluation.json").write_text(json.dumps(report), encoding="utf-8")
        print("RAG_SEARCH_MEASURED=" + json.dumps(report))


def test_real_archive_search_http_private_and_daily_reuse(tmp_path, monkeypatch):
    # Simulated publication clock; only this fixture may publish before historical NOW.
    from bullbear.rag import index as index_module
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW-timedelta(hours=1)).astimezone(tz)
    monkeypatch.setattr(index_module, "datetime", Clock)
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW-timedelta(hours=1))
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True, rag_generation_id=generation)
    market = fixture_market(settings)
    seen = []
    class Runner(TestRunner):
        background_context = None
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            seen.append(self.background_context)
            assert self.background_context.payload["status"] == "completed"
            with RagStore(tmp_path / "rag") as store:
                assert Retriever(store).load_context(self.background_context.context_id) == self.background_context
                seed(store, "during-debate", text="volatility 새로운 내용", at=NOW)
            return super().run(snapshot, debate_id, max_extra_rounds, emit)
    app = create_app(settings=settings, market=market, token="test-token", runner_factory=lambda: Runner(settings))
    try:
        with TestClient(app) as client:
            first = start(client).json()
            result = completed(client, first["debate_id"])
            assert result["status"] == "completed"
            second = start(client, key="another-key").json()
            assert second["reused"] and second["debate_id"] == first["debate_id"]
            events = parse_sse(client.get(f"/debates/{first['debate_id']}/events", headers=AUTH).text)
            assert "KCTX." not in json.dumps([result, events])
            assert "volatility" not in json.dumps([result, events])
            assert len(seen) == 1
    finally:
        if close := getattr(market, "close", None):
            close()

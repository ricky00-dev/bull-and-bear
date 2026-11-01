"""Actual pgvector plumbing with synthetic vectors; not model quality evidence."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest

from bullbear.rag.embeddings import (EmbeddingSpec, EmbeddingService, OpenAIEmbeddings,
    EmbeddingUnavailable, BudgetExceeded, checked_vector)
from bullbear.rag.vectors import VectorIndex, install_vectors, ranked_rows
from bullbear.rag.vector_evaluation import ComparisonCase, compare, metrics
from bullbear.rag.retrieval import Retriever, query_terms
from bullbear.rag.index import GenerationIndex
from bullbear.rag.store import RagStore
from bullbear.rag.context_repository import PostgresContextRepository
from bullbear.snapshot import build_snapshot
from .test_rag_archive_storage import archive_dsn
from .test_rag_retrieval import seed
from .fakes import FakeSource, NOW


def spec(**changes):
    return EmbeddingSpec(provider="fixture", model="synthetic-concepts", revision="v1", dimensions=3,
                         price_revision="test-price-v1", nano_usd_per_token=10, **changes)


class FixtureProvider:
    calls = 0
    def embed(self, version, text):
        self.calls += 1
        if "unrelated" in text:
            return [0, 1, 0], 1
        if "흔들림" in text or "volatility" in text:
            return [1, 0, 0], 1
        return [0, 0, 1], 1


@pytest.fixture
def vector_service(archive_dsn):
    install_vectors(archive_dsn)
    install_vectors(archive_dsn)
    return EmbeddingService(archive_dsn, spec(), FixtureProvider())


def test_versioned_cache_usage_and_price_change_reuses_vectors(archive_dsn):
    provider = FixtureProvider()
    service = EmbeddingService(archive_dsn, spec(), provider)
    key, value = service.prepare("volatility", "document", daily_budget_nano=1000)
    assert service.prepare("volatility", "document", daily_budget_nano=0) == (key, value)
    assert provider.calls == 1
    changed_price = EmbeddingService(archive_dsn, spec().model_copy(update={"price_revision": "new", "nano_usd_per_token": 20}), provider)
    assert changed_price.spec.version_id == service.spec.version_id
    assert changed_price.prepare("volatility", "document", daily_budget_nano=0) == (key, value)
    assert service.ledger()[0]["measured_cost_nano"] == 10
    assert service.ledger()[0]["input_tokens"] == 1
    different = EmbeddingService(archive_dsn, spec().model_copy(update={"revision": "v2"}), provider)
    assert different.prepare("volatility", "document", daily_budget_nano=2000)[0] != key
    assert provider.calls == 2


def test_budget_reservation_concurrent_calls_never_overspend(archive_dsn):
    def prepare(text):
        service = EmbeddingService(archive_dsn, spec(), FixtureProvider())
        try:
            service.prepare(text, "document", daily_budget_nano=100)
            return True
        except (BudgetExceeded, EmbeddingUnavailable):
            return False
    # Each text reserves 100 nano; settled cost is 10, so only assert accounted bound.
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(prepare, ["volatility"] * 8))
    service = EmbeddingService(archive_dsn, spec())
    assert service.ledger()[0]["calls"] == 1
    assert service.ledger()[0]["measured_cost_nano"] == 10
    with pytest.raises(BudgetExceeded):
        EmbeddingService(archive_dsn, spec(), FixtureProvider()).prepare("another text", "query", daily_budget_nano=10)


def test_unknown_call_retains_reservation_and_never_auto_retries(archive_dsn):
    class Broken:
        calls = 0
        def embed(self, *_):
            self.calls += 1
            raise TimeoutError("secret URL and key")
    provider = Broken()
    service = EmbeddingService(archive_dsn, spec(), provider)
    for _ in range(2):
        with pytest.raises(EmbeddingUnavailable) as error:
            service.prepare("volatility", "query", daily_budget_nano=1000)
        assert "secret" not in str(error.value)
    assert provider.calls == 1
    assert service.ledger()[0]["unknown_calls"] == 1
    assert service.ledger()[0]["reserved_nano"] == 100


@pytest.mark.parametrize("values,tokens", [([0, 0, 0], 1), ([1, 0], 1), ([float('nan'), 0, 1], 1), ([1, 0, 0], 999)])
def test_invalid_response_is_charged_but_not_cached(archive_dsn, values, tokens):
    provider = SimpleNamespace(embed=lambda *_: (values, tokens))
    service = EmbeddingService(archive_dsn, spec(), provider)
    with pytest.raises(EmbeddingUnavailable):
        service.prepare("query", "query", daily_budget_nano=1000)
    assert service.ledger()[0]["measured_cost_nano"] == tokens * 10
    with pytest.raises(EmbeddingUnavailable):
        service.cached("query", "query")


def test_openai_adapter_with_fake_client_and_no_network():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model="test-model", data=[SimpleNamespace(index=0, embedding=[1, 0, 0])],
                               usage=SimpleNamespace(prompt_tokens=2))
    provider = OpenAIEmbeddings(SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    version = spec().model_copy(update={"provider": "openai", "model": "test-model"})
    assert provider.embed(version, "query") == ([1, 0, 0], 2)
    assert calls == [{"model": "test-model", "input": ["query"], "dimensions": 3, "encoding_format": "float"}]


def test_exact_vector_search_and_paired_comparison(vector_service, tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path) as store:
        _, good, _ = seed(store, "semantic", text="가격의 흔들림 크기")
        _, lexical, _ = seed(store, "lexical", text="volatility unrelated")
        _, foreign, _ = seed(store, "foreign", text="volatility", tickers=("999999",))
        _, rejected, _ = seed(store, "rejected", text="volatility", review="rejected")
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        vector_id = index.build(store, generation, daily_budget_nano=100000)
        calls = vector_service.provider.calls
        assert index.build(store, generation, daily_budget_nano=100000) == vector_id
        assert vector_service.provider.calls == calls
        vector_service.prepare(" ".join(query_terms(snapshot)), "query", daily_budget_nano=100000)
        case = ComparisonCase(id="synthetic", snapshot=snapshot, relevant=[good.chunk_id], forbidden=[foreign.chunk_id, rejected.chunk_id])
        report = compare(store, index, generation, [case], context_repository=PostgresContextRepository(vector_service.repository.dsn))
        assert report["summary"]["dense"]["failures"] == 0
        assert report["summary"]["dense"]["mrr"] == 1
        assert report["summary"]["bm25"]["mrr"] == 0
        assert all(v["forbidden_hits"] == 0 for v in report["summary"].values())
        ids = [r["context_id"] for r in report["results"]]
        assert len(set(ids)) == 3
        for key in ids:
            assert PostgresContextRepository(vector_service.repository.dsn).load(key).context_id == key


def test_missing_query_cache_and_rejection_after_build_fail_closed(vector_service, tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path) as store:
        _, chunk, approval = seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        retriever = Retriever(store, strategy="dense", vector_index=index)
        assert retriever.retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1").payload["status"] == "failed"
        vector_service.prepare(" ".join(query_terms(snapshot)), "query", daily_budget_nano=100000)
        store.annotate(approval.model_copy(update={"review_status": "rejected"}))
        result = retriever.retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert result.payload["status"] == "empty"
        assert not result.payload["items"]


def test_incomplete_vector_generation_is_not_published(vector_service, tmp_path):
    with RagStore(tmp_path) as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        with pytest.raises(BudgetExceeded):
            VectorIndex(vector_service).build(store, generation, daily_budget_nano=0)
    with vector_service.repository._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rag.vector_generations").fetchone()[0] == 0


def test_metrics_penalize_short_result_lists_and_rrf_uses_ranks():
    assert metrics(["a"], ["a", "b"], 2)["ndcg"] < 1
    lexical = [{"rowid": 1, "score": -1000}, {"rowid": 2, "score": -.000001}]
    rows = ranked_rows(lexical, {"1": 0, "2": 0}, {1: .8, 2: .1}, "hybrid")
    assert rows[0]["rrf"] == rows[1]["rrf"]
    with pytest.raises(ValueError):
        checked_vector([0, 0, 0], 3)


def test_distinct_requests_share_reserved_budget(archive_dsn):
    import threading
    entered, release = threading.Event(), threading.Event()
    class Waiting:
        def embed(self, *_):
            entered.set()
            assert release.wait(5)
            return [1, 0, 0], 1
    service = EmbeddingService(archive_dsn, spec(), Waiting())
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(service.prepare, "volatility", "document", daily_budget_nano=100)
        try:
            assert entered.wait(5)
            second = EmbeddingService(archive_dsn, spec().model_copy(update={"revision": "other"}), FixtureProvider())
            with pytest.raises(BudgetExceeded):
                second.prepare("other", "query", daily_budget_nano=100)
            assert second.provider.calls == 0
        finally:
            release.set()
        pending.result()


def test_vector_readiness_and_dimension_versions_are_enforced(vector_service, tmp_path):
    from bullbear.rag.schemas import stamp
    with RagStore(tmp_path) as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        vector_service.prepare("volatility", "query", daily_budget_nano=100000)
        db, manifest = GenerationIndex(store).open(generation)
        db.close()
        with pytest.raises(EmbeddingUnavailable, match="not ready at decision"):
            index.distances({}, generation, manifest, "volatility", cutoff=stamp(NOW), time_policy="observed-v1")
        wrong = EmbeddingService(vector_service.repository.dsn, spec().model_copy(update={"dimensions": 2}))
        with pytest.raises(EmbeddingUnavailable):
            wrong.cached("volatility", "query")


def test_corrupt_vector_is_rejected_and_vector_table_is_immutable(vector_service, tmp_path):
    import psycopg
    from bullbear.rag.schemas import stamp
    from bullbear.rag.objects import ArchiveCorruptError
    with RagStore(tmp_path) as store:
        _, chunk, _ = seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        vector_service.prepare("volatility", "query", daily_budget_nano=100000)
        with pytest.raises(psycopg.errors.RaiseException):
            with psycopg.connect(vector_service.repository.dsn) as raw:
                raw.execute("UPDATE rag.embedding_vectors SET embedding='[0,1,0]'")
        # Simulate storage corruption using the disposable DB's owner only.
        with psycopg.connect(vector_service.repository.dsn) as raw:
            raw.execute("ALTER TABLE rag.embedding_vectors DISABLE TRIGGER immutable_embedding_vectors")
            raw.execute("UPDATE rag.embedding_vectors SET embedding='[0,1,0]'")
        db, manifest = GenerationIndex(store).open(generation)
        db.close()
        with pytest.raises(ArchiveCorruptError):
            index.distances({1: manifest["members"][0]}, generation, manifest, "volatility",
                            cutoff=stamp(NOW), time_policy="reconstructed-v1")


def test_compare_failures_are_reported_not_scored_as_success(vector_service, tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path) as store:
        _, chunk, _ = seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        case = ComparisonCase(id="missing-query", snapshot=snapshot, relevant=[chunk.chunk_id])
        result = compare(store, index, generation, [case], context_repository=None)
        assert result["summary"]["dense"]["failures"] == 1
        assert result["summary"]["dense"]["recall"] is None
        assert result["summary"]["bm25"]["failures"] == 0


def test_no_extension_does_not_spend_embedding_budget(archive_dsn, tmp_path):
    provider = FixtureProvider()
    index = VectorIndex(EmbeddingService(archive_dsn, spec(), provider))
    with RagStore(tmp_path) as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        with pytest.raises(EmbeddingUnavailable):
            index.build(store, generation, daily_budget_nano=100000)
    assert provider.calls == 0


def test_comparison_cli_flags_negative_case_answers(vector_service, tmp_path, monkeypatch, capsys):
    from bullbear.rag.vector_cli import main
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    monkeypatch.setenv("BULLBEAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BULLBEAR_RAG_ARCHIVE_BACKEND", "sqlite")
    monkeypatch.setenv("BULLBEAR_RAG_OBJECT_BACKEND", "local")
    monkeypatch.setenv("BULLBEAR_RAG_POSTGRES_DSN", vector_service.repository.dsn)
    with RagStore(tmp_path / "rag") as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        VectorIndex(vector_service).build(store, generation, daily_budget_nano=100000)
    vector_service.prepare(" ".join(query_terms(snapshot)), "query", daily_budget_nano=100000)
    calls = vector_service.provider.calls
    version_file, cases_file, report_file = (tmp_path / n for n in ("spec.json", "cases.json", "report.json"))
    version_file.write_text(vector_service.spec.model_dump_json(), encoding="utf-8")
    cases_file.write_text(json.dumps([ComparisonCase(id="negative", snapshot=snapshot,
        relevant=[], expect_empty=True).model_dump(mode="json")]), encoding="utf-8")
    assert main(["compare", str(cases_file), "--spec", str(version_file), "--generation", generation,
                 "--output", str(report_file)]) == 1
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["summary"]["dense"]["unexpected_answers"] == 1
    assert report["summary"]["dense"]["failures"] == 0
    assert vector_service.provider.calls == calls

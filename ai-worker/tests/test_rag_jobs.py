"""Capture-based incremental ingestion on SQLite and a disposable real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from bullbear.rag.jobs import IngestJobs, LeaseLost, incremental_window, main
from bullbear.rag.store import RagStore
from bullbear.rag.archive_repository import PostgresArchive
from bullbear.rag.objects import ObjectStorageError
from .test_rag_archive_storage import archive_dsn
from .test_rag_ingest import document, batch, T


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path):
    if request.param == "postgres":
        dsn = request.getfixturevalue("archive_dsn")
        with PostgresArchive(tmp_path, dsn) as value:
            yield value
    else:
        with RagStore(tmp_path) as value:
            yield value


def capture(ticker="005930", suffix="first", at=T, **changes):
    doc = document(observed=at, source_item_id=ticker, tickers=(ticker,))
    return batch([doc], ticker + "-" + suffix, query_key=ticker,
                 window_start=at-timedelta(days=1), window_end=at,
                 completed_through=at, **changes)


def test_30_tickers_incremental_overlap_and_idempotency(store):
    jobs = IngestJobs(store)
    for i in range(30):
        ticker = f"{i:06d}"
        item = capture(ticker)
        first = jobs.enqueue(item, ticker=ticker, now=T)
        assert jobs.enqueue(item, ticker=ticker, now=T) == first
    assert len(jobs.run(limit=30)) == 30
    assert all(row["state"] == "succeeded" and row["attempts"] == 1 for row in jobs.status())
    assert jobs.run() == []
    assert store.counts()["document_revisions"] == 30
    for i in range(30):
        ticker = f"{i:06d}"
        window = incremental_window(store, "naver-news", ticker, start=T-timedelta(days=3),
                                    end=T+timedelta(days=1))
        assert window["window_start"].startswith((T-timedelta(hours=1)).isoformat()[:19])
        later = capture(ticker, "next", at=T+timedelta(hours=1))
        jobs.enqueue(later, ticker=ticker)
    assert len(jobs.run(limit=30)) == 30
    assert store.counts()["document_revisions"] == 30  # observations aren't revisions
    assert store.counts()["collection_runs"] == 60
    for i in (0, 10, 20):
        ticker = f"{i:06d}"
        update = capture(ticker, "correction", at=T+timedelta(hours=2))
        revised = update.items[0].model_copy(update={"text": "정정된 요약"})
        jobs.enqueue(update.model_copy(update={"items": (revised,)}), ticker=ticker)
    assert len(jobs.run()) == 3
    assert store.counts()["document_revisions"] == 33
    for i in (0, 10, 20):
        original = capture(f"{i:06d}").items[0]
        assert store.document_at(original.document_id, T)["text"] == original.text
        assert store.document_at(original.document_id, T+timedelta(hours=2))["text"] == "정정된 요약"


def test_storage_retry_backoff_then_success(store, monkeypatch):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T)
    claim = jobs.claim(now=T)
    original = store.object_store.put
    def fail(*_):
        raise ObjectStorageError("secret provider message")
    monkeypatch.setattr(store.object_store, "put", fail)
    assert jobs.execute(claim, now=T) == "retry"
    assert jobs.claim(now=T+timedelta(seconds=4)) is None
    assert store.counts()["collection_runs"] == 0
    assert store.watermark("naver-news", "005930") is None
    assert jobs.status()[0]["safe_error"] == "storage_unavailable"
    monkeypatch.setattr(store.object_store, "put", original)
    claim = jobs.claim(now=T+timedelta(seconds=5))
    assert jobs.execute(claim, now=T+timedelta(seconds=5)) == "succeeded"
    assert jobs.status()[0]["attempts"] == 2


def test_expired_worker_cannot_write_and_exhausted_jobs_are_terminal(store):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", max_attempts=2, now=T)
    old = jobs.claim(now=T, lease_seconds=5)
    replacement = jobs.claim(now=T+timedelta(seconds=5), lease_seconds=5)
    assert replacement["lease_token"] != old["lease_token"]
    with pytest.raises(LeaseLost):
        jobs.execute(old, now=T+timedelta(seconds=6))
    with pytest.raises(LeaseLost):
        jobs.heartbeat(old, now=T+timedelta(seconds=6))
    assert jobs.claim(now=T+timedelta(seconds=10)) is None
    assert jobs.status()[0]["state"] == "failed"
    assert store.counts()["collection_runs"] == 0


def test_completion_failure_rolls_back_watermark_and_archive(store, monkeypatch):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T)
    job = jobs.claim(now=T)
    original = jobs._event
    def fail(db, row, event, at, error=None):
        if event == "succeeded":
            raise ObjectStorageError("audit unavailable")
        return original(db, row, event, at, error)
    monkeypatch.setattr(jobs, "_event", fail)
    assert jobs.execute(job, now=T) == "retry"
    assert store.counts()["collection_runs"] == 0
    assert store.watermark("naver-news", "005930") is None
    monkeypatch.setattr(jobs, "_event", original)
    assert jobs.execute(jobs.claim(now=T+timedelta(seconds=5)), now=T+timedelta(seconds=5)) == "succeeded"


def test_partial_failed_empty_and_ticker_isolation(store):
    jobs = IngestJobs(store)
    partial = capture().model_copy(update={"status": "partial", "coverage": "partial",
        "safe_error": "page_cap", "completed_through": None})
    jobs.enqueue(partial, ticker="005930", now=T)
    empty = batch([], "empty", query_key="000001", completed_through=T)
    jobs.enqueue(empty, ticker="000001", now=T)
    failed = batch([], "failed", query_key="000002", status="failed", coverage="unknown", safe_error="provider_error", pages=0)
    jobs.enqueue(failed, ticker="000002", now=T)
    assert {r["state"] for r in jobs.run()} == {"partial", "succeeded", "failed"}
    assert jobs.run() == []  # retrying identical incomplete captures cannot fix coverage
    assert store.watermark("naver-news", "005930") is None
    assert store.watermark("naver-news", "000001") is not None
    assert store.watermark("naver-news", "000002") is None
    with pytest.raises(ValueError, match="mismatch"):
        jobs.enqueue(capture(), ticker="000001")
    with pytest.raises(ValueError, match="conflict"):
        jobs.enqueue(capture(), ticker="005930")


def test_lease_expiring_during_object_write_is_fenced(store, monkeypatch):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T)
    claim = jobs.claim(now=T, lease_seconds=5)
    original = store.object_store.put
    def slow(key, payload):
        original(key, payload)
        jobs.claim(now=T+timedelta(seconds=6))
    monkeypatch.setattr(store.object_store, "put", slow)
    with pytest.raises(LeaseLost):
        jobs.execute(claim, now=T+timedelta(seconds=1))
    assert store.counts()["collection_runs"] == 0


def test_heartbeat_and_safe_attempt_history(store):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T)
    claim = jobs.claim(now=T, lease_seconds=5)
    jobs.heartbeat(claim, lease_seconds=10, now=T+timedelta(seconds=4))
    assert jobs.claim(now=T+timedelta(seconds=6)) is None
    assert jobs.execute(claim, now=T+timedelta(seconds=7)) == "succeeded"
    events = store.db.execute("SELECT event FROM ingest_attempts ORDER BY occurred_at").fetchall()
    assert [r[0] for r in events] == ["started", "succeeded"]
    with pytest.raises(Exception):
        store.db.execute("DELETE FROM ingest_attempts")


def test_parallel_claims_use_distinct_tokens(store):
    jobs = IngestJobs(store)
    for i in range(10):
        jobs.enqueue(capture(f"{i:06d}"), ticker=f"{i:06d}", now=T)
    def claim(_):
        # Separate connections model independently restarting workers.
        other = PostgresArchive(store.directory, store._dsn) if isinstance(store, PostgresArchive) else RagStore(store.directory)
        with other:
            return IngestJobs(other).claim(now=T)
    with ThreadPoolExecutor(4) as pool:
        claims = list(pool.map(claim, range(14)))
    taken = [c for c in claims if c]
    assert len(taken) == len({c["job_id"] for c in taken}) == 10
    assert len({c["lease_token"] for c in taken}) == 10


def test_cli_manifest_and_plan(tmp_path, monkeypatch, capsys):
    import json
    monkeypatch.setenv("BULLBEAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BULLBEAR_RAG_ARCHIVE_BACKEND", "sqlite")
    monkeypatch.setenv("BULLBEAR_RAG_OBJECT_BACKEND", "local")
    path = tmp_path / "capture.json"
    path.write_text(json.dumps([{"ticker": "005930", "batch": capture().model_dump(mode="json")}]), encoding="utf-8")
    assert main(["enqueue", str(path)]) == 0
    assert main(["run"]) == 0
    assert main(["status"]) == 0
    assert 'succeeded' in capsys.readouterr().out
    assert main(["plan", "--source", "naver-news", "--tickers", "005930,000001",
                 "--start", (T-timedelta(days=3)).isoformat(), "--end", (T+timedelta(days=1)).isoformat()]) == 0


def test_same_ticker_windows_serialize_but_other_tickers_progress(store):
    jobs = IngestJobs(store)
    later = jobs.enqueue(capture(suffix="later", at=T+timedelta(hours=1)), ticker="005930", now=T)
    earlier = jobs.enqueue(capture(), ticker="005930", now=T)
    unrelated = jobs.enqueue(capture("000001"), ticker="000001", now=T)
    claims = [jobs.claim(now=T), jobs.claim(now=T)]
    assert {c["job_id"] for c in claims} == {earlier, unrelated}
    assert jobs.claim(now=T) is None
    for claim in claims:
        assert jobs.execute(claim, now=T) == "succeeded"
    assert jobs.claim(now=T)["job_id"] == later


def test_shared_document_across_tickers_is_not_duplicated(store):
    jobs = IngestJobs(store)
    doc = document(source_item_id="shared", tickers=("000001", "000002"))
    for ticker in doc.tickers:
        jobs.enqueue(batch([doc], ticker, query_key=ticker, completed_through=T), ticker=ticker)
    assert len(jobs.run()) == 2
    assert store.counts()["documents"] == store.counts()["document_revisions"] == 1
    assert store.watermark("naver-news", "000001") and store.watermark("naver-news", "000002")


def test_retry_exhaustion_and_permanent_conflict(store, monkeypatch):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T, max_attempts=1)
    def fail(*_):
        raise ObjectStorageError("unavailable")
    monkeypatch.setattr(store.object_store, "put", fail)
    assert jobs.execute(jobs.claim(now=T), now=T) == "failed"
    assert jobs.claim(now=T+timedelta(hours=1)) is None


def test_retry_wait_does_not_block_other_ticker(store):
    jobs = IngestJobs(store)
    first_id = jobs.enqueue(capture(), ticker="005930", now=T)
    first = jobs.claim(now=T)
    assert first["job_id"] == first_id
    jobs._fail(first, "storage_unavailable", retry=True, now=T)
    jobs.enqueue(capture(suffix="later", at=T+timedelta(hours=1)), ticker="005930", now=T)
    other = jobs.enqueue(capture("000001"), ticker="000001", now=T)
    assert jobs.claim(now=T)["job_id"] == other
    assert jobs.claim(now=T) is None
    retry = jobs.claim(now=T+timedelta(seconds=5))
    assert retry["job_id"] == first_id
    jobs._fail(retry, "storage_unavailable", retry=True, now=T+timedelta(seconds=5))
    assert jobs.claim(now=T+timedelta(seconds=14)) is None
    assert jobs.claim(now=T+timedelta(seconds=15))["job_id"] == first_id


def test_existing_collection_conflict_is_terminal_without_overwrite(store):
    original = capture()
    store.import_collection(original)
    changed = original.model_copy(update={"raw_payload": {"changed": True}})
    jobs = IngestJobs(store)
    jobs.enqueue(changed, ticker="005930", now=T)
    assert jobs.execute(jobs.claim(now=T), now=T) == "failed"
    assert jobs.status()[0]["safe_error"] == "invalid_capture_or_conflict"
    assert store.import_collection(original).reused


def test_queue_preserves_watermark_gap(store):
    jobs = IngestJobs(store)
    jobs.enqueue(capture(), ticker="005930", now=T)
    jobs.execute(jobs.claim(now=T), now=T)
    old = store.watermark("naver-news", "005930")
    gap = capture(suffix="gap", at=T+timedelta(days=3))
    jobs.enqueue(gap, ticker="005930", now=T)
    jobs.execute(jobs.claim(now=T), now=T)
    assert store.watermark("naver-news", "005930") == old
    import json
    assert json.loads(store.collection(gap.collection_id)["result_json"])["watermark_reason"] == "coverage_gap"


def test_queue_survives_restart(tmp_path):
    with RagStore(tmp_path) as store:
        job_id = IngestJobs(store).enqueue(capture(), ticker="005930", now=T)
    with RagStore(tmp_path) as store:
        jobs = IngestJobs(store)
        assert jobs.run()[0] == {"job_id": job_id, "ticker": "005930", "state": "succeeded"}


def test_sqlite_queue_cutover_preserves_pending_and_attempts(archive_dsn, tmp_path):
    from bullbear.rag.archive_transfer import import_archive
    from bullbear.rag.objects import ArchiveCorruptError
    with RagStore(tmp_path / "source") as source:
        jobs = IngestJobs(source)
        jobs.enqueue(capture(), ticker="005930", now=T)
        jobs.execute(jobs.claim(now=T), now=T)
        jobs.enqueue(capture("000001"), ticker="000001", now=T)
        path = source.path
    with PostgresArchive(tmp_path / "target", archive_dsn) as target:
        report = import_archive(path, target)
        assert report["tables"]["ingest_attempts"] == 2
        assert len(IngestJobs(target).run()) == 1
        assert target.counts()["documents"] == 2
    with RagStore(path.parent) as source:
        jobs = IngestJobs(source)
        jobs.claim(now=T)
        with pytest.raises(ArchiveCorruptError):
            import_archive(path, dry_run=True)

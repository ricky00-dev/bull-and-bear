from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from bullbear.data.base import Disclosure, NewsArticle
from bullbear.rag import AnnotationInput, ChunkInput, CollectionBatch, DocumentInput, RagStore
from bullbear.rag.cli import main as rag_cli
from bullbear.rag.ingest import disclosure_document, news_document, sync_payload
from bullbear.rag.schemas import Period, StudyScope
from bullbear.rag.store import ArchiveCorruptError

T = datetime(2026, 10, 30, 7, tzinfo=timezone.utc)  # 16:00 KST


def document(text="최초 요약", observed=T, **changes):
    data = dict(source="naver-news", source_item_id="article-1", source_ref="article-1", kind="news",
                url="https://example.com/news/1", title="삼성전자 기사", text=text,
                content_level="title_summary", observed_at=observed, published_at=T - timedelta(hours=1),
                timestamp_precision="instant", publication_verified=True)
    data.update(changes)
    return DocumentInput(**data)


def batch(items=(), collection_id="run-1", **changes):
    items = tuple(items)
    data = dict(collection_id=collection_id, source="naver-news", query_key="005930",
                window_start=T - timedelta(days=1), window_end=T,
                started_at=min([i.observed_at for i in items] or [T]),
                finished_at=max([i.observed_at for i in items] or [T]), items=items,
                status="completed" if items else "empty", coverage="complete", pages=1,
                observation_mode="current")
    data.update(changes)
    return CollectionBatch(**data)


@pytest.fixture
def store(tmp_path):
    with RagStore(tmp_path / "rag") as value:
        yield value


def test_current_history_idempotence_and_a_b_a_activation(store):
    a = document()
    first = store.import_collection(batch([a]))
    assert (first.new_revisions, first.new_events) == (1, 1)
    replay = store.import_collection(batch([a]))
    assert replay.reused and store.counts()["collection_runs"] == 1
    repeat = a.model_copy(update={"observed_at": T + timedelta(minutes=1)})
    result = store.import_collection(batch([repeat], "repeat"))
    assert (result.new_revisions, result.new_events) == (0, 0)
    b = document("정정 요약", T + timedelta(minutes=2))
    store.import_collection(batch([b], "correction"))
    reverted = document(observed=T + timedelta(minutes=3))
    result = store.import_collection(batch([reverted], "revert"))
    assert (result.new_revisions, result.new_events) == (0, 1)
    assert store.counts()["document_revisions"] == 2
    assert store.counts()["document_events"] == 3
    assert store.document_at(a.document_id, T - timedelta(seconds=1)) is None
    assert store.document_at(a.document_id, T)["text"] == a.text
    assert store.document_at(a.document_id, b.observed_at)["text"] == b.text
    assert store.document_at(a.document_id, reverted.observed_at)["text"] == a.text
    assert store.revision(a.revision_id)["first_observed_at"].startswith("2026-10-30T07:00:00")
    with pytest.raises(ValueError, match="reused"):
        store.import_collection(batch([b]))


def test_archive_backfill_never_activates_or_backdates_first_observation(store):
    a = document()
    store.import_collection(batch([a]))
    old = document("과거 검색 결과", T + timedelta(hours=1))
    result = store.import_collection(batch([old], "old-import", observation_mode="archive"))
    assert result.new_revisions == 1 and result.new_events == 0
    assert store.document_at(a.document_id, T + timedelta(days=1))["revision_id"] == a.revision_id
    assert store.revision(old.revision_id)["first_observed_at"] > store.revision(a.revision_id)["first_observed_at"]


def test_explicit_withdrawal_uses_observation_time_and_can_be_reactivated(store):
    a = document()
    store.import_collection(batch([a]))
    event = dict(event_id="remove", document_id=a.document_id, kind="withdrawn",
                 observed_at=T + timedelta(hours=1), source_ref="publisher-removal-notice")
    store.record_event(**event)
    store.record_event(**event)
    assert store.document_at(a.document_id, T)["revision_id"] == a.revision_id
    assert store.document_at(a.document_id, T + timedelta(hours=1)) is None
    with pytest.raises(ValueError, match="reused"):
        store.record_event(**{**event, "kind": "deleted"})
    a2 = document(observed=T + timedelta(hours=2))
    store.import_collection(batch([a2], "restored"))
    assert store.document_at(a.document_id, a2.observed_at)["revision_id"] == a.revision_id


def test_date_only_disclosure_is_eligible_only_after_actual_observation(store):
    item = disclosure_document(Disclosure("DART:20261030000001", T.date(), "기업설명회", "삼성전자",
                                         "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261030000001"), observed_at=T, ticker="005930")
    result = store.import_collection(batch([item], source="opendart"))
    assert result.quarantined_items == 0
    assert store.document_at(item.document_id, T - timedelta(seconds=1)) is None
    saved = store.document_at(item.document_id, T + timedelta(minutes=40))
    assert saved["published_at"] is None and saved["published_on"] == "2026-10-30"
    assert saved["content_level"] == "title_only" and saved["content"]["metadata"]["filer"] == "삼성전자"


@pytest.mark.parametrize("changes,reason", [
    ({"published_at": T + timedelta(seconds=1)}, "publication_after_observation"),
    ({"source_updated_at": T + timedelta(seconds=1)}, "update_after_observation"),
    ({"publication_verified": False}, "publication_unverified"),
    ({"published_at": None, "timestamp_precision": "unknown"}, "publication_time_unknown"),
    ({"published_at": None, "published_on": (T + timedelta(days=1)).date(), "timestamp_precision": "day"}, "publication_date_after_observation"),
])
def test_unconfirmed_or_impossible_publication_is_preserved_but_quarantined(store, changes, reason):
    item = document(**changes)
    result = store.import_collection(batch([item]))
    assert result.quarantined_items == 1
    assert store.revision(item.revision_id)["quarantine_reason"] == reason
    assert store.document_at(item.document_id, T + timedelta(days=30)) is None


def test_new_quarantined_version_does_not_fall_back_to_stale_valid_version(store):
    original = document()
    store.import_collection(batch([original]))
    changed = document("확인되지 않은 정정", T + timedelta(minutes=1), publication_verified=False)
    store.import_collection(batch([changed], "unverified"))
    assert store.document_at(original.document_id, T)["revision_id"] == original.revision_id
    assert store.document_at(original.document_id, changed.observed_at) is None


def test_timezone_normalization_url_identity_and_metadata_revision():
    original = document(url="HTTPS://EXAMPLE.COM/news/1#top")
    same = document(published_at=original.published_at.astimezone(timezone(timedelta(hours=9))),
                    observed=T + timedelta(minutes=1), source_payload={"transient": "capture"})
    assert original.content_hash == same.content_hash
    assert document(metadata={"filer": "변경"}).content_hash != same.content_hash
    assert document(published_at=T - timedelta(hours=2)).content_hash != same.content_hash
    with pytest.raises(ValidationError, match="timezone"):
        document(observed=T.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        document(url="https://user:secret@example.com/article")


def test_complete_empty_partial_failed_and_watermark_gap_are_distinct(store):
    store.import_collection(batch([], completed_through=T))
    assert store.watermark("naver-news", "005930")["completed_through"].startswith("2026-10-30T07:00:00")
    for status, coverage, error in [("partial", "partial", "page_cap"), ("failed", "unknown", "provider_error")]:
        store.import_collection(batch([], status, status=status, coverage=coverage, safe_error=error, pages=0))
        assert store.collection(status)["status"] == status
    later = batch([], "gap", window_start=T + timedelta(minutes=1), window_end=T + timedelta(hours=1), completed_through=T + timedelta(hours=1))
    result = store.import_collection(later)
    assert not result.watermark_advanced and result.watermark_reason == "coverage_gap"
    fill = batch([], "fill", window_start=T, window_end=T + timedelta(hours=1), completed_through=T + timedelta(hours=1))
    assert store.import_collection(fill).watermark_advanced
    assert store.import_collection(batch([], "earlier", completed_through=T)).watermark_reason == "not_newer"
    with pytest.raises(ValidationError):
        batch([], "unknown-empty", pages=0)
    with pytest.raises(ValidationError):
        batch([], "bad-completed", status="completed")
    with pytest.raises(ValidationError):
        batch([], "bad-watermark", observation_mode="archive", completed_through=T)


def provider_payload(items):
    return dict(collection_id="provider", source="naver-news", query_key="005930", ticker="005930", kind="news",
                observed_at=T.isoformat(), window_start=(T - timedelta(days=1)).isoformat(), window_end=T.isoformat(),
                started_at=T.isoformat(), finished_at=T.isoformat(), observation_mode="current",
                status="completed" if items else "empty", coverage="complete", pages=1, items=items,
                completed_through=T.isoformat())


def raw_news():
    return dict(source_ref="https://EXAMPLE.com/1#x", title="삼성전자 실적", summary="기사 요약만 보존",
                published_at=(T - timedelta(minutes=1)).isoformat(), url="https://example.com/1", publisher="언론사")


def test_provider_import_preserves_raw_summary_and_never_claims_full_text(store):
    result = sync_payload(store, provider_payload([raw_news()]))
    item = news_document(NewsArticle(**raw_news()), observed_at=T, ticker="005930")
    saved = store.document_at(item.document_id, T)
    assert result.watermark_advanced
    assert saved["text"] == "기사 요약만 보존" and saved["content_level"] == "title_summary"
    recorded = json.loads(store.collection("provider")["input_json"])
    assert recorded["raw_payload"]["items"][0] == raw_news()


def test_invalid_provider_items_are_audited_without_advancing_watermark(store):
    payload = provider_payload([raw_news(), {"title": "invalid", "secret": "DO_NOT_ECHO"}])
    result = sync_payload(store, payload)
    assert result.status == "partial" and result.imported_items == 1 and result.rejected_items == 1 and not result.watermark_advanced
    row = store.collection("provider")
    assert row["safe_error"] == "invalid_provider_item" and "DO_NOT_ECHO" in row["input_json"]
    assert store.watermark("naver-news", "005930") is None
    no_items = provider_payload([])
    no_items.pop("items")
    no_items["collection_id"] = "missing"
    result = sync_payload(store, no_items)
    assert result.status == "failed" and store.collection("missing")["safe_error"] == "missing_items"
    actual_empty = provider_payload([])
    actual_empty["collection_id"] = "empty"
    assert sync_payload(store, actual_empty).status == "empty"


def test_collection_is_atomic_and_rows_are_immutable(store):
    a = document()
    bad = document("공시", T + timedelta(minutes=1), kind="disclosure")
    with pytest.raises(ValueError, match="kind"):
        store.import_collection(batch([a, bad]))
    assert store.counts()["documents"] == 0 and store.counts()["collection_runs"] == 0
    store.import_collection(batch([a]))
    for table in ("document_revisions", "document_events", "collection_runs"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.db.execute(f"DELETE FROM {table}")


def test_corrupt_or_missing_object_fails_closed(store):
    a = document()
    store.import_collection(batch([a]))
    (store.objects / a.content_hash).write_text("corrupt", encoding="utf-8")
    with pytest.raises(ArchiveCorruptError):
        store.document_at(a.document_id, T)
    with pytest.raises(ArchiveCorruptError):
        store.import_collection(batch([a], "repeat"))
    assert store.collection("repeat") is None


def test_multiple_tags_review_history_and_period_units(store):
    a = document()
    store.import_collection(batch([a]))
    chunk = ChunkInput(revision_id=a.revision_id, ordinal=0, text=a.text, source_locator="summary:0", chunker_version="capture-v1")
    assert store.add_chunk(chunk) == store.add_chunk(chunk)
    scope = StudyScope(forecast_horizon=Period(value=7, unit="trading_day"), outcome_metric="alpha_vs_KOSPI")
    approved = AnnotationInput(chunk_id=chunk.chunk_id, horizons=("common", "short"), review_status="approved",
                               created_at=T, reviewed_at=T + timedelta(minutes=1), tagging_policy_version="manual-v1", study_scope=scope)
    annotation_id = store.annotate(approved)
    assert store.annotate(approved) == annotation_id
    assert store.annotation_at(chunk.chunk_id, T) is None
    assert store.annotation_at(chunk.chunk_id, approved.reviewed_at)["horizons"] == ["common", "short"]
    rejection = approved.model_copy(update={"review_status": "rejected", "reviewed_at": T + timedelta(minutes=2)})
    store.annotate(rejection)
    assert store.annotation_at(chunk.chunk_id, rejection.reviewed_at) is None
    assert store.annotation_at(chunk.chunk_id, approved.reviewed_at)["annotation_id"] == annotation_id
    with pytest.raises(ValidationError):
        AnnotationInput(**{**approved.model_dump(), "horizons": ["short", "short"]})
    with pytest.raises(ValueError, match="quote"):
        store.add_chunk(chunk.model_copy(update={"text": "출처에 없는 문장"}))


def test_wal_read_snapshot_and_separate_writers_are_safe(store):
    reader = store.open_reader()
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        store.import_collection(batch([document()]))
        assert reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        reader.execute("COMMIT")
        assert reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("DELETE FROM documents")
    finally:
        reader.close()
    def writer(_):
        with RagStore(store.directory) as second:
            return second.import_collection(batch([document()], "concurrent"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(writer, range(3)))
    assert sum(not r.reused for r in results) == 1
    assert store.counts()["collection_runs"] == 2


def test_migration_reopen_and_future_version_rejection(tmp_path):
    directory = tmp_path / "archive"
    with RagStore(directory) as first:
        first.import_collection(batch([document()]))
        assert first.db.execute("PRAGMA user_version").fetchone()[0] == 1
    with RagStore(directory) as reopened:
        assert reopened.document_at(document().document_id, T)["text"] == document().text
        assert reopened.db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
        reopened.db.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="version"):
        RagStore(directory)


def test_local_cli_sync_inspect_and_dispatch(tmp_path, capsys, monkeypatch):
    import httpx
    from bullbear.cli import main
    def no_network(*_a, **_kw):
        raise AssertionError("network is forbidden in local archive CLI")
    monkeypatch.setattr(httpx.Client, "send", no_network)
    payload_file = tmp_path / "capture.json"
    payload_file.write_text(json.dumps(provider_payload([raw_news()]), ensure_ascii=False), encoding="utf-8")
    args = ["--data-dir", str(tmp_path / "data")]
    assert rag_cli([*args, "sync", str(payload_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["new_revisions"] == 1
    assert rag_cli([*args, "inspect"]) == 0
    assert json.loads(capsys.readouterr().out)["documents"] == 1
    with pytest.raises(SystemExit) as exc:
        main(["rag", *args, "inspect"])
    assert exc.value.code == 0
    capsys.readouterr()
    bad = tmp_path / "bad.json"
    bad.write_text('{"api_key":"NEVER_PRINT_THIS"}', encoding="utf-8")
    assert rag_cli([*args, "import", str(bad)]) == 1
    output = capsys.readouterr()
    assert "NEVER_PRINT_THIS" not in output.out + output.err


def test_same_instant_conflicting_observations_are_rejected_atomically(store):
    a, b = document(), document("다른 버전")
    with pytest.raises(ValueError, match="ambiguous"):
        store.import_collection(batch([a, b]))
    assert store.counts()["collection_runs"] == 0
    store.import_collection(batch([a]))
    with pytest.raises(ValueError, match="ambiguous"):
        store.import_collection(batch([b], "other-job"))
    assert store.document_at(a.document_id, T)["text"] == a.text
    assert store.collection("other-job") is None


def test_approved_annotation_expiration_never_resurrects_old_annotation(store):
    a = document()
    store.import_collection(batch([a]))
    chunk = ChunkInput(revision_id=a.revision_id, ordinal=0, text=a.text, source_locator="summary", chunker_version="v1")
    store.add_chunk(chunk)
    base = dict(chunk_id=chunk.chunk_id, horizons=("short",), review_status="approved", created_at=T, tagging_policy_version="manual-v1")
    store.annotate(AnnotationInput(**base, reviewed_at=T))
    store.annotate(AnnotationInput(**base, reviewed_at=T + timedelta(minutes=1), valid_until=T + timedelta(minutes=2)))
    assert store.annotation_at(chunk.chunk_id, T + timedelta(minutes=1)) is not None
    assert store.annotation_at(chunk.chunk_id, T + timedelta(minutes=2)) is None


def test_normalized_import_defaults_to_archive_without_online_activation(store, tmp_path, capsys):
    a = document()
    payload = batch([a]).model_dump(mode="json")
    payload.pop("observation_mode")
    capture = tmp_path / "archive.json"
    capture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    # CLI receives a WORKER data dir; this store is already under that dir/rag.
    assert rag_cli(["--data-dir", str(store.directory.parent), "import", str(capture)]) == 0
    assert json.loads(capsys.readouterr().out)["new_events"] == 0
    assert store.document_at(a.document_id, T + timedelta(days=1)) is None


def test_late_imported_actual_earlier_observation_preserves_point_in_time_replay(store):
    late = document(observed=T + timedelta(minutes=10))
    store.import_collection(batch([late], "captured-10"))
    earlier = document(observed=T + timedelta(minutes=5))
    store.import_collection(batch([earlier], "captured-5"))
    assert store.document_at(earlier.document_id, T + timedelta(minutes=4)) is None
    selected = store.document_at(earlier.document_id, T + timedelta(minutes=6))
    assert selected["revision_id"] == earlier.revision_id
    assert selected["first_observed_at"].startswith("2026-10-30T07:05:00")
    assert selected["first_recorded_observation_at"].startswith("2026-10-30T07:10:00")


def test_quarantine_is_per_observation_and_later_verified_capture_can_recover(store):
    early = document(published_at=T + timedelta(minutes=1))
    store.import_collection(batch([early], "impossible-early"))
    valid = early.model_copy(update={"observed_at": T + timedelta(minutes=2)})
    result = store.import_collection(batch([valid], "valid-later"))
    assert result.new_revisions == 0 and result.new_events == 1
    assert store.document_at(early.document_id, T) is None
    assert store.document_at(early.document_id, T + timedelta(minutes=1)) is None
    assert store.document_at(valid.document_id, valid.observed_at)["quarantine_reason"] is None


def test_bad_earlier_capture_imported_late_cannot_make_future_publication_available(store):
    valid = document(published_at=T + timedelta(minutes=8), observed=T + timedelta(minutes=10))
    store.import_collection(batch([valid], "valid-first"))
    invalid = valid.model_copy(update={"observed_at": T + timedelta(minutes=5)})
    store.import_collection(batch([invalid], "bad-older-capture"))
    assert store.document_at(valid.document_id, T + timedelta(minutes=6)) is None
    assert store.document_at(valid.document_id, T + timedelta(minutes=9)) is None
    assert store.document_at(valid.document_id, T + timedelta(minutes=10))["revision_id"] == valid.revision_id


def test_document_lookup_keeps_one_wal_snapshot_across_event_and_revision_queries(store, monkeypatch):
    a = document()
    store.import_collection(batch([a]))
    original_revision = store.revision
    observed_counts = []
    def concurrent_revision(revision_id):
        with RagStore(store.directory) as writer:
            writer.import_collection(batch([document("동시 정정", T + timedelta(minutes=1))], "concurrent-correction"))
        observed_counts.append(store.db.execute("SELECT COUNT(*) FROM document_revisions").fetchone()[0])
        return original_revision(revision_id)
    monkeypatch.setattr(store, "revision", concurrent_revision)
    assert store.document_at(a.document_id, T + timedelta(minutes=2))["text"] == a.text
    assert observed_counts == [1]
    monkeypatch.setattr(store, "revision", original_revision)
    assert store.document_at(a.document_id, T + timedelta(minutes=2))["text"] == "동시 정정"

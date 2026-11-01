"""Real archive cutover and sealed-generation parity; no provider/model calls."""
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from bullbear.rag.archive_repository import PostgresArchive, configured_archive
from bullbear.rag.archive_transfer import import_archive, read_archive, copy_objects
from bullbear.rag.context_repository import PostgresContextRepository, ContextStorageError
from bullbear.rag.generation_transfer import push_generation, fetch_generation
from bullbear.rag.index import GenerationIndex
from bullbear.rag.objects import ArchiveCorruptError, LocalObjectStore, S3ObjectStore, ObjectStorageError
from bullbear.rag.retrieval import Retriever
from bullbear.rag.storage import migrate
from bullbear.rag.store import RagStore
from bullbear.snapshot import build_snapshot
from .test_rag_retrieval import seed
from .fakes import FakeSource, NOW


@pytest.fixture
def archive_dsn():
    dsn = os.getenv("BULLBEAR_TEST_RAG_POSTGRES_DSN")
    if not dsn:
        pytest.skip("dedicated test DSN not set")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    name = "rag_archive_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    target = make_conninfo(dsn, dbname=name)
    try:
        migrate(target)
        migrate(target)
        yield target
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_local_objects_atomic_concurrent_and_no_overwrite(tmp_path):
    store = LocalObjectStore(tmp_path)
    data = "원문".encode()
    key = hashlib.sha256(data).hexdigest()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: store.put(key, data), range(12)))
    assert store.get(key) == data
    (tmp_path / key).write_bytes(b"corrupt")
    with pytest.raises(ArchiveCorruptError):
        store.put(key, data)
    assert (tmp_path / key).read_bytes() == b"corrupt"
    with pytest.raises(ArchiveCorruptError):
        store.get("../escape")


def test_s3_conditional_put_duplicate_verification_and_safe_errors():
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber, ANY
    from botocore.response import StreamingBody
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    store = S3ObjectStore("fixture", client=client)
    data = b"original"
    key = hashlib.sha256(data).hexdigest()
    request = {"Bucket": "fixture", "Key": "rag/objects/" + key, "Body": data,
               "IfNoneMatch": "*", "ChecksumSHA256": ANY}
    with Stubber(client) as stub:
        stub.add_client_error("put_object", service_error_code="ConditionalRequestConflict", http_status_code=409, expected_params=request)
        stub.add_response("put_object", {}, request)
        store.put(key, data)
        stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412, expected_params=request)
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(data), len(data))}, {"Bucket": "fixture", "Key": "rag/objects/" + key})
        store.put(key, data)
        stub.add_client_error("get_object", service_error_code="AccessDenied", service_message="secret credential", http_status_code=403)
        with pytest.raises(ObjectStorageError) as error:
            store.get(key)
        assert "secret" not in str(error.value)
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(b"bad"), 3)})
        with pytest.raises(ArchiveCorruptError):
            store.get(key)
        stub.assert_no_pending_responses()


def test_sqlite_can_move_objects_without_database_changes(tmp_path):
    remote = LocalObjectStore(tmp_path / "remote")
    with RagStore(tmp_path / "source") as source:
        doc, chunk, _ = seed(source)
        path = source.path
    before = path.read_bytes()
    assert copy_objects(path, remote)["objects"] == 1
    assert path.read_bytes() == before
    with RagStore(path.parent, object_store=remote) as moved:
        assert moved.revision(doc.revision_id)["text"] == doc.text
        assert moved.annotation_at(chunk.chunk_id, NOW)["review_status"] == "approved"


def test_invalid_source_rejected_before_object_upload(tmp_path):
    with RagStore(tmp_path / "source") as source:
        doc, _, _ = seed(source)
        (source.objects / doc.content_hash).write_bytes(b"tampered")
        with pytest.raises(ArchiveCorruptError):
            import_archive(source.path, dry_run=True)
    with pytest.raises(Exception):
        import_archive(tmp_path / "missing.sqlite3", dry_run=True)
    assert not (tmp_path / "missing.sqlite3").exists()


def test_cutover_preserves_search_review_history_and_generation(archive_dsn, tmp_path):
    remote = LocalObjectStore(tmp_path / "remote")
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path / "source") as source:
        doc, chunk, annotation = seed(source)
        generation = GenerationIndex(source).publish(NOW)
        before = Retriever(source).retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert before.payload["status"] == "completed"
        # Later rejection must never be converted back into approval by import.
        rejected = annotation.model_copy(update={"review_status": "rejected", "reviewed_at": NOW + timedelta(days=1)})
        source.annotate(rejected)
        path = source.path
    original_bytes = path.read_bytes()
    assert import_archive(path, dry_run=True)["tables"]["chunk_annotations"] == 2
    with PostgresArchive(tmp_path / "publisher", archive_dsn, object_store=remote) as target:
        report = import_archive(path, target)
        assert import_archive(path, target) == report
        assert target.document_at(doc.document_id, NOW)["revision_id"] == doc.revision_id
        assert target.annotation_at(chunk.chunk_id, NOW)["review_status"] == "approved"
        assert target.annotation_at(chunk.chunk_id, NOW + timedelta(days=1)) is None
        target.annotate(annotation, initial_only=True)
        assert target.counts()["chunk_annotations"] == 2
        # Export original sealed bytes, retaining historical committed_at.
    with PostgresArchive(path.parent, archive_dsn, object_store=remote) as publisher:
        receipt = push_generation(publisher, generation)
        assert push_generation(publisher, generation) == receipt
    with PostgresArchive(tmp_path / "new-worker", archive_dsn, object_store=remote) as target:
        assert not (target.directory / "rag.sqlite3").exists()
        assert fetch_generation(target, generation)["committed_at"] == receipt["committed_at"]
        fetch_generation(target, generation)
        result = Retriever(target, context_repository=PostgresContextRepository(archive_dsn)).retrieve(
            snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert result.payload == before.payload
        assert result.context_id == before.context_id
        # Append after imported sequence values; preserved old rejection wins ties.
        newest = rejected.model_copy(update={"reviewed_at": NOW + timedelta(days=2), "tagging_policy_version": "new"})
        target.annotate(newest)
        assert target.counts()["chunk_annotations"] == 3
        assert target.annotation_at(chunk.chunk_id, NOW + timedelta(days=2)) is None
        with pytest.raises(ArchiveCorruptError, match="empty or an exact"):
            import_archive(path, target)
    assert path.read_bytes() == original_bytes


def test_postgres_writers_and_immutable_reviews(archive_dsn, tmp_path):
    def write(_):
        with PostgresArchive(tmp_path, archive_dsn) as target:
            return seed(target)[1].chunk_id
    with ThreadPoolExecutor(4) as pool:
        assert len(set(pool.map(write, range(8)))) == 1
    with PostgresArchive(tmp_path, archive_dsn) as target:
        assert target.counts()["chunk_annotations"] == 1
        assert target.counts()["document_events"] == 1
        with pytest.raises(ContextStorageError):
            target.db.execute("UPDATE chunk_annotations SET review_status='rejected'")
        assert target.counts()["chunk_annotations"] == 1
        with pytest.raises(ContextStorageError):
            target.db.execute("TRUNCATE chunk_horizons")


def test_object_failure_does_not_commit_archive(archive_dsn, tmp_path):
    class Broken:
        def put(self, *_):
            raise ObjectStorageError("failed")
    with PostgresArchive(tmp_path, archive_dsn, object_store=Broken()) as target:
        with pytest.raises(ObjectStorageError):
            seed(target)
        assert not any(target.counts().values())


def test_import_conflict_leaves_destination_intact(archive_dsn, tmp_path):
    with RagStore(tmp_path / "source") as source:
        seed(source, key="source")
        path = source.path
    with PostgresArchive(tmp_path / "destination", archive_dsn) as target:
        seed(target, key="other")
        before = target.counts()
        with pytest.raises(ArchiveCorruptError):
            import_archive(path, target)
        assert target.counts() == before


def test_configuration_fails_closed(tmp_path):
    from dataclasses import replace
    from bullbear.config import load_settings
    settings = replace(load_settings(), data_dir=tmp_path, rag_archive_backend="postgres", rag_postgres_dsn=None)
    with pytest.raises(ValueError):
        configured_archive(settings)
    with pytest.raises(ValueError):
        configured_archive(replace(settings, rag_archive_backend="typo"))


@pytest.mark.parametrize("name", [
    "test_current_history_idempotence_and_a_b_a_activation",
    "test_archive_backfill_never_activates_or_backdates_first_observation",
    "test_explicit_withdrawal_uses_observation_time_and_can_be_reactivated",
    "test_date_only_disclosure_is_eligible_only_after_actual_observation",
    "test_new_quarantined_version_does_not_fall_back_to_stale_valid_version",
    "test_complete_empty_partial_failed_and_watermark_gap_are_distinct",
    "test_provider_import_preserves_raw_summary_and_never_claims_full_text",
    "test_invalid_provider_items_are_audited_without_advancing_watermark",
    "test_multiple_tags_review_history_and_period_units",
    "test_same_instant_conflicting_observations_are_rejected_atomically",
    "test_approved_annotation_expiration_never_resurrects_old_annotation",
    "test_late_imported_actual_earlier_observation_preserves_point_in_time_replay",
    "test_quarantine_is_per_observation_and_later_verified_capture_can_recover",
    "test_bad_earlier_capture_imported_late_cannot_make_future_publication_available",
])
def test_postgres_archive_domain_parity(archive_dsn, tmp_path, name):
    from . import test_rag_ingest
    with PostgresArchive(tmp_path, archive_dsn) as store:
        getattr(test_rag_ingest, name)(store)


def test_mid_import_failure_rolls_back_rows(archive_dsn, tmp_path, monkeypatch):
    with RagStore(tmp_path / "source") as source:
        seed(source)
        path = source.path
    with PostgresArchive(tmp_path / "dest", archive_dsn) as target:
        execute = target.db.execute
        def fail(query, params=()):
            if query.startswith("INSERT INTO chunk_annotations"):
                raise ContextStorageError("injected write failure")
            return execute(query, params)
        monkeypatch.setattr(target.db, "execute", fail)
        with pytest.raises(ContextStorageError):
            import_archive(path, target)
        assert not any(target.counts().values())
        monkeypatch.setattr(target.db, "execute", execute)
        assert import_archive(path, target)["objects"] == 1


def test_corrupt_review_denormalization_is_rejected(tmp_path):
    with RagStore(tmp_path) as source:
        seed(source)
        source.db.execute("DROP TRIGGER immutable_chunk_annotations_update")
        source.db.execute("UPDATE chunk_annotations SET review_status='rejected'")
        with pytest.raises(ArchiveCorruptError):
            import_archive(source.path, dry_run=True)


def test_verified_cache_avoids_remote_reads_and_rejects_corruption(tmp_path):
    from bullbear.rag.objects import CachedObjectStore
    class Remote:
        calls = 0
        def get(self, key):
            self.calls += 1
            return b"source"
    remote = Remote()
    cache = CachedObjectStore(remote, tmp_path)
    key = hashlib.sha256(b"source").hexdigest()
    assert cache.get(key) == cache.get(key) == b"source"
    assert remote.calls == 1

    (tmp_path / key).write_bytes(b"corrupt")
    with pytest.raises(ArchiveCorruptError):
        cache.get(key)
    assert remote.calls == 1


def test_missing_original_cannot_become_safe_empty_retrieval(tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with RagStore(tmp_path) as store:
        doc, _, _ = seed(store)
        generation = GenerationIndex(store).publish(NOW)
        (store.objects / doc.content_hash).unlink()
        result = Retriever(store).retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert result.payload["status"] == "failed"
        assert result.payload["warnings"] == ["integrity_error"]

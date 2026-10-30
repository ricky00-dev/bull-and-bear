import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from bullbear.rag.corpus import Corpus, import_corpus
from bullbear.rag.index import GenerationIndex
from bullbear.rag.retrieval import Retriever
from bullbear.rag.schemas import AnnotationInput, ChunkInput, CollectionBatch
from bullbear.rag.store import RagStore
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW

PACKAGE = Path(__file__).parents[1] / "knowledge" / "common-short-v1.json"


def corpus():
    return Corpus.model_validate_json(PACKAGE.read_text(encoding="utf-8"))


def test_editorial_package_has_traceable_basis_and_no_fake_human_review(tmp_path):
    package = corpus()
    observed = package.reviewed_at + timedelta(seconds=1)
    with RagStore(tmp_path) as store:
        with pytest.raises(ValueError, match="opt-in"):
            import_corpus(store, package, observed_at=observed)
        assert store.counts()["documents"] == 0
        first = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        assert len(first["notes"]) == 6 and not first["human_reviewed"]
        again = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        assert first == again
        assert store.counts()["documents"] == 6
        for note in first["notes"]:
            revision = store.revision(note["revision_id"])
            metadata = revision["content"]["metadata"]
            assert metadata["basis"]["url"].startswith("https://")
            assert metadata["authorship"] == "original_Korean_paraphrase_not_source_quote"
            assert metadata["human_reviewed"] is False
            assert revision["published_at"] == package.authored_at.isoformat(timespec="microseconds")


def test_corpus_not_available_before_observation_and_no_fact_mutation(tmp_path):
    package = corpus()
    observed = package.reviewed_at + timedelta(seconds=1)
    with RagStore(tmp_path) as store:
        imported = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        index = GenerationIndex(store)
        early = index.publish(observed-timedelta(seconds=1))
        db, early_manifest = index.open(early)
        db.close()
        assert early_manifest["members"] == []
        ready = index.publish(observed)
        snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW).model_copy(update={"created_at": observed})
        original = snapshot.model_dump_json()
        result = Retriever(store).retrieve(snapshot, generation_id=ready, time_policy="reconstructed-v1")
        assert result.payload["status"] == "completed"
        assert {i["path"] for i in result.payload["items"]} == {"common", "short"}
        assert all(i["chunk_id"] in {n["chunk_id"] for n in imported["notes"]} for i in result.payload["items"])
        assert all(i["role"] == "background_only" for i in result.payload["items"])
        assert snapshot.model_dump_json() == original


def test_corpus_rejects_bad_source_future_review_and_unattested_human(tmp_path):
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    for change in ({"human_reviewed": True}, {"reviewed_at": "2026-01-01T00:00:00Z"}):
        with pytest.raises(ValueError):
            Corpus.model_validate({**data, **change})
    future = json.loads(PACKAGE.read_text(encoding="utf-8"))
    future["sources"][0]["published_on"] = "2027-01-01"
    with pytest.raises(ValueError, match="publication date"):
        Corpus.model_validate(future)
    data["notes"][0]["source_id"] = "missing"
    with pytest.raises(ValueError):
        Corpus.model_validate(data)
    with RagStore(tmp_path) as store:
        with pytest.raises(ValueError, match="backdate"):
            import_corpus(store, corpus(), allow_agent_reviewed=True, observed_at=NOW)
        assert store.counts()["documents"] == 0


def test_reimport_preserves_frozen_generation_and_later_rejection(tmp_path):
    package = corpus()
    first_at = package.reviewed_at + timedelta(seconds=1)
    later = first_at + timedelta(seconds=10)
    with RagStore(tmp_path) as store:
        import_corpus(store, package, allow_agent_reviewed=True, observed_at=first_at)
        generation = GenerationIndex(store).publish(first_at)
        snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW).model_copy(update={"created_at": later})
        before = Retriever(store).retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert before.payload["status"] == "completed"
        import_corpus(store, package, allow_agent_reviewed=True, observed_at=later)
        after = Retriever(store).retrieve(snapshot, generation_id=generation, time_policy="reconstructed-v1")
        assert before.context_id == after.context_id
        assert store.counts()["chunk_annotations"] == 6
        assert store.counts()["collection_runs"] == 2

        chunk = before.payload["items"][0]["chunk_id"]
        annotation = store.annotation_at(chunk, later)
        annotation.pop("annotation_id")
        rejected_at = later + timedelta(seconds=1)
        store.annotate(AnnotationInput.model_validate({**annotation, "review_status": "rejected",
                       "created_at": rejected_at, "reviewed_at": rejected_at}))
        final_at = later + timedelta(seconds=2)
        import_corpus(store, package, allow_agent_reviewed=True, observed_at=final_at)
        assert store.annotation_at(chunk, final_at) is None
        assert store.counts()["chunk_annotations"] == 7
        result = Retriever(store).retrieve(snapshot.model_copy(update={"created_at": final_at}),
                                           generation_id=generation, time_policy="reconstructed-v1")
        assert chunk not in {item["chunk_id"] for item in result.payload["items"]}


@pytest.mark.parametrize("status", ["rejected", "proposed"])
def test_unrelated_note_and_package_updates_preserve_existing_review(tmp_path, status):
    package = corpus()
    first_at = package.reviewed_at + timedelta(seconds=1)
    later = first_at + timedelta(seconds=10)
    with RagStore(tmp_path) as store:
        first = import_corpus(store, package, allow_agent_reviewed=True, observed_at=first_at)
        original = first["notes"][0]
        annotation = store.annotation_at(original["chunk_id"], first_at)
        annotation.pop("annotation_id")
        review_id = store.annotate(AnnotationInput.model_validate({**annotation, "review_status": status,
            "created_at": first_at + timedelta(seconds=1),
            "reviewed_at": first_at + timedelta(seconds=1) if status == "rejected" else None}))
        generation = GenerationIndex(store).publish(first_at)
        data = package.model_dump(mode="json")
        data.update(corpus_version="package-v2", authored_at=later, reviewed_at=later, reviewer="another agent")
        for source in data["sources"]:
            source["observed_at"] = later
        data["notes"][1]["title"] += " 수정"
        updated = Corpus.model_validate(data)
        second = import_corpus(store, updated, allow_agent_reviewed=True, observed_at=later)
        assert original == second["notes"][0]
        assert first["notes"][2:] == second["notes"][2:]
        assert first["notes"][1]["revision_id"] != second["notes"][1]["revision_id"]
        assert store.revision(original["revision_id"])["published_at"] == package.authored_at.isoformat(timespec="microseconds")
        latest = store.db.execute("SELECT annotation_id FROM chunk_annotations WHERE chunk_id=? ORDER BY annotation_seq DESC",
                                  (original["chunk_id"],)).fetchone()[0]
        assert latest == review_id
        changed = second["notes"][1]
        assert store.annotation_at(changed["chunk_id"], later) is None
        assert store.counts()["document_revisions"] == 7
        assert store.counts()["chunk_annotations"] == 8
        third = import_corpus(store, updated, allow_agent_reviewed=True, observed_at=later + timedelta(seconds=1))
        assert third["notes"] == second["notes"]
        assert store.counts()["chunk_annotations"] == 8
        assert store.annotation_at(changed["chunk_id"], later + timedelta(seconds=1)) is None
        db, manifest = GenerationIndex(store).open(generation)
        db.close()
        assert changed["chunk_id"] not in {member["chunk_id"] for member in manifest["members"]}
        raw = json.loads(store.db.execute("SELECT input_json FROM collection_runs ORDER BY finished_at DESC LIMIT 1").fetchone()[0])
        assert raw["raw_payload"]["corpus"]["reviewer"] == "another agent"
        assert raw["items"][0]["source_payload"]["corpus_version"] == "package-v2"


def test_concurrent_package_provenance_updates_do_not_renew_review(tmp_path):
    package = corpus()
    observed = package.reviewed_at + timedelta(seconds=1)
    with RagStore(tmp_path) as store:
        first = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
    def refresh(offset):
        later = observed + timedelta(seconds=offset)
        updated = package.model_copy(update={"authored_at": later, "reviewed_at": later,
                                              "corpus_version": f"refresh-{offset}"})
        with RagStore(tmp_path) as writer:
            return import_corpus(writer, updated, allow_agent_reviewed=True, observed_at=later)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(refresh, (10, 20)))
    assert all(result["notes"] == first["notes"] for result in results)
    with RagStore(tmp_path) as store:
        assert store.counts()["document_revisions"] == store.counts()["chunk_annotations"] == 6


def test_interrupted_changed_note_import_stays_proposed_on_retry(tmp_path, monkeypatch):
    package = corpus()
    observed = package.reviewed_at + timedelta(seconds=1)
    with RagStore(tmp_path) as store:
        import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        data = package.model_dump(mode="json")
        data["notes"][0]["topics"].append("changed-classification")
        updated = Corpus.model_validate(data)
        original = store.annotate
        def interrupted(*args, **kwargs):
            raise RuntimeError("interrupted before annotation")
        monkeypatch.setattr(store, "annotate", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            import_corpus(store, updated, allow_agent_reviewed=True, observed_at=observed + timedelta(seconds=1))
        monkeypatch.setattr(store, "annotate", original)
        later = observed + timedelta(seconds=2)
        retried = import_corpus(store, updated, allow_agent_reviewed=True, observed_at=later)
        assert store.annotation_at(retried["notes"][0]["chunk_id"], later) is None
        assert store.counts()["chunk_annotations"] == 7


def test_legacy_package_hash_revision_preserves_its_rejection(tmp_path):
    package = corpus()
    package = package.model_copy(update={"notes": package.notes[:1]})
    observed = package.reviewed_at + timedelta(seconds=1)
    with RagStore(tmp_path / "seed") as seed:
        imported = import_corpus(seed, package, allow_agent_reviewed=True, observed_at=observed)
        batch = json.loads(seed.db.execute("SELECT input_json FROM collection_runs").fetchone()[0])
        annotation = seed.annotation_at(imported["notes"][0]["chunk_id"], observed)
    item = batch["items"][0]
    item["source_ref"] = package.corpus_version + ":" + package.notes[0].id
    item["source_payload"] = {}
    item["metadata"].pop("note_fingerprint")
    item["metadata"].pop("initial_review_status")
    item["metadata"].update(corpus_hash=imported["corpus_hash"], reviewer=package.reviewer)
    item["metadata"]["basis"]["observed_at"] = package.sources[0].observed_at.isoformat()
    batch.update(collection_id="legacy-package", raw_payload={})
    legacy = CollectionBatch.model_validate(batch)
    chunk = ChunkInput(revision_id=legacy.items[0].revision_id, ordinal=0, text=package.notes[0].text,
                       source_locator=f"authored-note:{package.notes[0].id};basis:{package.notes[0].source_section}",
                       chunker_version="editorial-whole-paragraph-v1")
    with RagStore(tmp_path / "legacy") as store:
        store.import_collection(legacy)
        store.add_chunk(chunk)
        annotation.pop("annotation_id")
        annotation.update(chunk_id=chunk.chunk_id, tagging_policy_version=package.corpus_version)
        store.annotate(AnnotationInput.model_validate(annotation))
        later = observed + timedelta(seconds=1)
        store.annotate(AnnotationInput.model_validate({**annotation, "review_status": "rejected",
                                                       "created_at": later, "reviewed_at": later}))
        refreshed = package.model_copy(update={"corpus_version": "new-package", "authored_at": later,
                                               "reviewed_at": later, "reviewer": "new agent"})
        result = import_corpus(store, refreshed, allow_agent_reviewed=True, observed_at=later + timedelta(seconds=1))
        assert result["notes"][0]["revision_id"] == legacy.items[0].revision_id
        assert result["notes"][0]["chunk_id"] == chunk.chunk_id
        assert store.annotation_at(chunk.chunk_id, later + timedelta(seconds=1)) is None
        assert store.counts()["document_revisions"] == 1
        assert store.counts()["chunk_annotations"] == 2

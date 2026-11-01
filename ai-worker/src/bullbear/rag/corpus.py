"""Import versioned, source-linked editorial background without inventing old availability.

These are our authored explanations, NOT copied source documents or market facts.
Agent-reviewed material requires an explicit experimental opt-in, never human approval.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import (AnnotationInput, ChunkInput, CollectionBatch, DocumentInput,
                      canonical_url, digest, utc)
from .store import RagStore


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    url: str
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    published_on: date | None
    observed_at: datetime

    _url = field_validator("url")(canonical_url)
    _aware = field_validator("observed_at")(utc)

    @model_validator(mode="after")
    def not_future(self):
        if self.published_on and self.published_on > self.observed_at.date():
            raise ValueError("source publication date is after observation")
        return self


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1000)
    source_id: str
    source_section: str = Field(min_length=1)
    horizons: list[Literal["common", "short"]] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    applicability: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class Corpus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["knowledge-corpus-v1"]
    corpus_version: str = Field(min_length=1)
    release_status: Literal["experimental"]
    authored_at: datetime
    reviewed_at: datetime
    reviewer: str = Field(min_length=1)
    review_kind: Literal["agent_source_review"]
    human_reviewed: Literal[False]
    sources: list[Source] = Field(min_length=1)
    notes: list[Note] = Field(min_length=1)

    _aware = field_validator("authored_at", "reviewed_at")(utc)

    @model_validator(mode="after")
    def coherent(self):
        source_ids = {s.id for s in self.sources}
        if len(source_ids) != len(self.sources) or len({n.id for n in self.notes}) != len(self.notes):
            raise ValueError("duplicate corpus ids")
        if any(n.source_id not in source_ids or len(set(n.horizons)) != len(n.horizons) for n in self.notes):
            raise ValueError("invalid note source or horizons")
        if self.reviewed_at < self.authored_at or any(s.observed_at > self.reviewed_at for s in self.sources):
            raise ValueError("review must follow authorship and source observation")
        return self


def _note_fingerprint(note: Note, source: Source) -> str:
    # Collection/review times attest to this import, not a new authored paragraph.
    return digest({"note": note.model_dump(mode="json"),
                   "basis": source.model_dump(mode="json", exclude={"observed_at"})})


def _existing_note(store: RagStore, note: Note, fingerprint: str, observed: datetime):
    """Reuse immutable content, including its original authored time, when unchanged.

    Legacy corpus imports can be recognized from their original annotation. A
    missing original annotation is not evidence of approval: create a proposal.
    """
    reader = store.open_reader()
    try:
        rows = reader.execute(
            "SELECT r.revision_id FROM document_revisions r JOIN documents d USING(document_id) "
            "WHERE d.source='bullbear-editorial' AND d.source_item_id=? ORDER BY r.first_observed_at,r.revision_id",
            (note.id,)).fetchall()
        for row in rows:
            revision = store.revision(row["revision_id"])
            content = revision["content"]
            metadata = content["metadata"]
            saved_fingerprint = metadata.get("note_fingerprint")
            if saved_fingerprint is None:
                original = reader.execute(
                    "SELECT a.data_json FROM chunk_annotations a JOIN chunks c USING(chunk_id) "
                    "WHERE c.revision_id=? ORDER BY a.annotation_seq LIMIT 1", (row["revision_id"],)).fetchone()
                if original and "basis" in metadata:
                    annotation = json.loads(original[0])
                    basis = metadata["basis"]
                    legacy_note = Note(id=note.id, title=content["title"], text=content["text"],
                                       source_id=basis["id"], source_section=metadata["basis_section"],
                                       **{key: annotation[key] for key in (
                                           "horizons", "topics", "applicability", "limitations")})
                    saved_fingerprint = _note_fingerprint(legacy_note, Source.model_validate(basis))
            if saved_fingerprint == fingerprint and utc(datetime.fromisoformat(revision["first_observed_at"])) <= observed:
                return content, True
        return None, bool(rows)
    finally:
        reader.close()


def import_corpus(store: RagStore, corpus: Corpus, *, allow_agent_reviewed=False,
                  observed_at: datetime | None = None) -> dict:
    if not allow_agent_reviewed:
        raise ValueError("agent-reviewed corpus requires explicit experimental opt-in")
    observed = utc(observed_at or datetime.now(timezone.utc))
    if observed < corpus.reviewed_at:
        raise ValueError("cannot backdate observation before corpus review")
    payload = corpus.model_dump(mode="json")
    corpus_hash = digest(payload)
    sources = {s.id: s for s in corpus.sources}
    docs, changed, fingerprints = [], [], []
    for note in corpus.notes:
        source = sources[note.source_id]
        fingerprint = _note_fingerprint(note, source)
        previous, has_revision = _existing_note(store, note, fingerprint, observed)
        provenance = {"corpus_hash": corpus_hash, "corpus_version": corpus.corpus_version,
                      "authored_at": corpus.authored_at.isoformat(), "reviewed_at": corpus.reviewed_at.isoformat(),
                      "reviewer": corpus.reviewer, "basis_observed_at": source.observed_at.isoformat()}
        changed.append((has_revision and previous is None) or bool(
            previous and previous["metadata"].get("initial_review_status") == "proposed"))
        fingerprints.append(fingerprint)
        if previous is not None:
            docs.append(DocumentInput.model_validate({**previous, "observed_at": observed,
                                                       "source_payload": provenance}))
            continue
        docs.append(DocumentInput(
            source="bullbear-editorial", source_item_id=note.id, kind="knowledge",
            source_ref=f"editorial-note:{note.id}:{fingerprint}", url=source.url,
            title=note.title, text=note.text, publisher="Bull and Bear editorial notes (AI-authored)",
            published_at=observed if has_revision else corpus.authored_at, observed_at=observed, timestamp_precision="instant",
            content_level="full_text", publication_verified=True,
            source_payload=provenance,
            metadata={"authorship": "original_Korean_paraphrase_not_source_quote", "note_fingerprint": fingerprint,
                      "initial_review_status": "proposed" if has_revision else "approved",
                      "release_status": corpus.release_status, "review_kind": corpus.review_kind,
                      "human_reviewed": False,
                      "basis": source.model_dump(mode="json", exclude={"observed_at"}), "basis_section": note.source_section}))
    # All schema validation precedes writes. Interrupted imports are resumable;
    # changed notes stay proposed until an explicit note-level review is recorded.
    chunks = [ChunkInput(revision_id=doc.revision_id, ordinal=0, text=doc.text,
                         source_locator=f"authored-note:{note.id};basis:{note.source_section}",
                         chunker_version="editorial-whole-paragraph-v1") for doc, note in zip(docs, corpus.notes)]
    annotations = [AnnotationInput(
        chunk_id=chunk.chunk_id, horizons=tuple(note.horizons), topics=tuple(note.topics),
        markets=("global",), review_status="proposed" if needs_review else "approved",
        created_at=observed, reviewed_at=None if needs_review else observed,
        applicability=note.applicability, limitations=tuple(note.limitations),
        duplicate_group_id=note.id, tagging_policy_version="editorial-note-v2:"+fingerprint)
        for chunk, note, needs_review, fingerprint in zip(chunks, corpus.notes, changed, fingerprints)]
    batch = CollectionBatch(collection_id="CORPUS."+digest([corpus_hash, observed.isoformat()]),
                            source="bullbear-editorial", query_key=corpus.corpus_version,
                            window_start=observed, window_end=observed, started_at=observed,
                            finished_at=observed, observation_mode="current", status="completed",
                            coverage="complete", pages=1, items=tuple(docs), raw_payload={"corpus": payload})
    store.import_collection(batch)
    for chunk, annotation in zip(chunks, annotations):
        store.add_chunk(chunk)
        store.annotate(annotation, initial_only=True)
    return {"corpus_hash": corpus_hash, "corpus_version": corpus.corpus_version,
            "observation_at": observed.isoformat(), "human_reviewed": False,
            "release_status": "experimental", "notes": [
                {"id": note.id, "chunk_id": chunk.chunk_id, "revision_id": doc.revision_id}
                for note, chunk, doc in zip(corpus.notes, chunks, docs)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--allow-agent-reviewed", action="store_true")
    args = parser.parse_args(argv)
    corpus = Corpus.model_validate_json(args.corpus.read_text(encoding="utf-8"))
    from ..config import load_settings
    from .archive_repository import configured_archive
    with configured_archive(load_settings(), args.data_dir / "rag") as store:
        result = import_corpus(store, corpus, allow_agent_reviewed=args.allow_agent_reviewed)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

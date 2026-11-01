"""Bounded private HTTP observation; never replaces the primary context or emits SSE."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .archive_repository import configured_archive
from .context_repository import PostgresContextRepository
from .embeddings import EmbeddingService, EmbeddingSpec, OpenAIEmbeddings
from .index import GenerationIndex
from .retrieval import Retriever
from .selection import SelectionPolicy, focused_terms, query_text
from .schemas import digest, stamp
from .vectors import VectorIndex

log = logging.getLogger(__name__)


class ShadowRunner:
    def __init__(self, settings):
        self.settings = settings
        self.slot = threading.BoundedSemaphore(1)
        self.readers = threading.BoundedSemaphore(1)  # Never takes the primary reader semaphore.
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-shadow")
        self.spec = None
        self.selection_policy = None
        try:
            if not settings.rag_postgres_dsn or not settings.rag_shadow_spec:
                raise ValueError("shadow configuration missing")
            self.spec = EmbeddingSpec.model_validate_json(settings.rag_shadow_spec.read_text(encoding="utf-8"))
            if settings.rag_shadow_selection_policy:
                self.selection_policy = SelectionPolicy.model_validate_json(settings.rag_shadow_selection_policy.read_text(encoding="utf-8"))
                if self.selection_policy.embedding_version != self.spec.version_id:
                    raise ValueError("selection policy embedding version mismatch")
            if settings.rag_shadow_prepare_query and (
                    self.spec.provider != "openai" or self.spec.nano_usd_per_token <= 0
                    or settings.rag_shadow_daily_budget_nano <= 0):
                self.spec = None
        except Exception:
            self.spec = None

    def close(self):
        self.pool.shutdown(wait=True)

    def _write(self, run_id, payload):
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
                return
            directory = self.settings.data_dir / "rag-shadow"
            directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".shadow-", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, directory / f"{run_id}.json")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            # Observability failure must never turn a completed primary run into a failure.
            log.warning("shadow record persistence failed")

    def submit(self, run_id, snapshot, primary, generation_id):
        if not self.slot.acquire(blocking=False):
            self._write(run_id, {"schema": "rag-http-shadow-v1", "run_id": run_id,
                                "status": "skipped_capacity", "primary_unchanged": True})
            return False
        try:
            self.pool.submit(self._run, run_id, snapshot.model_copy(deep=True), primary, generation_id)
            return True
        except Exception:
            self.slot.release()
            self._write(run_id, {"schema": "rag-http-shadow-v1", "run_id": run_id,
                                "status": "submit_failed", "primary_unchanged": True})
            return False

    def _run(self, run_id, snapshot, primary, generation_id):
        started = time.perf_counter()
        record = {"schema": "rag-http-shadow-v1", "run_id": run_id, "status": "running",
            "snapshot_id": snapshot.snapshot_id, "snapshot_hash": digest(snapshot.model_dump(mode="json")),
            "decision_at": stamp(snapshot.created_at), "generation_id": generation_id,
            "started_at": stamp(datetime.now(timezone.utc)), "time_policy": "observed-v1",
            "primary_context_id": primary.context_id if primary else None,
            "primary_unchanged": True, "comparisons": []}
        provider = None
        try:
            self._write(run_id, record)
            if self.spec is None:
                record["status"] = "invalid_configuration"
                return
            record["embedding_version"] = self.spec.version_id
            record["selection_policy_id"] = self.selection_policy.policy_id if self.selection_policy else None
            if self.selection_policy and not focused_terms(snapshot):
                record["status"] = "no_supported_query"
                return
            service = EmbeddingService(self.settings.rag_postgres_dsn, self.spec)
            index = VectorIndex(service)
            # Check availability before any optional charged query preparation.
            with service.repository._connection() as db:
                ready = db.execute("SELECT ready_at FROM rag.vector_generations WHERE generation_id=%s AND version_id=%s",
                    (generation_id, self.spec.version_id)).fetchone()
            if ready is None or stamp(ready[0]) > stamp(snapshot.created_at):
                record["status"] = "generation_not_ready_at_decision"
                return
            with configured_archive(self.settings) as store:
                db, manifest = GenerationIndex(store).open(generation_id)
                db.close()
                if manifest["as_of"] > stamp(snapshot.created_at) or manifest["committed_at"] > stamp(snapshot.created_at):
                    record["status"] = "generation_not_ready_at_decision"
                    return
                if self.settings.rag_shadow_prepare_query:
                    provider = OpenAIEmbeddings()
                    service.provider = provider
                    query_id, _ = service.prepare(query_text(snapshot, self.selection_policy), "query",
                        daily_budget_nano=self.settings.rag_shadow_daily_budget_nano)
                    record["query_embedding_id"] = query_id
                else:
                    query_id, _ = service.cached(query_text(snapshot, self.selection_policy), "query")
                    record["query_embedding_id"] = query_id
                baseline = {item["chunk_id"] for item in primary.payload["items"]} if primary else set()
                for strategy in ("dense", "hybrid"):
                    at = time.perf_counter()
                    context = Retriever(store, strategy=strategy, vector_index=index, reader_slots=self.readers, selection_policy=self.selection_policy,
                        context_repository=PostgresContextRepository(self.settings.rag_postgres_dsn)).retrieve(
                            snapshot, generation_id=generation_id)
                    payload = context.payload
                    selected = {item["chunk_id"] for item in payload["items"]}
                    record["comparisons"].append({"strategy": strategy, "status": payload["status"],
                        "context_id": context.context_id, "selected_chunk_ids": sorted(selected),
                        "primary_overlap": len(selected & baseline), "added_chunk_ids": sorted(selected - baseline),
                        "removed_chunk_ids": sorted(baseline - selected), "warnings": payload.get("warnings", []),
                        "search_and_persist_seconds": time.perf_counter() - at})
                record["status"] = "completed" if all(r["status"] in {"completed", "empty"}
                    for r in record["comparisons"]) else "retrieval_failed"
        except Exception as exc:
            record["status"] = "shadow_unavailable"
            # Type name only; provider/DSN/private content strings are never logged.
            record["error_type"] = type(exc).__name__
        finally:
            try:
                if provider is not None and provider.client is not None:
                    provider.client.close()
            except Exception:
                pass
            record["elapsed_seconds"] = time.perf_counter() - started
            record["finished_at"] = stamp(datetime.now(timezone.utc))
            self._write(run_id, record)
            self.slot.release()

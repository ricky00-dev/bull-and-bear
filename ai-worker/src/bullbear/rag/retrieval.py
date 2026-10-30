"""Bounded, deterministic retrieval over a sealed FTS generation.

The caller freezes a timeout after one second even if an OS read stalls. At most
four daemon readers can be outstanding; they never write contexts or late results.
Persistence is outside the search deadline and must succeed before returning.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from .context import (KnowledgeContext, MAX_CHARS, MAX_TOKENS, PROFILE_VERSION,
                      SCHEMA_VERSION, render_items, token_upper_bound)
from .index import GenerationIndex, current_member, normalize
from .replay import load_context, save_context
from .schemas import digest, stamp

SEARCH_SECONDS = 1.0
CANDIDATES = 20
POLICY_VERSION = "filtered-bm25-v1"
_READERS = threading.BoundedSemaphore(4)
# Versioned, deliberately small alias set. No generated claims/news text in query.
ALIASES = {
    "per": ("per", "주가수익비율", "valuation"),
    "pbr": ("pbr", "주가순자산비율", "valuation"),
    "roe": ("roe", "자기자본이익률", "profitability"),
    "volatility": ("volatility", "변동성"),
    "revenue": ("revenue", "매출액", "earnings"),
    "operating": ("operating", "영업이익", "earnings"),
}


def query_terms(snapshot) -> list[str]:
    terms = {"kospi", "코스피", "초과수익", "거래일", "event_relevance"}
    terms.update(normalize(snapshot.name + " " + snapshot.ticker))
    for key, fact in sorted(snapshot.facts.items()):
        tokens = normalize(key.replace("_", " ") + " " + fact.label)
        terms.update(tokens)
        for concept, aliases in ALIASES.items():
            if concept in tokens or set(aliases) & set(tokens):
                terms.update(aliases)
    return sorted(terms)[:128]


class Retriever:
    def __init__(self, store):
        self.store = store

    def load_context(self, context_id):
        return load_context(self.store, context_id)

    def retrieve(self, snapshot, *, generation_id: str, time_policy="observed-v1"):
        if time_policy not in {"observed-v1", "reconstructed-v1"}:
            raise ValueError("unsupported retrieval time policy")
        # Detach the market input before the reader thread starts.
        snapshot = snapshot.model_copy(deep=True)
        cutoff = stamp(snapshot.created_at)
        terms = query_terms(snapshot)
        base = {"schema_version": SCHEMA_VERSION, "profile_version": PROFILE_VERSION,
                "snapshot_id": snapshot.snapshot_id, "snapshot_hash": digest(snapshot.model_dump(mode="json")),
                "decision_at": cutoff, "generation_id": generation_id, "time_policy": time_policy,
                "policy_version": POLICY_VERSION, "query_terms": terms,
                "market": "KR", "target": {"value": 7, "unit": "trading_day", "benchmark": "KOSPI"},
                "limits": {"common": 2, "short": 3, "candidates_per_path": CANDIDATES,
                           "characters": MAX_CHARS, "token_upper_bound": MAX_TOKENS,
                           "search_seconds": SEARCH_SECONDS},
                "token_accounting": "utf8_byte_upper_bound_not_actual_usage"}
        started = time.monotonic()
        deadline = started + SEARCH_SECONDS
        done, cancel = threading.Event(), threading.Event()
        output = []

        def check():
            if cancel.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("search deadline")

        def work():
            try:
                output.append(self._search(snapshot, generation_id, cutoff, terms, time_policy, check))
            except TimeoutError:
                output.append({"status": "timeout", "items": [], "warnings": ["search_deadline"]})
            except Exception:
                output.append({"status": "failed", "items": [], "warnings": ["retrieval_unavailable"]})
            finally:
                done.set()
                _READERS.release()

        if not _READERS.acquire(blocking=False):
            result = {"status": "failed", "items": [], "warnings": ["retrieval_busy"]}
        else:
            try:
                threading.Thread(target=work, daemon=True, name="rag-reader").start()
            except BaseException:
                _READERS.release()
                raise
            if done.wait(max(0, deadline - time.monotonic())) and output and time.monotonic() < deadline:
                result = output[0]
            else:
                cancel.set()
                result = {"status": "timeout", "items": [], "warnings": ["search_deadline"]}
        elapsed = time.monotonic() - started
        context = KnowledgeContext.from_payload({**base, **result})
        # Latency is attempt metadata, not part of the deterministic context ID.
        save_context(self.store, context, {"status": result["status"], "search_elapsed_seconds": elapsed,
                     "context_id": context.context_id, "generation_id": generation_id,
                     "candidates": result.get("candidates", []), "exclusions": result.get("exclusions", []),
                     "warnings": result.get("warnings", [])})
        return context

    def _search(self, snapshot, generation_id, cutoff, terms, time_policy, check):
        check()
        index = GenerationIndex(self.store)
        db, manifest = index.open(generation_id, check=check)
        reader = None
        try:
            if stamp(datetime.fromisoformat(manifest["as_of"])) > cutoff:
                return {"status": "failed", "items": [], "warnings": ["future_generation"]}
            if time_policy == "observed-v1" and stamp(datetime.fromisoformat(manifest["committed_at"])) > cutoff:
                return {"status": "failed", "items": [], "warnings": ["generation_not_committed_at_decision"]}
            reader = self.store.open_reader()
            reader.execute("PRAGMA busy_timeout=1")
            def progress():
                try:
                    check()
                    return 0
                except TimeoutError:
                    return 1
            for connection in (db, reader):
                connection.set_progress_handler(progress, 100)
            reader.execute("BEGIN")
            eligible, exclusions, candidates = {}, [], []
            for rowid, member in enumerate(manifest["members"], 1):
                check()
                live, reason = current_member(reader, self.store, member["chunk_id"], cutoff)
                if live and live != member:
                    live, reason = None, "pending_revision_or_annotation"
                if live and not (set(member["markets"]) & {"KR", "KOSPI", "global"}):
                    live, reason = None, "market"
                if live and member["tickers"] and snapshot.ticker not in member["tickers"]:
                    live, reason = None, "ticker"
                if live:
                    eligible[rowid] = member
                else:
                    exclusions.append({"chunk_id": member["chunk_id"], "reason": reason})
            selected, docs, texts, groups = [], set(), set(), set()
            match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            for path, limit in (("common", 2), ("short", 3)):
                check()
                grades = {str(key): 0 if member["tickers"] else 1 if set(member["markets"]) & {"KR", "KOSPI"} else 2
                          for key, member in eligible.items() if path in member["horizons"]}
                # Filtering rowids does not change the generation's BM25 corpus statistics.
                rows = db.execute(
                    "SELECT corpus.rowid,bm25(corpus) AS score,e.value AS grade FROM corpus "
                    "JOIN json_each(?) e ON corpus.rowid=CAST(e.key AS INTEGER) WHERE corpus MATCH ? "
                    "ORDER BY e.value,score,corpus.rowid LIMIT ?",
                    (json.dumps(grades), match, CANDIDATES)).fetchall() if grades else []
                count = 0
                for row in rows:
                    check()
                    member = eligible[row["rowid"]]
                    record = {"chunk_id": member["chunk_id"], "path": path, "bm25": row["score"],
                              "suitability_grade": row["grade"], "source_priority": "equal_reviewed_sources",
                              "candidate_rank": len([c for c in candidates if c["path"] == path]) + 1}
                    reason = "selected"
                    if member["document_id"] in docs or member["text_hash"] in texts or (
                            member["duplicate_group_id"] and member["duplicate_group_id"] in groups):
                        reason = "duplicate"
                    elif count >= limit:
                        reason = "path_limit"
                    item = {**member, "path": path, "role": "background_only", "bm25": row["score"]}
                    proposed = selected + [item]
                    if reason == "selected" and (sum(len(i["text"]) for i in proposed) > MAX_CHARS or
                            token_upper_bound(render_items(proposed)) > MAX_TOKENS):
                        reason = "context_budget"
                    record["reason"] = reason
                    candidates.append(record)
                    if reason == "selected":
                        selected.append(item)
                        docs.add(member["document_id"])
                        texts.add(member["text_hash"])
                        groups.add(member["duplicate_group_id"])
                        count += 1
            check()
            return {"status": "completed" if selected else "empty", "items": selected,
                    "warnings": ["historical_reconstruction"] if time_policy == "reconstructed-v1" else [],
                    "generation_as_of": manifest["as_of"], "generation_committed_at": manifest["committed_at"],
                    "candidates": candidates, "exclusions": exclusions}
        finally:
            db.close()
            if reader is not None:
                reader.close()

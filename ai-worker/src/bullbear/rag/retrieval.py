"""Bounded, deterministic retrieval over a sealed FTS generation.

The caller freezes a timeout after one second even if an OS read stalls. At most
four daemon readers can be outstanding; they never write contexts or late results.
Persistence is outside the search deadline and must succeed before returning.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from datetime import datetime

from .context import (KnowledgeContext, MAX_CHARS, MAX_TOKENS, PROFILE_VERSION,
                      SCHEMA_VERSION, render_items, token_upper_bound)
from .index import GenerationIndex, current_member, normalize
from .replay import load_context, save_context
from .schemas import digest, stamp
from .store import ArchiveCorruptError

SEARCH_SECONDS = 1.0
CANDIDATES = 20
POLICY_VERSION = "filtered-bm25-v3-concept-priority"
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
# Only curated spellings and complete Korean particles, never general stemming.
_SPACED_ALIASES = {
    "주가수익비율": r"주가\s*수익\s*비율",
    "주가순자산비율": r"주가\s*순자산\s*비율",
    "자기자본이익률": r"자기\s*자본\s*이익률",
}
_PARTICLES = r"(?:으로|에서|까지|부터|은|는|이|가|을|를|의|에|와|과|로|도|만)?"
_ALIAS_PATTERNS = {
    concept: re.compile(r"(?<!\w)(?:" + "|".join(_SPACED_ALIASES.get(alias, re.escape(alias))
                                               for alias in aliases) + ")" + _PARTICLES + r"(?!\w)")
    for concept, aliases in ALIASES.items()
}


def query_terms(snapshot) -> list[str]:
    # Budget by meaning before lexicographic tie-breaking. News/disclosure IDs
    # and headlines are market facts, not background concept vocabulary; a full
    # daily snapshot must not evict PER/volatility just by carrying more articles.
    target = {"kospi", "코스피", "초과수익", "거래일", "event_relevance"}
    identity = normalize(snapshot.ticker) + normalize(snapshot.name)[:8]
    aliases_found, concepts = set(), set()
    categories = {fact.category for fact in snapshot.facts.values()}
    if "news" in categories:
        concepts.update(("news", "뉴스"))
    if "disclosure" in categories:
        concepts.update(("disclosure", "공시"))
    for key, fact in sorted(snapshot.facts.items()):
        if fact.category in {"news", "disclosure"}:
            continue
        concept_text = unicodedata.normalize("NFC", key.replace("_", " ") + " " + fact.label).lower()
        tokens = normalize(concept_text)
        concepts.update(token for token in tokens
                        if token not in {"px", "fin", "val", "eval", "probe"}
                        and not token.isdecimal()
                        and not re.fullmatch(r"[0-9a-f]{8,}|(?:\d{4})?(?:h[12]|q[1-4]|fy)", token))
        for concept, aliases in ALIASES.items():
            if concept in tokens or set(aliases) & set(tokens) or _ALIAS_PATTERNS[concept].search(concept_text):
                aliases_found.update(aliases)
    ranked = dict.fromkeys([*sorted(target), *identity, *sorted(aliases_found), *sorted(concepts)])
    return list(ranked)[:128]


class Retriever:
    def __init__(self, store, *, context_repository=None, strategy="bm25", vector_index=None, reader_slots=None, selection_policy=None):
        if strategy not in {"bm25", "dense", "hybrid"} or (strategy != "bm25" and vector_index is None):
            raise ValueError("invalid retrieval strategy or missing vector index")
        if selection_policy is not None and strategy != "bm25" and selection_policy.embedding_version != vector_index.version_id:
            raise ValueError("selection policy embedding version mismatch")
        self.selection_policy = selection_policy
        self.reader_slots = reader_slots if reader_slots is not None else _READERS
        self.strategy, self.vector_index = strategy, vector_index
        self.store = store
        self.context_repository = context_repository

    def load_context(self, context_id):
        return load_context(self.store, context_id, repository=self.context_repository)

    def retrieve(self, snapshot, *, generation_id: str, time_policy="observed-v1", request=None, generation_binding=None):
        if time_policy not in {"observed-v1", "reconstructed-v1"}:
            raise ValueError("unsupported retrieval time policy")
        # Detach the market input before the reader thread starts.
        snapshot = snapshot.model_copy(deep=True)
        cutoff = stamp(snapshot.created_at)
        from .selection import focused_terms
        evidence = None
        if request is not None:
            from .evidence import parse_request, assess
            request = parse_request(request)
            evidence = assess(snapshot, request)
        terms = focused_terms(snapshot) if self.selection_policy else query_terms(snapshot)
        base = {"schema_version": SCHEMA_VERSION, "profile_version": PROFILE_VERSION,
                "snapshot_id": snapshot.snapshot_id, "snapshot_hash": digest(snapshot.model_dump(mode="json")),
                "decision_at": cutoff, "generation_id": generation_id, "time_policy": time_policy,
                "policy_version": POLICY_VERSION, "query_terms": terms,
                "market": "KR", "target": {"value": 7, "unit": "trading_day", "benchmark": "KOSPI"},
                "limits": {"common": 2, "short": 3, "candidates_per_path": CANDIDATES,
                           "characters": MAX_CHARS, "token_upper_bound": MAX_TOKENS,
                           "search_seconds": SEARCH_SECONDS},
                "token_accounting": "utf8_byte_upper_bound_not_actual_usage"}
        if self.strategy != "bm25":
            base.update(strategy=self.strategy, embedding_version=self.vector_index.version_id,
                        policy_version="filtered-pgvector-rrf-v1", fusion_constant=60 if self.strategy == "hybrid" else None)
        if generation_binding is not None:
            base['generation_binding'] = generation_binding
        if self.selection_policy:
            base.update(selection_policy=self.selection_policy.model_dump(mode="json"),
                        selection_policy_id=self.selection_policy.policy_id, query_policy="focused-labels-v1")
        if evidence is not None:
            base["evidence"] = evidence
            if evidence["route"] != "background":
                context = KnowledgeContext.from_payload({**base, "status": "empty", "items": [],
                    "warnings": [], "answerability": evidence["answerability"],
                    "abstention_reason": evidence["reasons"][0] if evidence["reasons"] else None})
                save_context(self.store, context, {"status": "empty", "context_id": context.context_id,
                    "generation_id": generation_id, "evidence": evidence}, repository=self.context_repository)
                return context
            from ..snapshot import Fact
            probe = snapshot.model_copy(update={"facts": {"QUERY": Fact(id="QUERY", category="valuation",
                label=request.question, value=None, unit="text", as_of=snapshot.as_of, source="explicit_question")}})
            terms = focused_terms(probe)
            base["query_terms"] = terms
            base["query_policy"] = "explicit-question-v1"
        started = time.monotonic()
        deadline = started + SEARCH_SECONDS
        done, cancel = threading.Event(), threading.Event()
        output = []

        def check():
            if cancel.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("search deadline")

        def work():
            try:
                output.append(self._search(snapshot, generation_id, cutoff, terms, time_policy, check,
                    **({'generation_binding': generation_binding} if generation_binding is not None else {}),
                    **({"query_override": request.question} if request is not None else {})))
            except TimeoutError:
                output.append({"status": "timeout", "items": [], "warnings": ["search_deadline"]})
            except ArchiveCorruptError:
                output.append({"status": "failed", "items": [], "warnings": ["integrity_error"]})
            except Exception:
                output.append({"status": "failed", "items": [], "warnings": ["retrieval_unavailable"]})
            finally:
                done.set()
                self.reader_slots.release()

        if not self.reader_slots.acquire(blocking=False):
            result = {"status": "failed", "items": [], "warnings": ["retrieval_busy"]}
        else:
            try:
                threading.Thread(target=work, daemon=True, name="rag-reader").start()
            except BaseException:
                self.reader_slots.release()
                raise
            if done.wait(max(0, deadline - time.monotonic())) and output and time.monotonic() < deadline:
                result = output[0]
            else:
                cancel.set()
                result = {"status": "timeout", "items": [], "warnings": ["search_deadline"]}
        elapsed = time.monotonic() - started
        if evidence is not None:
            evidence = {**evidence, "answerability": ("documents_found" if result["status"] == "completed"
                else "no_documents" if result["status"] == "empty" else "retrieval_failed")}
            result.update(evidence=evidence, answerability=evidence["answerability"])
        context = KnowledgeContext.from_payload({**base, **result})
        # Latency is attempt metadata, not part of the deterministic context ID.
        save_context(self.store, context, {"status": result["status"], "search_elapsed_seconds": elapsed,
                     "context_id": context.context_id, "generation_id": generation_id,
                     "candidates": result.get("candidates", []), "exclusions": result.get("exclusions", []),
                     "warnings": result.get("warnings", [])}, repository=self.context_repository)
        return context

    def _search(self, snapshot, generation_id, cutoff, terms, time_policy, check, query_override=None, generation_binding=None):
        check()
        if generation_binding is not None and generation_binding.get('state') != 'bound':
            return {'status': 'failed', 'items': [], 'warnings': ['snapshot_generation_unavailable']}
        index = GenerationIndex(self.store)
        db, manifest = index.open(generation_id, check=check)
        reader = None
        try:
            if generation_binding is not None:
                from .binding import validate_binding
                if time_policy != 'observed-v1':
                    raise ValueError('bound snapshots require observed policy')
                validate_binding(generation_binding, snapshot, generation_id, manifest)
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
            from .selection import query_text
            if self.selection_policy and not terms:
                return {"status": "empty", "items": [], "candidates": [], "exclusions": exclusions,
                        "warnings": ["historical_reconstruction"] if time_policy == "reconstructed-v1" else [],
                        "answerability": "abstain", "abstention_reason": "no_supported_query",
                        "generation_as_of": manifest["as_of"], "generation_committed_at": manifest["committed_at"]}
            vector_metadata = {}
            distances = {}
            if self.strategy != "bm25":
                distances, vector_metadata = self.vector_index.distances(eligible, generation_id, manifest,
                    (query_override if query_override is not None else query_text(snapshot, self.selection_policy)), cutoff=cutoff, time_policy=time_policy)
                check()
            from .selection import gate
            best_distance = min(distances.values(), default=2.0)
            selected, docs, texts, groups = [], set(), set(), set()
            match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            global_lexical = 0
            if self.selection_policy and match and eligible:
                scores = db.execute("SELECT bm25(corpus) AS score FROM corpus JOIN json_each(?) e ON corpus.rowid=CAST(e.value AS INTEGER) WHERE corpus MATCH ?",
                    (json.dumps(list(eligible)), match)).fetchall()
                global_lexical = max((abs(r["score"]) for r in scores), default=0)
            for path, limit in (("common", 2), ("short", 3)):
                check()
                grades = {str(key): 0 if member["tickers"] else 1 if set(member["markets"]) & {"KR", "KOSPI"} else 2
                          for key, member in eligible.items() if path in member["horizons"]}
                # Filtering rowids does not change the generation's BM25 corpus statistics.
                rows = db.execute(
                    "SELECT corpus.rowid,bm25(corpus) AS score,e.value AS grade FROM corpus "
                    "JOIN json_each(?) e ON corpus.rowid=CAST(e.key AS INTEGER) WHERE corpus MATCH ? "
                    "ORDER BY e.value,score,corpus.rowid LIMIT ?",
                    (json.dumps(grades), match, CANDIDATES)).fetchall() if grades and match else []
                if self.strategy != "bm25":
                    from .vectors import ranked_rows
                    rows = ranked_rows(rows, grades, distances, self.strategy, limit=CANDIDATES)
                best_lexical = global_lexical if self.selection_policy else 0
                count = 0
                for row in rows:
                    check()
                    member = eligible[row["rowid"]]
                    record = {"chunk_id": member["chunk_id"], "path": path, "bm25": row["score"],
                              "suitability_grade": row["grade"], "source_priority": "equal_reviewed_sources",
                              "candidate_rank": len([c for c in candidates if c["path"] == path]) + 1}
                    if self.strategy != "bm25":
                        record.update(cosine_distance=row["cosine_distance"], rrf=row["rrf"])
                    reason = (gate(self.selection_policy, self.strategy, member, row, terms,
                                   best_distance, best_lexical) if self.selection_policy else "selected")
                    if reason == "selected" and self.selection_policy and len(selected) >= self.selection_policy.max_items:
                        reason = "selection_limit"
                    if reason == "selected" and (member["document_id"] in docs or member["text_hash"] in texts or (
                            member["duplicate_group_id"] and member["duplicate_group_id"] in groups)):
                        reason = "duplicate"
                    elif reason == "selected" and count >= limit:
                        reason = "path_limit"
                    item = {**member, "path": path, "role": "background_only", "bm25": row["score"]}
                    if self.strategy != "bm25":
                        item.update(cosine_distance=row["cosine_distance"], rrf=row["rrf"])
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
                    "candidates": candidates, "exclusions": exclusions, **vector_metadata,
                    **({"answerability": "supported_background" if selected else "abstain",
                        "abstention_reason": None if selected else "no_supported_candidates"}
                       if self.selection_policy else {})}
        finally:
            db.close()
            if reader is not None:
                reader.close()

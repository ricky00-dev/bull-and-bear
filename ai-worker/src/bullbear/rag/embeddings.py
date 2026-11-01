"""Versioned embeddings with budget reservations; query-time retrieval is cache-only."""
from __future__ import annotations

import json
import math
import struct
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .context_repository import PostgresContextRepository
from .objects import ArchiveCorruptError
from .schemas import canonical_json, digest


class EmbeddingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["openai", "fixture"]
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)  # Application contract revision, not a weight snapshot claim.
    dimensions: int = Field(ge=1, le=16000)
    preprocessing: Literal["identity-v1"] = "identity-v1"
    document_prefix: str = ""
    query_prefix: str = ""
    price_revision: str = Field(min_length=1)
    nano_usd_per_token: int = Field(ge=0, le=1000000)

    @property
    def version_id(self):
        return "EMV." + digest(self.semantic_spec())

    def semantic_spec(self):
        return self.model_dump(mode="json", exclude={"price_revision", "nano_usd_per_token"})


class EmbeddingUnavailable(RuntimeError):
    pass


class BudgetExceeded(EmbeddingUnavailable):
    pass


class Provider(Protocol):
    def embed(self, spec: EmbeddingSpec, text: str) -> tuple[list[float], int]: ...


class OpenAIEmbeddings:
    def __init__(self, client=None):
        self.client = client

    def validate(self, spec):
        if spec.provider != "openai" or spec.nano_usd_per_token <= 0:
            raise ValueError("a positive configured API price is required")
        if self.client is None:
            try:
                from openai import OpenAI
                self.client = OpenAI(max_retries=0, timeout=20)
            except Exception:
                raise EmbeddingUnavailable("embedding client configuration unavailable") from None

    def embed(self, spec, text):
        self.validate(spec)
        response = self.client.embeddings.create(model=spec.model, input=[text],
            dimensions=spec.dimensions, encoding_format="float")
        if response.model != spec.model or len(response.data) != 1 or response.data[0].index != 0:
            raise EmbeddingUnavailable("embedding response identity mismatch")
        return response.data[0].embedding, response.usage.prompt_tokens


def checked_vector(values, dimensions):
    if len(values) != dimensions or any(isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("invalid embedding dimensions or values")
    # pgvector stores float32; hash and compare those exact values, not float64 inputs.
    result = [struct.unpack("!f", struct.pack("!f", float(v)))[0] for v in values]
    if not all(math.isfinite(v) for v in result) or not any(result):
        raise ValueError("zero or non-finite embedding")
    return result


class EmbeddingService:
    def __init__(self, dsn, spec, provider=None):
        self.repository = PostgresContextRepository(dsn)
        self.spec = spec
        self.provider = provider

    def input(self, text, role):
        if role not in {"document", "query"} or not text.strip():
            raise ValueError("invalid embedding input")
        text = (self.spec.document_prefix if role == "document" else self.spec.query_prefix) + text
        bound = len(text.encode("utf-8"))
        # Conservative byte bound avoids model-specific tokenizers and truncation.
        if bound > 8191:
            raise ValueError("embedding input exceeds conservative token bound")
        return text, bound, "EMB." + digest([self.spec.version_id, role, digest(text)])

    def cached(self, text, role):
        _, _, key = self.input(text, role)
        with self.repository._connection() as db:
            row = db.execute("SELECT version_id,vector_json,vector_hash FROM rag.embeddings WHERE embedding_id=%s", (key,)).fetchone()
        if row is None:
            raise EmbeddingUnavailable("embedding not prepared")
        vector = checked_vector(json.loads(row[1]), self.spec.dimensions)
        if row[0] != self.spec.version_id or digest(vector) != row[2]:
            raise ArchiveCorruptError("cached embedding integrity failure")
        return key, vector

    def prepare(self, text, role, *, daily_budget_nano):
        if not isinstance(daily_budget_nano, int) or daily_budget_nano < 0 or self.provider is None:
            raise ValueError("explicit embedding budget and provider required")
        try:
            return self.cached(text, role)
        except EmbeddingUnavailable:
            pass
        if hasattr(self.provider, "validate"):
            self.provider.validate(self.spec)
        prepared, bound, key = self.input(text, role)
        reserved = bound * self.spec.nano_usd_per_token
        with self.repository._connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(7348201103)")
            # All versions and workers share the daily budget, including unknown outcomes.
            spent = db.execute("""SELECT COALESCE(SUM(CASE WHEN r.call_id IS NULL THEN c.reserved_nano
                ELSE r.cost_nano END),0) FROM rag.embedding_calls c LEFT JOIN rag.embedding_receipts r USING(call_id)
                WHERE c.created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""").fetchone()[0]
            old = db.execute("SELECT 1 FROM rag.embedding_calls WHERE call_id=%s", (key,)).fetchone()
            if old:
                # Includes concurrent in-flight and unknown/failed calls: never auto-repeat billing.
                raise EmbeddingUnavailable("embedding call already reserved; inspect ledger")
            if spent + reserved > daily_budget_nano:
                raise BudgetExceeded("embedding daily budget exceeded")
            spec_json = canonical_json(self.spec.semantic_spec())
            db.execute("INSERT INTO rag.embedding_versions VALUES (%s,%s) ON CONFLICT DO NOTHING", (self.spec.version_id, spec_json))
            if db.execute("SELECT spec_json FROM rag.embedding_versions WHERE version_id=%s", (self.spec.version_id,)).fetchone()[0] != spec_json:
                raise ArchiveCorruptError("embedding version conflict")
            db.execute("INSERT INTO rag.embedding_calls(call_id,version_id,input_hash,role,reserved_nano,token_bound,price_revision,nano_usd_per_token) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                       (key, self.spec.version_id, digest(prepared), role, reserved, bound, self.spec.price_revision, self.spec.nano_usd_per_token))
        try:
            values, tokens = self.provider.embed(self.spec, prepared)
            if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
                raise ValueError("invalid usage")
        except Exception:
            # Keep reservation charged when provider usage is unknown, even after process death.
            raise EmbeddingUnavailable("embedding outcome unknown; reservation retained") from None
        try:
            vector = checked_vector(values, self.spec.dimensions)
            valid = tokens <= bound
        except (ValueError, TypeError, OverflowError):
            valid, vector = False, None
        with self.repository._connection() as db:
            db.execute("INSERT INTO rag.embedding_receipts(call_id,input_tokens,cost_nano,status) VALUES (%s,%s,%s,%s)",
                       (key, tokens, tokens * self.spec.nano_usd_per_token, "completed" if valid else "invalid_response"))
            if valid:
                db.execute("INSERT INTO rag.embeddings(embedding_id,version_id,vector_json,vector_hash) VALUES (%s,%s,%s,%s)",
                    (key, self.spec.version_id, canonical_json(vector), digest(vector)))
        if not valid:
            raise EmbeddingUnavailable("invalid vector or token bound; usage recorded")
        return key, vector

    def ledger(self):
        with self.repository._connection() as db:
            rows = db.execute("""SELECT c.version_id,COUNT(*),SUM(c.reserved_nano),
                COALESCE(SUM(r.cost_nano),0),SUM(CASE WHEN r.call_id IS NULL THEN 1 ELSE 0 END),
                COALESCE(SUM(r.input_tokens),0) FROM rag.embedding_calls c
                LEFT JOIN rag.embedding_receipts r USING(call_id) GROUP BY c.version_id ORDER BY c.version_id""").fetchall()
        return [dict(zip(("version_id", "calls", "reserved_nano", "measured_cost_nano", "unknown_calls", "input_tokens"),
                         [row[0], *map(int, row[1:])])) for row in rows]

"""Durable authorization ledger for bounded, text-only OpenAI benchmarks.

Reserve the model's entire possible input window before every paid request.
This deliberately costs more headroom than an estimated prompt, but a tokenizer
estimate cannot weaken the monetary cap. Missing responses retain reservations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

NANO = 1_000_000_000
TOKEN_POLICY = "json-utf8-envelope-reasoning-upper-v1"


class BudgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelPrice:
    version: str = "openai-standard-usd-2026-10-30-v1"
    provider: str = "openai"
    model: str = "gpt-5-mini"
    actual_models: tuple[str, ...] = ("gpt-5-mini", "gpt-5-mini-2025-08-07")
    input_nano_per_token: int = 250
    cached_nano_per_token: int = 25
    output_nano_per_token: int = 2000
    context_window: int = 400000
    max_output_tokens: int = 128000
    source: str = "https://developers.openai.com/api/docs/models/gpt-5-mini"
    pricing_source: str = "https://developers.openai.com/api/docs/pricing"

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


PRICE = ModelPrice()


def amount_nano(value) -> int:
    try:
        amount = Decimal(str(value)) * NANO
    except (InvalidOperation, ValueError):
        raise ValueError("invalid USD limit") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("USD limit must be positive with at most 9 decimals")
    return int(amount)


def input_upper_bound(request: dict, output_limit: int) -> int:
    """Conservative text envelope estimate, never an actual model-token count.

Encrypted reasoning has hidden tokenization: reserve the previous per-response
output allowance for every replayed reasoning item as well as its visible bytes.
No images, hosted tools, previous_response_id or server conversation are allowed.
"""
    if any(request.get(k) for k in ("previous_response_id", "conversation", "background")):
        raise BudgetError("server-side or background inputs are not budgeted")
    if request.get("service_tier", "default") != "default":
        raise BudgetError("only standard service pricing is budgeted")
    if request.get("truncation", "disabled") != "disabled":
        raise BudgetError("automatic input truncation is not allowed")
    if any(t.get("type") != "function" for t in request.get("tools", [])):
        raise BudgetError("hosted tool fees are not budgeted")
    reasoning = 0
    nodes = 0

    def inspect(value):
        nonlocal reasoning, nodes
        if isinstance(value, dict):
            nodes += 1
            kind = value.get("type")
            if isinstance(kind, str) and kind in {"input_image", "input_audio", "input_file", "computer_screenshot"}:
                raise BudgetError("only local text inputs are budgeted")
            if kind == "reasoning":
                reasoning += 1
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(request)
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    return len(encoded) + 4096 + 128 * nodes + reasoning * output_limit


class SpendLedger:
    def __init__(self, path, authorization_id: str, max_usd, *, price=PRICE):
        if not authorization_id or len(authorization_id) > 200:
            raise ValueError("authorization id required")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.authorization_id = authorization_id
        self.limit = amount_nano(max_usd)
        self.price = price
        with self._connect() as db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS authorizations(id TEXT PRIMARY KEY,limit_nano INTEGER NOT NULL,"
                "price_hash TEXT NOT NULL,halted INTEGER NOT NULL DEFAULT 0);"
                "CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL,"
                "scope TEXT NOT NULL,status TEXT NOT NULL,reserved_nano INTEGER NOT NULL,actual_nano INTEGER,"
                "estimated_input INTEGER NOT NULL,output_limit INTEGER NOT NULL,usage_json TEXT,reason TEXT);"
                "CREATE INDEX IF NOT EXISTS requests_authorization ON requests(authorization_id);")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO authorizations(id,limit_nano,price_hash) VALUES (?,?,?)",
                       (authorization_id, self.limit, price.fingerprint))
            row = db.execute("SELECT limit_nano,price_hash FROM authorizations WHERE id=?", (authorization_id,)).fetchone()
            if tuple(row) != (self.limit, price.fingerprint):
                raise BudgetError("authorization limit or price version changed")

    def _connect(self):
        # A connection context normally does not close; this owned wrapper does.
        return _Connection(self.path)

    def reserve(self, request: dict, *, scope: str) -> str:
        if request.get("model") not in self.price.actual_models:
            raise BudgetError("model has no authorized price")
        output = request.get("max_output_tokens")
        if type(output) is not int or not 1 <= output <= self.price.max_output_tokens:
            raise BudgetError("explicit valid output limit required")
        estimate = input_upper_bound(request, output)
        if estimate + output > self.price.context_window:
            raise BudgetError("input and reserved output exceed model context")
        # Ignore prospective cache discounts. The server's context limit bounds
        # paid input even if local envelope counting is imperfect.
        reserved = ((self.price.context_window-output) * self.price.input_nano_per_token
                    + output * self.price.output_nano_per_token)
        request_id = "REQ." + uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            auth = db.execute("SELECT halted FROM authorizations WHERE id=?", (self.authorization_id,)).fetchone()
            spent = db.execute("SELECT COALESCE(SUM(COALESCE(actual_nano,reserved_nano)),0) FROM requests "
                               "WHERE authorization_id=?", (self.authorization_id,)).fetchone()[0]
            if auth[0] or spent + reserved > self.limit:
                raise BudgetError("authorization budget exhausted or halted")
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (request_id, self.authorization_id, scope, "reserved", reserved, None, estimate, output, None, None))
        return request_id

    def settle(self, request_id: str, response) -> None:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", None)
        if usage is None:
            self.unconfirmed(request_id, "missing_usage")
            return
        data = usage.model_dump(mode="json") if hasattr(usage, "model_dump") else vars(usage)
        details = data.get("input_tokens_details") or {}
        if not isinstance(details, dict):
            details = vars(details)
        values = (data.get("input_tokens"), data.get("output_tokens"), details.get("cached_tokens", 0))
        valid = all(type(n) is int and n >= 0 for n in values)
        if model not in self.price.actual_models or not valid or values[2] > values[0]:
            self.unconfirmed(request_id, "unpriced_or_invalid_usage", halt=True)
            raise BudgetError("response model or usage cannot be priced")
        inputs, outputs, cached = values
        actual = ((inputs-cached)*self.price.input_nano_per_token + cached*self.price.cached_nano_per_token
                  + outputs*self.price.output_nano_per_token)
        violation = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved_nano,output_limit,status FROM requests WHERE id=? AND authorization_id=?",
                             (request_id, self.authorization_id)).fetchone()
            if row is None or row[2] not in {"reserved", "unconfirmed"}:
                raise BudgetError("request already settled or unknown")
            violation = actual > row[0] or outputs > row[1] or inputs+outputs > self.price.context_window
            if violation:
                db.execute("UPDATE authorizations SET halted=1 WHERE id=?", (self.authorization_id,))
            db.execute("UPDATE requests SET status=?,actual_nano=?,usage_json=?,reason=? WHERE id=?",
                       ("violated" if violation else "settled", actual,
                        json.dumps({"model": model, "input_tokens": inputs, "output_tokens": outputs,
                                    "cached_tokens": cached}), "reservation_exceeded" if violation else None, request_id))
        if violation:
            raise BudgetError("provider usage exceeded reserved limits")

    def unconfirmed(self, request_id: str, reason="response_unconfirmed", *, halt=False):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE requests SET status='unconfirmed',reason=? WHERE id=? AND authorization_id=? AND status='reserved'",
                       (reason, request_id, self.authorization_id))
            if halt:
                db.execute("UPDATE authorizations SET halted=1 WHERE id=?", (self.authorization_id,))

    def summary(self, scope=None):
        with self._connect() as db:
            where = "authorization_id=?" + (" AND scope=?" if scope is not None else "")
            args = (self.authorization_id, scope) if scope is not None else (self.authorization_id,)
            rows = db.execute("SELECT status,reserved_nano,actual_nano FROM requests WHERE " + where, args).fetchall()
            halted = bool(db.execute("SELECT halted FROM authorizations WHERE id=?", (self.authorization_id,)).fetchone()[0])
        unknown = sum(row[2] is None for row in rows)
        known = sum(row[2] or 0 for row in rows)
        held = sum(row[1] for row in rows if row[2] is None)
        return {"authorization_id": self.authorization_id, "max_usd": self.limit/NANO,
                "price_version": self.price.version, "price_hash": self.price.fingerprint,
                "token_policy": TOKEN_POLICY, "requests": len(rows), "unconfirmed_requests": unknown,
                "known_cost_usd": known/NANO, "reserved_unconfirmed_usd": held/NANO,
                "accounted_upper_usd": (known+held)/NANO, "halted": halted,
                "cost_usd": None if unknown else known/NANO,
                "cost_status": "partial_unconfirmed_requests" if unknown else "priced_actual_usage"}


class _Connection:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")

    def __enter__(self):
        return self.db

    def __exit__(self, kind, value, tb):
        try:
            self.db.rollback() if kind else self.db.commit()
        finally:
            self.db.close()

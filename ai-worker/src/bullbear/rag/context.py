"""Immutable private knowledge input. It never changes Snapshot or public evidence."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .schemas import canonical_json, digest

SCHEMA_VERSION = "knowledge-context-v1"
PROFILE_VERSION = "knowledge-short-v1"
MAX_CHARS = 6000
MAX_TOKENS = 2000
RENDER_VERSION = "compact-json-utf8-upper-v1"


def render_items(items: list[dict]) -> str:
    if not items:
        return ""
    data = [{"label": f"K{i}", "text": item["text"],
             "horizons": item["horizons"], "applicability": item["applicability"],
             "limitations": item["limitations"], "study_scope": item["study_scope"]}
            for i, item in enumerate(items, 1)]
    return "PRIVATE_BACKGROUND_DATA\n" + canonical_json(data)


def token_upper_bound(rendered: str) -> int:
    # UTF-8 byte length is a conservative byte-fallback tokenizer bound, NOT
    # measured model token usage. Metadata and the data envelope are included.
    return len(rendered.encode("utf-8"))


@dataclass(frozen=True)
class KnowledgeContext:
    payload_json: str

    def __post_init__(self):
        data = json.loads(self.payload_json)
        if canonical_json(data) != self.payload_json:
            raise ValueError("context must use canonical JSON")
        if data.get("schema_version") != SCHEMA_VERSION or data.get("profile_version") != PROFILE_VERSION:
            raise ValueError("unsupported knowledge schema/profile")
        if not data.get("snapshot_id") or not data.get("decision_at"):
            raise ValueError("context must identify frozen snapshot and decision time")
        if data.get("status") not in {"completed", "empty", "timeout", "failed"}:
            raise ValueError("invalid retrieval status")
        items = data.get("items", [])
        if len(items) > 5 or (data["status"] != "completed" and items):
            raise ValueError("invalid selected items")
        if sum(len(item["text"]) for item in items) > MAX_CHARS:
            raise ValueError("context character limit exceeded")
        if any(item.get("kind") not in {"knowledge", "research"} for item in items):
            raise ValueError("market facts cannot be knowledge background")
        counts = {"common": 0, "short": 0}
        for item in items:
            path = item.get("path")
            if path is None:
                path = next((p for p, cap in (("common", 2), ("short", 3))
                             if p in item["horizons"] and counts[p] < cap), None)
            if path not in counts or path not in item["horizons"]:
                raise ValueError("invalid knowledge path")
            counts[path] += 1
        if counts["common"] > 2 or counts["short"] > 3:
            raise ValueError("knowledge path limit exceeded")
        if token_upper_bound(render_items(items)) > MAX_TOKENS:
            raise ValueError("context token upper bound exceeded")

    @classmethod
    def from_payload(cls, payload: dict) -> KnowledgeContext:
        return cls(canonical_json(payload))

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def context_id(self) -> str:
        return "KCTX." + digest(self.payload)

    @property
    def snapshot_id(self) -> str:
        return self.payload["snapshot_id"]

    @property
    def rendered(self) -> str:
        return render_items(self.payload["items"])


def render_background(context: KnowledgeContext | None) -> str:
    return context.rendered if context else ""


def run_fingerprint(snapshot_hash: str, context: KnowledgeContext | None, *, models: dict,
                    versions: dict, condition: str) -> str:
    return digest({"snapshot_hash": snapshot_hash, "context_id": context.context_id if context else None,
                   "models": models, "versions": versions, "condition": condition})

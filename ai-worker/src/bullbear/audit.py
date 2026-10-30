"""Private, durable run provenance; never serialize environment or exception text.

Each run owns its directory. Atomic replacements expose either the previous or
the next complete manifest, and fsync completes before the next paid call starts.
An unfinished manifest is evidence of interruption, not a resumable checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import prompts, schemas, semantic
from .snapshot import KST

SECRET_ENV_NAMES = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENDART_API_KEY", "KRX_API_KEY",
    "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "WORKER_TOKEN",
)
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens", "requests")
_KEY_PATTERN = re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{8,})\b")
_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|x-api-key|api[_-]?key|access[_-]?token|client[_-]?secret)"
    r"([\s\"']*[:=][\s\"']*)(?:bearer\s+)?[^\s\"'&,}]+"
)


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError("Unsupported audit value")


def canonical_hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=_json_default).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def code_revision() -> dict:
    root = Path(__file__).resolve().parents[3]
    try:
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True, timeout=3)
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, check=True, timeout=3)
        return {"revision": revision.stdout.strip(), "dirty": bool(status.stdout)}
    except (OSError, subprocess.SubprocessError):
        return {"revision": "unknown", "dirty": None}


def selected_models(settings) -> dict:
    return {role: os.getenv(f"BULLBEAR_{role.upper()}_MODEL",
                            getattr(settings, f"{role}_model", None) or settings.model)
            for role in ("debater", "moderator")}


def provenance() -> dict:
    # Hash source files as well as schemas: template rendering and reviewer
    # policy changes must be distinguishable without storing prompt text.
    result = {
        "code": code_revision(),
        "policy_version": prompts.POLICY_VERSION,
        "judgment_policy_hash": canonical_hash(prompts.JUDGMENT_POLICY),
        "prompt_source_hashes": {
            module.__name__.rsplit(".", 1)[-1]: "sha256:" + hashlib.sha256(
                Path(module.__file__).read_bytes()).hexdigest()
            for module in (prompts, semantic)
        },
        "schema_hashes": {
            "statement": canonical_hash(schemas.STATEMENT_SCHEMA),
            "moderator": canonical_hash(schemas.MODERATOR_SCHEMA),
            "semantic_review": canonical_hash(semantic.Review.model_json_schema()),
        },
    }
    result["rag_source_hashes"] = {
        name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ("context.py", "retrieval.py", "index.py", "replay.py", "store.py", "schemas.py")
        if (path := Path(__file__).with_name("rag") / name).is_file()
    }
    return result


def normalized_usage(payload) -> dict:
    """Allow only model names and nonnegative integer counters, never vendor blobs."""
    calls = []
    for item in payload.get("calls", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("model"), str):
            continue
        call = {"model": item["model"]}
        call.update({key: value for key in USAGE_KEYS
                     if isinstance(value := item.get(key), int)
                     and not isinstance(value, bool) and value >= 0})
        calls.append(call)
    return {"calls": calls}


def usage_delta(before: dict, after: dict) -> dict:
    previous = {item["model"]: item for item in before["calls"]}
    calls = []
    for item in after["calls"]:
        old = previous.get(item["model"], {})
        delta = {key: max(0, item.get(key, 0) - old.get(key, 0)) for key in USAGE_KEYS
                 if key in item or key in old}
        if any(delta.values()):
            calls.append({"model": item["model"], **delta})
    return {"calls": calls}


def merge_usage(*payloads) -> dict:
    totals = {}
    for payload in payloads:
        for call in normalized_usage(payload)["calls"]:
            item = totals.setdefault(call["model"], {"model": call["model"]})
            for key in USAGE_KEYS:
                if key in call:
                    item[key] = item.get(key, 0) + call[key]
    return {"calls": list(totals.values())}


class RunAudit:
    def __init__(self, data_dir: Path, run_id: str, *, ticker: str, data_date: str,
                 max_extra_rounds: int, models: dict, efforts: dict, secrets=()):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("Invalid audit run ID")
        self.directory = data_dir / "audits" / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "manifest.json"
        self._lock = threading.RLock()
        self._started = time.perf_counter()
        self._secrets = tuple(value for key in SECRET_ENV_NAMES if (value := os.getenv(key))) + tuple(
            value for value in secrets if value)
        self._redacted = False
        self._context_attached = False
        self.data = {
            "schema_version": "worker-run-audit-v1", "run_id": run_id,
            "status": "running", "started_at": self._now(), "finished_at": None,
            "elapsed_seconds": 0.0, "ticker": ticker, "data_date": data_date,
            "snapshot_id": None, "decision_at": None, "snapshot": None,
            "provenance": provenance(),
            "config": {"selected_models": models, "efforts": efforts,
                       "max_extra_rounds": max_extra_rounds, "first_side": "bull"},
            "runner": None, "stages": [], "events": [], "llm_calls": [],
            "usage": {"calls": []}, "role_usage": {}, "usage_complete": True,
            "usage_errors": [], "cleanup_errors": [],
        }
        self._write()

    @staticmethod
    def _now():
        return datetime.now(KST).isoformat()

    def _sanitize(self, value):
        if isinstance(value, str):
            original = value
            for secret in sorted(self._secrets, key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
            value = _KEY_PATTERN.sub("[REDACTED]", value)
            value = _ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
            self._redacted |= original != value
            return value
        if isinstance(value, dict):
            return {key: self._sanitize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        return value

    def _write(self):
        payload = self._sanitize(self.data)
        payload["redactions_applied"] = self._redacted
        descriptor, temporary = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=_json_default)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def attach_snapshot(self, snapshot):
        with self._lock:
            payload = snapshot.model_dump(mode="json")
            # build_snapshot embeds DataUnavailable strings in these optional
            # warnings. Keep the category, never copy vendor exception text.
            exception_prefixes = ("재무 데이터 없음:", "발행주식수 없음:", "공시 없음:", "뉴스 없음:")
            omitted = False
            warnings = []
            for warning in payload["warnings"]:
                prefix = next((p for p in exception_prefixes if warning.startswith(p)), None)
                warnings.append(prefix + " [provider detail omitted]" if prefix else warning)
                omitted |= prefix is not None
            payload["warnings"] = warnings
            self._redacted |= omitted
            self.data.update(snapshot_id=snapshot.snapshot_id,
                             decision_at=snapshot.created_at.isoformat(),
                             snapshot=payload, snapshot_warning_details_omitted=omitted,
                             snapshot_payload_hash=canonical_hash(snapshot.model_dump(mode="json")))
            self._write()

    def attach_runner(self, runner):
        with self._lock:
            self.data["runner"] = {"type": type(runner).__name__,
                                   "llm_call_observation": getattr(runner, "audit", None) is self}
            self._write()

    def attach_context(self, context, *, retrieval_config=None):
        """Persist one frozen private input; retries cannot replace its contents."""
        with self._lock:
            if self.data["snapshot_id"] is None:
                raise ValueError("snapshot must be attached before knowledge context")
            if context is not None:
                if context.snapshot_id != self.data["snapshot_id"]:
                    raise ValueError("knowledge context snapshot mismatch")
                payload = json.loads(context.payload_json)
                if datetime.fromisoformat(payload["decision_at"]) != datetime.fromisoformat(self.data["decision_at"]):
                    raise ValueError("knowledge context decision time mismatch")
                record = {"context_id": context.context_id, "payload": payload,
                          "canonical_payload": context.payload_json}
            else:
                record = {"context_id": None, "payload": None, "canonical_payload": None}
            record["retrieval_config"] = dict(retrieval_config or {})
            if self._context_attached:
                if self.data["knowledge_context"] != record:
                    raise ValueError("knowledge context is already frozen")
                return
            self.data["knowledge_context"] = record
            self.data["run_fingerprint"] = canonical_hash({
                "snapshot_id": self.data["snapshot_id"],
                "snapshot_payload_hash": self.data["snapshot_payload_hash"],
                "decision_at": self.data["decision_at"],
                "context_id": record["context_id"],
                "retrieval_config": record["retrieval_config"],
                "config": self.data["config"], "provenance": self.data["provenance"],
            })
            self._write()
            self._context_attached = True

    @contextmanager
    def stage(self, name):
        started = time.perf_counter()
        with self._lock:
            record = {"name": name, "status": "running", "started_at": self._now()}
            self.data["stages"].append(record)
            self._write()
        try:
            yield
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            raise
        else:
            record["status"] = "success"
        finally:
            with self._lock:
                record.update(finished_at=self._now(),
                              elapsed_seconds=round(time.perf_counter() - started, 6))
                self._write()

    def observe_event(self, event, payload):
        if event not in ("turn_started", "statement_rejected", "statement_accepted",
                         "extra_round_requested", "moderator_started"):
            return
        with self._lock:
            self.data["events"].append({"type": event, "at": self._now(),
                "elapsed_seconds": round(time.perf_counter() - self._started, 6),
                **{key: payload[key] for key in ("side", "round", "attempt", "attempts", "verified")
                   if key in payload}})
            self._write()

    def begin_call(self, role, client_role, llm, conv, schema, effort, tools):
        with self._lock:
            call = {"call_id": len(self.data["llm_calls"]) + 1, "role": role,
                    "client_role": client_role, "selected_model": llm.model,
                    "status": "running", "started_at": self._now(), "effort": effort,
                    "system_hash": canonical_hash(conv.system),
                    "messages_hash": canonical_hash(conv.messages),
                    "schema_hash": canonical_hash(schema), "tools_hash": canonical_hash(tools or [])}
            self.data["llm_calls"].append(call)
            self._write()
            return call

    def end_call(self, call, *, usage, elapsed, error=None):
        with self._lock:
            call.update(status="failure" if error is not None else "success", finished_at=self._now(),
                        elapsed_seconds=round(elapsed, 6), usage=usage,
                        actual_models=[item["model"] for item in usage["calls"]])
            if error is not None:
                call["error_type"] = type(error).__name__
            self.data["usage"] = merge_usage(self.data["usage"], usage)
            roles = self.data["role_usage"]
            roles[call["role"]] = merge_usage(roles.get(call["role"], {"calls": []}), usage)
            self._write()

    def finish(self, status, *, usage=None, error=None, result=None):
        with self._lock:
            self.data.update(status=status, finished_at=self._now(),
                             elapsed_seconds=round(time.perf_counter() - self._started, 6))
            if usage is not None:
                self.data["usage"] = normalized_usage(usage)
            if error is not None:
                self.data["error_type"] = type(error).__name__
            if result is not None:
                self.data["result"] = result
            self._write()

    def cleanup_error(self, error):
        with self._lock:
            self.data["cleanup_errors"].append({"error_type": type(error).__name__})
            self._write()

    def usage_error(self, error):
        with self._lock:
            self.data["usage_complete"] = False
            self.data["usage_errors"].append({"error_type": type(error).__name__})
            self._write()


class AuditedLLM:
    """Observe structured calls without changing the provider or public events."""
    def __init__(self, llm, audit: RunAudit, client_role: str):
        self.llm, self.audit, self.client_role = llm, audit, client_role

    def __getattr__(self, name):
        return getattr(self.llm, name)

    def _usage(self):
        return normalized_usage(self.llm.usage_payload())

    def structured(self, conv, *, schema, effort, tools=None, tool_handler=None, on_event=None):
        role = "semantic_reviewer" if schema == semantic.Review.model_json_schema() else self.client_role
        before = self._usage()
        call = self.audit.begin_call(role, self.client_role, self.llm, conv, schema, effort, tools)
        started = time.perf_counter()
        try:
            result = self.llm.structured(conv, schema=schema, effort=effort, tools=tools,
                                         tool_handler=tool_handler, on_event=on_event)
        except Exception as exc:
            self.audit.end_call(call, usage=usage_delta(before, self._usage()),
                                elapsed=time.perf_counter() - started, error=exc)
            raise
        self.audit.end_call(call, usage=usage_delta(before, self._usage()),
                            elapsed=time.perf_counter() - started)
        return result

"""One local, free-text debate. Preview by default; never publishes to the service."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-worker/src"))

import anthropic
from dotenv import dotenv_values

from bullbear.anthropic_budget import WorkerSpendLedger
from bullbear.experiments.minimal_agents import POLICY_VERSION, build_system, run_debate
from bullbear.llm import LLMError
from bullbear.prompts import debater_system
from bullbear.schemas import Side
from bullbear.snapshot import Snapshot
from bullbear.tools import SnapshotTools, TOOL_DEFINITIONS

MODEL = "claude-sonnet-5-5"
MAX_OUTPUT = 16000


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class TextCompletion:
    """The only generation loop is the existing read-only tool protocol."""

    def __init__(self, client, snapshot, ledger, output, *, max_requests=8):
        if client.max_retries != 0:
            raise ValueError("Hidden SDK retries must be disabled")
        self.client, self.ledger, self.output = client, ledger, Path(output)
        self.tool = SnapshotTools(snapshot)
        self.max_requests = max_requests
        self.requests = 0
        self.tool_calls = []
        self.turns = []

    def __call__(self, role, system, messages):
        messages = deepcopy(messages)
        started = time.perf_counter()
        request_start = self.requests
        for _ in range(self.max_requests):
            parameters = dict(
                model=MODEL, max_tokens=MAX_OUTPUT, system=system, messages=messages,
                tools=[{**tool, "strict": True, "eager_input_streaming": True}
                       for tool in TOOL_DEFINITIONS],
                output_config={"effort": "high" if role == "moderator" else "medium"},
                service_tier="standard_only", inference_geo="global",
            )
            reservation = self.ledger.reserve(parameters, scope=f"minimal/{role}")
            self.requests += 1
            stem = f"{self.requests:03d}-{role}"
            try:
                save(self.output / f"{stem}-request.json", parameters)
            except BaseException:
                self.ledger.cancel_before_dispatch(reservation)
                raise
            try:
                with self.client.beta.messages.stream(**parameters) as stream:
                    message = stream.get_final_message()
                save(self.output / f"{stem}-response.json", message.model_dump(mode="json"))
                self.ledger.settle(reservation, message)
            except BaseException as exc:
                self.ledger.unknown(reservation, type(exc).__name__)
                raise
            finally:
                save(self.output / "budget-summary.json", self.ledger.summary())
            if message.stop_reason not in ("end_turn", "tool_use"):
                raise LLMError(f"Incomplete response: {message.stop_reason}")
            blocks = [block.model_dump(mode="json", exclude_none=True) for block in message.content]
            messages.append({"role": "assistant", "content": blocks})
            tool_uses = [block for block in message.content if block.type == "tool_use"]
            if not tool_uses:
                if message.stop_reason != "end_turn":
                    raise LLMError("Tool stop without a tool call")
                text = "".join(block.text for block in message.content if block.type == "text").strip()
                if not text:
                    raise LLMError("Empty final text")
                self.turns.append(dict(role=role, requests=self.requests - request_start,
                                       elapsed_seconds=time.perf_counter() - started,
                                       characters=len(text)))
                return text
            if message.stop_reason != "tool_use":
                raise LLMError("Tool call without a tool stop")
            results = []
            for block in tool_uses:
                self.tool_calls.append({"role": role, "name": block.name})
                result = {"type": "tool_result", "tool_use_id": block.id}
                try:
                    result["content"] = self.tool(block.name, block.input)
                except ValueError:
                    result.update(content="알 수 없는 조회 도구입니다.", is_error=True)
                results.append(result)
            messages.append({"role": "user", "content": results})
        raise LLMError("Tool request limit reached")


def render(result):
    names = {"bull": "매수", "bear": "매도", "moderator": "중재"}
    stages = {"opening": "첫 주장", "rebuttal": "반박", "closing": "최종 변론", "verdict": "판정"}
    lines = ["# 역할·도구·톤만 사용한 실험", ""]
    for turn in [*result["turns"], result["moderator"]]:
        lines.extend([f"## {stages[turn['round']]} · {names[turn['role']]}", "", turn["text"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory only")
    parser.add_argument("--execute", action="store_true", help="Make paid model requests")
    parser.add_argument("--max-usd", default="3", help="Dedicated total ceiling, not expected spend")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    snapshot_bytes = args.snapshot.read_bytes()
    snapshot = Snapshot.model_validate_json(snapshot_bytes)
    args.output.mkdir(parents=True, exist_ok=False)
    systems = {role: build_system(role, snapshot) for role in ("bull", "bear", "moderator")}
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((ROOT / "ai-worker/src/bullbear").rglob("*.py"))}
    source_hashes["scripts/worker_minimal_experiment.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    plan = dict(profile=POLICY_VERSION, model=MODEL, debater_effort="medium", moderator_effort="high",
                max_output_tokens=MAX_OUTPUT, max_requests_per_turn=8, max_usd=args.max_usd,
                snapshot_id=snapshot.snapshot_id, snapshot_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
                price_as_of=str(snapshot.as_of), collected_at=snapshot.created_at.isoformat(),
                facts=len(snapshot.facts), fact_dates_after_price_as_of=sum(
                    fact.as_of > snapshot.as_of for fact in snapshot.facts.values()),
                output_schema=None, review_before_publication=False, retry_feedback=False,
                cache_policy="none", source_hashes=source_hashes,
                system_characters={role: len(system) for role, system in systems.items()},
                worker_bull_system_characters=len(debater_system(Side.BULL, name=snapshot.name,
                    ticker=snapshot.ticker, as_of=str(snapshot.as_of))))
    save(args.output / "plan.json", plan)
    save(args.output / "systems.json", systems)
    (args.output / "snapshot.json").write_bytes(snapshot_bytes)
    if not args.execute:
        print(json.dumps({"status": "preview", "output": str(args.output),
                          "system_characters": plan["system_characters"]}, ensure_ascii=False))
        return 0
    key = (dotenv_values(args.env_file).get("ANTHROPIC_API_KEY") if args.env_file
           else os.getenv("ANTHROPIC_API_KEY"))
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not configured")
    ledger = WorkerSpendLedger(args.output / "budget.sqlite3", "minimal-agent-experiment-v1", args.max_usd)
    client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=180.0)
    complete = TextCompletion(client, snapshot, ledger, args.output)
    record = {"status": "running", "completed_turns": []}
    save(args.output / "result.json", record)
    start = time.perf_counter()

    def on_turn(turn):
        record["completed_turns"].append(turn)
        save(args.output / "result.json", record)
        print(json.dumps({"role": turn["role"], "round": turn["round"],
                          "characters": len(turn["text"])}, ensure_ascii=False), flush=True)

    try:
        record["result"] = run_debate(snapshot, complete, on_turn=on_turn)
        record["status"] = "completed"
        (args.output / "transcript.md").write_text(render(record["result"]), encoding="utf-8")
    except BaseException as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        if isinstance(exc, anthropic.APIStatusError):
            record["http_status"] = exc.status_code
        # Do not expose provider errors, credentials, or model text in terminal progress.
    finally:
        client.close()
        record.update(elapsed_seconds=time.perf_counter() - start, requests=complete.requests,
                      tool_calls=complete.tool_calls, turn_metrics=complete.turns, budget=ledger.summary())
        save(args.output / "result.json", record)
        save(args.output / "budget-summary.json", ledger.summary())
    print(json.dumps({key: record[key] for key in ("status", "requests", "elapsed_seconds", "budget")},
                     ensure_ascii=False), flush=True)
    return 0 if record["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

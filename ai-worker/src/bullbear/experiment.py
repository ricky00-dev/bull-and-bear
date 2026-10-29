"""Same-snapshot, two-order multi-turn pilot (not an investment backtest).

Run from ai-worker: python -m bullbear.experiment --ticker 005930
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .agents import Debater, Moderator
from .config import load_settings
from .debate import Debate, verification_stats
from .events import EventLog
from .llm import LLM, LLMError
from .schemas import Side
from .snapshot import KST, Snapshot
from .prompts import JUDGMENT_POLICY, POLICY_VERSION


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_condition(snapshot, settings, directory, first_side, *, provider="anthropic", model=None):
    llm_class = LLM
    if provider == "openai":
        from .openai_llm import OpenAILLM
        llm_class = OpenAILLM
    debater_llm = llm_class(model or os.getenv("BULLBEAR_DEBATER_MODEL", settings.model))
    moderator_llm = llm_class(model or os.getenv("BULLBEAR_MODERATOR_MODEL", settings.model))
    history_lengths = []

    class ObservedDebater(Debater):
        def speak(self, side, round_kind, transcript, **kwargs):
            history_lengths.append({"side": side.value, "round": round_kind,
                                    "previous_statements": len(transcript)})
            return super().speak(side, round_kind, transcript, **kwargs)

    def emit(event, data):
        if event == "statement_accepted":
            if not data["verified"]:
                raise LLMError("Unverified statement; condition aborted")
            print(f"{first_side.value}-first: {data['round']} {data['side'].value} accepted", flush=True)

    started = time.perf_counter()
    report = {"provider": provider, "first_side": first_side.value, "snapshot_id": snapshot.snapshot_id,
              "debater_model": debater_llm.model, "moderator_model": moderator_llm.model,
              "max_extra_rounds": 0, "history_lengths": history_lengths}
    debater = ObservedDebater(debater_llm, snapshot, effort=settings.debater_effort)
    moderator = Moderator(moderator_llm, snapshot, effort=settings.moderator_effort)
    report.update(policy_version=POLICY_VERSION, judgment_policy=JUDGMENT_POLICY)
    try:
        result = Debate(snapshot,
                        debater, moderator,
                        EventLog(directory / f"{first_side.value}-first.jsonl"),
                        debate_id=f"pilot-{directory.name}-{first_side.value}",
                        max_extra_rounds=0, first_side=first_side, on_event=emit).run()
        report.update(status="completed", verdict=result.verdict.model_dump(mode="json"),
                      transcript=result.transcript(), stats=verification_stats(result.turns))
    except Exception as exc:
        # Provider error messages may include credentials; save only the type.
        report.update(status="failed", error_type=type(exc).__name__)
        safe_reasons = {
            "OpenAI response did not complete", "OpenAI refused the response",
            "OpenAI structured output could not be parsed", "OpenAI structured output must be an object",
            "Tool loop exceeded 8 requests", "Semantic reviewer returned an ungrounded quotation",
            "Statement failed verification after retries", "Moderator failed semantic/horizon verification after 3 attempts",
        }
        if isinstance(exc, LLMError) and str(exc) in safe_reasons:
            report["error_reason"] = str(exc)
        if isinstance(getattr(exc, "status_code", None), int):
            report["http_status"] = exc.status_code
    finally:
        report["semantic_reviews"] = {name: getattr(getattr(agent, "reviewer", None), "records", [])
                                      for name, agent in (("debater", debater), ("moderator", moderator))}
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["usage"] = {"debater": debater_llm.usage_payload(),
                           "moderator": moderator_llm.usage_payload()}
        save(directory / f"{first_side.value}-first.json", report)
        debater_llm.client.close()
        moderator_llm.client.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="005930")
    parser.add_argument("--provider", choices=("anthropic", "openai"), default="anthropic")
    parser.add_argument("--model", help="Use this model for both debaters and the moderator")
    parser.add_argument("--env-file", type=Path, help="Explicit dotenv file; its values override inherited environment variables")
    parser.add_argument("--snapshot-file", type=Path, help="Reuse this exact snapshot instead of fetching data")
    args = parser.parse_args(argv)
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("--env-file must point to an existing file")
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
    settings = load_settings()
    key_name = "OPENAI_API_KEY" if args.provider == "openai" else "ANTHROPIC_API_KEY"
    if not os.getenv(key_name):
        parser.exit(2, f"{key_name} is missing; no LLM calls made.\n")
    model = args.model or ("gpt-5-mini" if args.provider == "openai" else None)
    if args.snapshot_file:
        snapshot = Snapshot.model_validate_json(args.snapshot_file.read_text(encoding="utf-8"))
    else:
        from .server.market import Market
        market = Market(settings)
        snapshot = market.snapshot(market.quote(args.ticker))
    directory = settings.data_dir / "experiments" / (datetime.now(KST).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    directory.mkdir(parents=True)
    save(directory / "snapshot.json", snapshot.model_dump(mode="json"))
    save(directory / "manifest.json", {
        "purpose": "Exploratory turn-order pilot; not evidence of forecasting accuracy",
        "provider": args.provider, "model_override": model,
        "policy_version": POLICY_VERSION, "judgment_policy": JUDGMENT_POLICY,
        "snapshot_id": snapshot.snapshot_id, "warnings": snapshot.warnings,
        "conditions": ["bull-first", "bear-first"], "rounds": 3,
        "repetitions_per_condition": 1, "extra_rounds": 0,
        "debater_effort": settings.debater_effort, "moderator_effort": settings.moderator_effort,
    })
    reports = []
    for side in (Side.BULL, Side.BEAR):
        report = run_condition(snapshot, settings, directory, side, provider=args.provider, model=model)
        reports.append(report)
        if report["status"] != "completed":
            print(f"Stopped: {report['error_type']} (HTTP {report.get('http_status', 'n/a')}). Results: {directory}")
            return 1
    save(directory / "comparison.json", {
        "snapshot_id": snapshot.snapshot_id,
        "decisions": {r["first_side"]: r["verdict"]["decision"] for r in reports},
        "decision_changed": reports[0]["verdict"]["decision"] != reports[1]["verdict"]["decision"],
        "limitation": "One pair only; randomness and order effects cannot be separated. No future-return scoring.",
    })
    print(f"Results: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

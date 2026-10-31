from types import SimpleNamespace as NS

import pytest

from bullbear.benchmark import BenchmarkConfig, ObservedClient, RequestBudget, paid_ledger, run_pair
from bullbear.budget import BudgetError, SpendLedger
from bullbear.events import EventLog
from bullbear.llm import Conversation
from bullbear.openai_llm import OpenAILLM
from .test_budget import payload, response
from .test_openai_llm import client_for, message, response as sdk_response
from .fakes import FakeSource, NOW
from bullbear.snapshot import build_snapshot


def test_budget_is_committed_before_transport_and_reused_after_error(tmp_path):
    path = tmp_path / "budget.db"
    ledger = SpendLedger(path, "same", ".2")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        assert SpendLedger(path, "same", ".2").summary()["requests"] == 1
        raise OSError("unconfirmed transport")
    for name in ("first", "second"):
        budget = RequestBudget(10, EventLog(tmp_path / f"{name}.jsonl"), ledger=ledger)
        client = ObservedClient(NS(responses=NS(create=create)), budget)
        with pytest.raises((OSError, BudgetError)):
            client.create(**payload())
    assert len(calls) == 1
    assert ledger.summary()["cost_usd"] is None


def test_response_settles_before_adapter_validation_and_output_limit_is_configurable(tmp_path):
    requests = []
    reply = sdk_response([message()])
    reply["model"] = "gpt-5-mini-2025-08-07"
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    budget = RequestBudget(2, EventLog(tmp_path / "calls.jsonl"), ledger=ledger)
    llm = OpenAILLM("gpt-5-mini", client=ObservedClient(client_for([reply], requests), budget), max_output_tokens=512)
    assert llm.structured(Conversation("s"), schema={}, effort="medium") == {"ok": True}
    assert requests[0]["max_output_tokens"] == 512
    assert requests[0]["service_tier"] == "default" and requests[0]["truncation"] == "disabled"
    assert ledger.summary()["cost_status"] == "priced_actual_usage"


def test_unknown_response_model_is_logged_before_rejected_settlement(tmp_path):
    requests = []
    reply = sdk_response([message()])  # deliberately unpriced actual-model
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    log = EventLog(tmp_path / "calls.jsonl")
    budget = RequestBudget(2, log, ledger=ledger)
    llm = OpenAILLM("gpt-5-mini", client=ObservedClient(client_for([reply], requests), budget))
    with pytest.raises(BudgetError):
        llm.structured(Conversation("s"), schema={}, effort="medium")
    events = EventLog.read(tmp_path / "calls.jsonl")
    assert next(e for e in events if e["type"] == "provider_response")["response"]["model"] == "actual-model"
    assert ledger.summary()["halted"]
    assert ledger.summary()["cost_usd"] is None


def test_all_four_rag_arms_share_unconfirmed_reservation(tmp_path, monkeypatch):
    import openai
    from bullbear.benchmark import run_rag_comparison
    from .test_rag_benchmark import context_for
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    calls, options = [], []
    def create(**kwargs):
        calls.append(kwargs)
        return NS(model="gpt-5-mini", usage=None, status="incomplete",
                  model_dump=lambda **kw: {"model": "gpt-5-mini", "usage": None, "status": "incomplete"})
    def client(**kwargs):
        options.append(kwargs)
        return NS(responses=NS(create=create), close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", client)
    config = BenchmarkConfig(provider="openai", final_model="gpt-5-mini", allow_paid=True,
                             budget_ledger=str(tmp_path / "budget.db"), authorization_id="same", max_total_usd=".14")
    result = run_rag_comparison(snapshot, config, tmp_path / "comparison", context_for(snapshot))
    assert len(calls) == 1 and all(o["max_retries"] == 0 for o in options)
    assert result["completed_arms"] == 0 and result["cost_usd"] is None
    assert result["authorization_budget"]["unconfirmed_requests"] == 1
    # New output/run still shares the same authorization; no reset of the cap.
    run_rag_comparison(snapshot, config, tmp_path / "rerun", context_for(snapshot))
    assert len(calls) == 1


def test_live_missing_budget_or_unknown_provider_fails_before_output(tmp_path):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    config = BenchmarkConfig(provider="openai", final_model="gpt-5-mini", allow_paid=True)
    with pytest.raises(BudgetError):
        run_pair(snapshot, config, tmp_path / "output")
    assert not (tmp_path / "output").exists()
    with pytest.raises(BudgetError):
        paid_ledger(BenchmarkConfig(provider="anthropic", final_model="claude-test", allow_paid=True))


def test_multiple_pair_configurations_share_persistent_authorization(tmp_path):
    config = BenchmarkConfig(provider="openai", final_model="gpt-5-mini", allow_paid=True,
                             max_total_usd=".2", budget_ledger=str(tmp_path / "budget.db"), authorization_id="one-budget")
    first = paid_ledger(config)
    first.reserve(payload(), scope="none/single")
    with pytest.raises(BudgetError):
        paid_ledger(config).reserve(payload(), scope="common_short/debate")


@pytest.mark.parametrize("failure", ["unknown_model", "output_limit"])
def test_rejected_settlement_preserves_observed_usage_without_claiming_complete_aggregation(tmp_path, monkeypatch, failure):
    import openai
    reply = sdk_response([message()])
    if failure == "output_limit":
        reply["model"] = "gpt-5-mini"
        reply["usage"]["output_tokens"] = 16001
        reply["usage"]["total_tokens"] = 16101
    requests = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client_for([reply], requests))
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    config = BenchmarkConfig(provider="openai", final_model="gpt-5-mini", allow_paid=True,
                             budget_ledger=str(tmp_path / "budget.db"), authorization_id="same", max_total_usd="3")
    result = run_pair(snapshot, config, tmp_path / "output")
    report = result["conditions"]["single"]
    assert len(requests) == 1 and report["status"] == "failed"
    assert report["usage_status"] == "partial_unpriced_or_rejected_usage"
    assert report["provider_usage_reports_received"] == 1
    assert report["provider_actual_models"] == [reply["model"]]
    assert report["provider_observations"][0]["usage"]["output_tokens"] == reply["usage"]["output_tokens"]
    assert report["provider_observations"][0]["settlement_status"] == "rejected"
    assert report["adapter_usage_requests"] == 0 and report["usage"]["final"]["calls"] == []
    assert result["conditions"]["debate"]["usage_status"] == "no_requests"
    assert report["spend"]["halted"]
    if failure == "unknown_model":
        assert report["cost_usd"] is None
    else:
        assert report["cost_usd"] > 0  # Known billed usage remains recorded even when output limit was violated.


def test_priced_usage_remains_reported_when_output_is_refused(tmp_path, monkeypatch):
    import openai
    reply = sdk_response([message(kind="refusal")])
    reply["model"] = "gpt-5-mini"
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client_for([reply], []))
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    config = BenchmarkConfig(provider="openai", final_model="gpt-5-mini", allow_paid=True,
                             budget_ledger=str(tmp_path / "budget.db"), authorization_id="same", max_total_usd="3")
    result = run_pair(snapshot, config, tmp_path / "output")
    for report in result["conditions"].values():
        assert report["status"] == "failed"
        assert report["usage_status"] == "reported"
        assert report["adapter_usage_requests"] == report["provider_usage_reports_received"] == 1
        assert report["provider_observations"][0]["settlement_status"] == "accepted"
        assert report["cost_usd"] > 0

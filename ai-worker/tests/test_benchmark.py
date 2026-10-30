import json
import pytest
from pydantic import ValidationError

from bullbear import benchmark
from bullbear.benchmark import BenchmarkConfig, FixtureLLM, SingleDecision
from bullbear.events import EventLog
from bullbear.llm import Conversation, LLMError
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW


@pytest.fixture
def snapshot():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def test_paired_fixture_runs_real_validation_from_same_frozen_input(tmp_path, snapshot):
    before = snapshot.model_dump(mode="json")
    context = {"items": [{"id": "K.definition", "text": "변동성은 방향을 보장하지 않는다."}]}
    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "pair", context_bundle=context)
    assert result["status"] == "completed"
    assert result["comparable"]
    assert result["execution_mode"] == "fixture"
    assert result["accuracy"] is None
    assert result["forecast_scoring"] == "pending_no_realized_returns"
    assert len(result["conditions"]["debate"]["transcript"]) == 6
    assert snapshot.model_dump(mode="json") == before
    reports = result["conditions"]
    assert reports["single"]["snapshot_sha256"] == reports["debate"]["snapshot_sha256"]
    assert reports["single"]["context_sha256"] == reports["debate"]["context_sha256"]
    for condition in ("single", "debate"):
        assert reports[condition]["confidence_meaning"] == benchmark.CONFIDENCE_MEANING
        assert reports[condition]["usage_status"] == "fixture_no_real_usage"
        events = EventLog.read(tmp_path / "pair" / condition / "generations.jsonl")
        assert any(e["type"] == "generation_started" and "K.definition" in e["system"] for e in events)
    manifest = json.loads((tmp_path / "pair/manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["final_model"] == "fixture-v1"
    assert not manifest["fallbacks"] and manifest["sdk_retries"] == 0
    assert all(manifest[k] for k in ("prompt_hash", "schema_hash", "config_hash", "run_fingerprint"))
    assert json.loads((tmp_path / "pair/comparison.json").read_text(encoding="utf-8")) == result


def test_single_unknown_fact_and_wrong_horizon_are_rejected_before_semantic_review(tmp_path, snapshot):
    class Invalid(FixtureLLM):
        def structured(self, conv, *, schema, **kwargs):
            raw = super().structured(conv, schema=schema, **kwargs)
            if "claim" in raw:
                raw["claim"] = "장기 상승 예상"
                raw["evidence"][0]["source_id"] = "UNKNOWN"
            return raw

    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "invalid",
                                llm_factory=lambda c, m, s, b: Invalid(m, s, b))
    assert result["status"] == "partial_failure"
    assert result["conditions"]["single"]["status"] == "failed"
    assert result["conditions"]["single"]["requests_attempted"] == 3
    assert result["conditions"]["single"]["semantic_reviews"]["single"] == []
    attempts = [e for e in EventLog.read(tmp_path / "invalid/single/events.jsonl") if e["type"] == "single_attempt"]
    assert len(attempts) == 3
    assert {i["code"] for i in attempts[0]["issues"]} >= {"unknown_source", "horizon_mismatch"}
    assert "decision" not in result["conditions"]["single"]


def test_single_semantic_rejection_is_retained_then_rewritten(tmp_path, snapshot):
    class OneRejection(FixtureLLM):
        rejected = False

        def structured(self, conv, *, schema, **kwargs):
            raw = super().structured(conv, schema=schema, **kwargs)
            if "issues" in schema["properties"] and not self.rejected:
                self.rejected = True
                raw["issues"] = [{"code": "unsupported_inference", "quote": "불확실하다",
                                  "message": "테스트 검토 피드백"}]
            return raw

    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "retry",
                                llm_factory=lambda c, m, s, b: OneRejection(m, s, b))
    assert result["conditions"]["single"]["status"] == "completed"
    attempts = [e for e in EventLog.read(tmp_path / "retry/single/events.jsonl") if e["type"] == "single_attempt"]
    assert [e["passed"] for e in attempts] == [False, True]
    assert len(result["conditions"]["single"]["semantic_reviews"]["single"]) == 2


def test_failure_of_one_arm_does_not_skip_other_arm_or_batch_cell(tmp_path, snapshot):
    calls = 0

    def factory(config, model, snap, budget):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LLMError("secret-provider-exception-do-not-save")
        return FixtureLLM(model, snap, budget)

    rows = benchmark.run_batch([snapshot, snapshot], BenchmarkConfig(), tmp_path / "batch", llm_factory=factory)
    assert [r["status"] for r in rows] == ["partial_failure", "completed"]
    pair = json.loads((tmp_path / "batch/pair-001/comparison.json").read_text(encoding="utf-8"))
    assert pair["conditions"]["debate"]["status"] == "completed"
    assert pair["conditions"]["single"]["error_type"] == "LLMError"
    assert "secret-provider-exception" not in (tmp_path / "batch/pair-001/comparison.json").read_text(encoding="utf-8")
    assert len(json.loads((tmp_path / "batch/batch.json").read_text(encoding="utf-8"))["cells"]) == 2


def test_request_cap_counts_generation_and_review_and_stops_before_next_call(tmp_path, snapshot):
    result = benchmark.run_pair(snapshot, BenchmarkConfig(max_requests_per_condition=1), tmp_path / "limited")
    for report in result["conditions"].values():
        assert report["status"] == "failed"
        assert report["error_type"] == "RequestLimit"
        assert report["requests_attempted"] == 1
    assert result["decision_agreement"] is None


def test_snapshot_mutation_is_detected_and_does_not_reach_other_condition(tmp_path, snapshot):
    original = snapshot.model_dump(mode="json")
    calls = 0

    def factory(c, m, snap, budget):
        nonlocal calls
        calls += 1
        if calls == 1:
            snap.facts["PX.CLOSE"].value = -1
        return FixtureLLM(m, snap, budget)

    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "mutated", llm_factory=factory)
    assert result["conditions"]["single"]["status"] == "failed"
    assert result["conditions"]["debate"]["status"] == "completed"
    assert snapshot.model_dump(mode="json") == original


def test_real_provider_requires_explicit_paid_flag_before_creating_output(tmp_path, snapshot):
    with pytest.raises(ValueError, match="allow-paid"):
        benchmark.run_pair(snapshot, BenchmarkConfig(provider="openai", final_model="gpt-test"), tmp_path / "no-paid")
    assert not (tmp_path / "no-paid").exists()
    with pytest.raises(ValueError, match="max_pairs"):
        benchmark.run_batch([snapshot, snapshot], BenchmarkConfig(max_pairs=1), tmp_path / "too-many")


def test_cli_defaults_to_fixture_and_does_not_fetch_data(tmp_path, snapshot, capsys):
    path = tmp_path / "input.json"
    path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    assert benchmark.main(["--snapshot-file", str(path), "--output-dir", str(tmp_path / "cli")]) == 0
    assert (tmp_path / "cli/batch.json").exists()
    assert not (tmp_path / "cli/rag-comparison.json").exists()
    assert "Results:" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        benchmark.main(["--snapshot-file", str(path), "--provider", "openai", "--model", "gpt-test"])
    assert exc.value.code == 2


def test_live_actual_usage_and_unknown_failed_call_cost_are_not_fabricated(tmp_path, snapshot):
    class Reported(FixtureLLM):
        def usage_payload(self):
            return {"calls": [{"model": "provider-resolved-model", "input_tokens": 37, "output_tokens": 9,
                               "cache_read_input_tokens": 4, "cache_creation_input_tokens": 0}]}

    config = BenchmarkConfig(provider="openai", final_model="requested-model", allow_paid=True)
    result = benchmark.run_pair(snapshot, config, tmp_path / "actual", llm_factory=lambda c, m, s, b: Reported(m, s, b))
    assert result["conditions"]["single"]["actual_models"]["final"] == ["provider-resolved-model"]
    assert result["conditions"]["single"]["usage"]["final"]["calls"][0]["input_tokens"] == 37
    assert result["conditions"]["single"]["cost_usd"] is None
    assert result["execution_mode"] == "injected_test_double"
    assert result["conditions"]["single"]["usage_status"] == "injected_test_double_usage"
    assert result["accuracy"] is None


def test_confidence_is_bounded_and_never_exported_as_probability():
    with pytest.raises(ValidationError):
        SingleDecision(claim="x", argument="x", evidence=[], decision="BUY", confidence=float("nan"))


def test_openai_transport_records_raw_output_actual_usage_and_stops_before_over_budget_call(tmp_path):
    from bullbear.openai_llm import OpenAILLM
    from .test_openai_llm import client_for, response, message
    requests = []
    raw_client = client_for([response([message()])], requests)
    log = EventLog(tmp_path / "requests.jsonl")
    budget = benchmark.RequestBudget(1, log)
    client = benchmark.ObservedClient(raw_client, budget)
    llm = OpenAILLM("requested-alias", client=client)
    assert llm.structured(Conversation("s"), schema={}, effort="medium") == {"ok": True}
    assert llm.usage_payload()["calls"][0]["model"] == "actual-model"
    assert llm.usage_payload()["calls"][0]["input_tokens"] == 70
    with pytest.raises(benchmark.RequestLimit):
        llm.structured(Conversation("s"), schema={}, effort="medium")
    assert len(requests) == 1
    assert budget.responses_received == 1
    assert any(e["type"] == "provider_response" and e["response"]["model"] == "actual-model"
               for e in EventLog.read(tmp_path / "requests.jsonl"))
    client.close()


def test_unpriced_anthropic_benchmark_fails_before_sdk_initialization(tmp_path, snapshot, monkeypatch):
    import anthropic
    from bullbear.budget import BudgetError
    called = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: called.append(kwargs))
    budget = benchmark.RequestBudget(3, EventLog(tmp_path / "calls.jsonl"))
    config = BenchmarkConfig(provider="anthropic", final_model="claude-test", allow_paid=True)
    with pytest.raises(BudgetError):
        benchmark.make_llm(config, config.final_model, snapshot, budget)
    assert not called


def test_malformed_snapshot_does_not_erase_valid_batch_cell(tmp_path, snapshot):
    bad = tmp_path / "bad.json"
    bad.write_text("not a snapshot", encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(snapshot.model_dump_json(), encoding="utf-8")
    rows = benchmark.run_batch([bad, good], BenchmarkConfig(), tmp_path / "mixed")
    assert [row["status"] for row in rows] == ["failed", "completed"]
    assert rows[0]["error_type"] == "ValidationError"
    assert rows[0]["snapshot_id"] is None


def test_different_actual_final_models_are_not_reported_as_comparable(tmp_path, snapshot):
    created = 0

    class Reported(FixtureLLM):
        def usage_payload(self):
            return {"calls": [{"model": self.actual, "input_tokens": 1, "output_tokens": 1}]}

    def factory(c, m, s, b):
        nonlocal created
        created += 1
        client = Reported(m, s, b)
        client.actual = "resolved-a" if created == 1 else "resolved-b"
        return client

    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "models", llm_factory=factory)
    assert result["status"] == "completed"
    assert not result["comparable"]
    assert result["decision_agreement"] is None


def test_mismatched_context_is_rejected_before_execution(tmp_path, snapshot):
    with pytest.raises(ValueError, match="does not match"):
        benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "context",
                           context_bundle={"snapshot_id": "another-snapshot"})
    assert not (tmp_path / "context").exists()


def test_cli_rag_comparison_runs_four_fixture_arms(tmp_path, snapshot):
    from .test_rag_benchmark import context_for
    context = context_for(snapshot)
    path = tmp_path / 'snapshot.json'
    path.write_text(snapshot.model_dump_json(), encoding='utf-8')
    context_path = tmp_path / 'context.json'
    context_path.write_text(context.payload_json, encoding='utf-8')
    output = tmp_path / 'rag-cli'
    assert benchmark.main(['--rag-comparison', '--snapshot-file', str(path),
                           '--context-file', str(context_path), '--output-dir', str(output)]) == 0
    result = json.loads((output / 'rag-comparison.json').read_text(encoding='utf-8'))
    assert result['completed_arms'] == 4
    assert result['conditions']['none']['context_id'] is None
    assert result['conditions']['common_short']['context_id'] == context.context_id
    assert result['accuracy'] is None and result['cost_usd'] is None
    assert not (output / 'batch.json').exists()


@pytest.mark.parametrize('case', ['missing_context', 'multiple_snapshots', 'legacy_context', 'null_context'])
def test_cli_rag_comparison_rejects_invalid_setup_before_output(tmp_path, snapshot, case):
    from .test_rag_benchmark import context_for
    path = tmp_path / 'snapshot.json'
    path.write_text(snapshot.model_dump_json(), encoding='utf-8')
    context_path = tmp_path / 'context.json'
    context_path.write_text(context_for(snapshot).payload_json, encoding='utf-8')
    output = tmp_path / 'invalid-rag'
    args = ['--rag-comparison', '--snapshot-file', str(path), '--output-dir', str(output)]
    if case != 'missing_context':
        args += ['--context-file', str(context_path)]
    if case == 'multiple_snapshots':
        args += ['--snapshot-file', str(path)]
    elif case == 'legacy_context':
        context_path.write_text(json.dumps({'snapshot_id': snapshot.snapshot_id}), encoding='utf-8')
    elif case == 'null_context':
        context_path.write_text('null', encoding='utf-8')
    with pytest.raises(SystemExit) as exc:
        benchmark.main(args)
    assert exc.value.code == 2
    assert not output.exists()

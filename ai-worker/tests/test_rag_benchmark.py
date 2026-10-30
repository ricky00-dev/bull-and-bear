import json

import pytest

from bullbear import benchmark
from bullbear.benchmark import BenchmarkConfig
from bullbear.events import EventLog
from bullbear.rag.context import KnowledgeContext
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW


@pytest.fixture
def snapshot():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def context_for(snapshot, *, status="completed"):
    return KnowledgeContext.from_payload({
        "schema_version": "knowledge-context-v1", "profile_version": "knowledge-short-v1",
        "snapshot_id": snapshot.snapshot_id, "decision_at": snapshot.created_at.isoformat(),
        "status": status, "items": [{"kind": "knowledge", "text": "방향을 보장하지 않는다.",
                                      "horizons": ["common"], "applicability": "개념 설명",
                                      "limitations": [], "study_scope": None}] if status == "completed" else [],
    })


def test_formal_context_reaches_all_generators_and_reviewers_once(tmp_path, snapshot):
    context = context_for(snapshot)
    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "pair", context_bundle=context)
    assert result["status"] == "completed"
    for arm in ("single", "debate"):
        events = [row for row in EventLog.read(tmp_path / "pair" / arm / "generations.jsonl")
                  if row["type"] == "generation_started"]
        assert events and all(row["system"].count("PRIVATE_BACKGROUND_DATA") == 1 for row in events)
        assert all(context.rendered in row["system"] for row in events)
        assert result["conditions"][arm]["context_id"] == context.context_id


def test_rag_ablation_keeps_conditions_records_unpriced_usage_and_no_accuracy(tmp_path, snapshot):
    context = context_for(snapshot)
    result = benchmark.run_rag_comparison(snapshot, BenchmarkConfig(), tmp_path / "rag", context)
    assert result["completed_arms"] == 4 and result["completion_rate"] == 1
    assert result["comparable"] and result["accuracy"] is None
    assert result["provider_request_upper_bound"] == 480
    assert result["cost_usd"] is None and result["cost_status"].startswith("not_priced")
    for name in ("none", "common_short"):
        manifest = json.loads((tmp_path / "rag" / name / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["condition_order"] == ["single", "debate"]
        assert manifest["config"]["final_model"] == "fixture-v1"
        for arm in ("single", "debate"):
            events = EventLog.read(tmp_path / "rag" / name / arm / "generations.jsonl")
            generated = [e for e in events if e["type"] == "generation_started"]
            assert all(("PRIVATE_BACKGROUND_DATA" in e["system"]) == (name == "common_short") for e in generated)
    assert result["conditions"]["none"]["context_id"] is None
    assert result["conditions"]["common_short"]["context_id"] == context.context_id


def test_empty_or_failed_retrieval_cannot_be_reported_as_added_rag(tmp_path, snapshot):
    for status in ("empty", "failed", "timeout"):
        with pytest.raises(ValueError):
            benchmark.run_rag_comparison(snapshot, BenchmarkConfig(), tmp_path / status,
                                          context_for(snapshot, status=status))
        assert not (tmp_path / status).exists()


def test_rag_comparison_retains_bounded_failures_in_every_cell(tmp_path, snapshot):
    result = benchmark.run_rag_comparison(snapshot, BenchmarkConfig(max_requests_per_condition=1),
                                           tmp_path / "limited", context_for(snapshot))
    assert result["status"] == "partial_failure" and result["completion_rate"] == 0
    assert not result["comparable"]
    assert result["provider_request_upper_bound"] == 4
    assert all(cell["requests_attempted"] == 2 for cell in result["conditions"].values())


def changing_source(monkeypatch):
    calls = []

    def identity():
        value = "initial" if not calls else "edited"
        calls.append(value)
        return {"commit": "same-commit", "dirty": True, "source_hash": value,
                "module_hashes": {"benchmark.py": value}}

    monkeypatch.setattr(benchmark, "source_identity", identity)


def test_rag_freezes_initial_code_identity_and_rejects_changed_sources(tmp_path, snapshot, monkeypatch):
    changing_source(monkeypatch)
    directory = tmp_path / "changed-rag"
    result = benchmark.run_rag_comparison(snapshot, BenchmarkConfig(), directory, context_for(snapshot))
    assert result["completed_arms"] == 4  # Raw runs still complete and remain available.
    assert result["code_changed_during_run"] and not result["comparable"]
    assert result["code"]["source_hash"] == "initial"
    assert result["code_at_end"]["source_hash"] == "edited"
    for name in ("none", "common_short"):
        manifest = json.loads((directory / name / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["code"] == result["code"]
        assert result["conditions"][name]["code_changed_during_run"]
        for arm in ("single", "debate"):
            assert (directory / name / arm / "report.json").is_file()


def test_standalone_pair_detects_disk_changes_without_erasing_decisions(tmp_path, snapshot, monkeypatch):
    changing_source(monkeypatch)
    result = benchmark.run_pair(snapshot, BenchmarkConfig(), tmp_path / "changed-pair")
    assert result["status"] == "completed"
    assert result["code_changed_during_run"] and not result["comparable"]
    assert result["decision_agreement"] is None
    assert all(row["decision"] for row in result["conditions"].values())


def test_batch_reuses_code_identity_and_records_source_changes(tmp_path, snapshot, monkeypatch):
    changing_source(monkeypatch)
    directory = tmp_path / "changed-batch"
    cells = benchmark.run_batch([snapshot, snapshot], BenchmarkConfig(), directory)
    report = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
    assert all(cell["status"] == "completed" for cell in cells)
    assert report["code_changed_during_run"] and not report["comparable"]
    for i in (1, 2):
        manifest = json.loads((directory / f"pair-{i:03}" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["code"] == report["code"]

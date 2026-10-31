import json
from pathlib import Path

import pytest

from bullbear.rag.evaluation import EvaluationDataset, evaluate, main, score_ranking, score_selection

DATASET = Path(__file__).parent / "fixtures" / "rag_evaluation" / "concept-probes-v1.json"


def dataset():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_metrics_use_gold_denominator_deduplicate_and_keep_negatives_undefined():
    assert score_ranking(["irrelevant", "a", "a", "b"], ["a", "b", "c"], 3) == {
        "recall_at_k": 2 / 3, "reciprocal_rank_at_k": 0.5}
    assert score_ranking([], ["a"]) == {"recall_at_k": 0, "reciprocal_rank_at_k": 0}
    assert score_ranking(["a"], []) == {"recall_at_k": None, "reciprocal_rank_at_k": None}
    with pytest.raises(ValueError):
        score_ranking([], [], 21)


def test_selection_precision_requires_exhaustive_judgments_and_nonempty_denominator():
    assert score_selection(["a", "noise", "noise"], ["a"], exhaustive=True) == {
        "selected_precision": 0.5, "unnecessary_selected_count": 1}
    assert score_selection(["noise"], [], exhaustive=True) == {
        "selected_precision": 0, "unnecessary_selected_count": 1}
    assert score_selection([], ["a"], exhaustive=True) == {
        "selected_precision": None, "unnecessary_selected_count": 0}
    assert score_selection(["a", "unjudged"], ["a"], exhaustive=False) == {
        "selected_precision": None, "unnecessary_selected_count": None}


def test_actual_selection_precision_reports_noise_without_changing_legacy_gate(tmp_path):
    fixture = dataset()
    fixture["documents"] = [
        {"key": "relevant", "text": "volatility 정답 문단"},
        {"key": "noise", "text": "volatility 무관 문단"},
    ]
    fixture["cases"] = [
        {"id": "complete", "description": "완전 정답 집합", "concept_label": "volatility",
         "relevant": ["relevant"], "relevance_scope": "exhaustive"},
        {"id": "partial", "description": "부분 정답 집합", "concept_label": "volatility",
         "relevant": ["relevant"], "relevance_scope": "subset"},
    ]
    report = evaluate(fixture, tmp_path / "precision")
    assert report["selected_recall_successful"] == 1
    assert report["results"][0]["selected_precision"] == 0.5
    assert report["results"][0]["unnecessary_selected_count"] == 1
    assert report["results"][1]["selected_precision"] is None
    assert report["results"][1]["unnecessary_selected_count"] is None
    assert report["scored_selected_precision_queries"] == 1
    assert report["exhaustive_successful_queries"] == 1
    assert report["selected_precision_successful"] == 0.5
    assert report["unnecessary_selected_count_successful"] == 1
    # Precision is a new diagnostic; this patch does not redefine the gate.
    assert report["quality_gate_passed"]


def test_empty_and_failed_selection_precision_denominators_are_explicit(tmp_path):
    fixture = dataset()
    fixture["cases"] = [
        {"id": "empty", "description": "무관 질의", "concept_label": "unmatchableword",
         "relevance_scope": "exhaustive"},
        {"id": "failed", "description": "검색 장애", "concept_label": "volatility",
         "relevance_scope": "exhaustive", "generation_mode": "missing"},
    ]
    report = evaluate(fixture, tmp_path / "precision-empty")
    assert report["scored_selected_precision_queries"] == 0
    assert report["selected_precision_successful"] is None
    assert report["exhaustive_successful_queries"] == 1
    assert report["unnecessary_selected_count_successful"] == 0
    assert report["results"][0]["selected_precision"] is None
    assert report["results"][0]["unnecessary_selected_count"] == 0
    assert report["results"][1]["selected_precision"] is None
    assert report["results"][1]["unnecessary_selected_count"] is None


def test_real_archive_quality_report_measures_curated_korean_aliases(tmp_path):
    report = evaluate(dataset(), tmp_path / "run")
    assert report["attempts"] == 13 and report["search_availability"] == 1
    assert report["scored_positive_queries"] == 6
    assert report["macro_recall_at_k_successful"] == 1
    assert report["mrr_at_k_successful"] == 1
    assert report["selected_recall_successful"] == 1
    assert report["scored_negative_queries"] == 7 and report["negative_false_positives"] == 0
    assert report["violations"] == {"time": 0, "market": 0, "ticker": 0, "forbidden": 0}
    assert report["quality_gate_passed"] and not report["operational_activation_eligible"]
    assert report["cost_usd"] is None and report["accuracy"] is None
    misses = [r["case_id"] for r in report["results"] if r["selected_recall"] == 0]
    assert misses == []
    assert json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8")) == report


def test_failed_search_is_not_relevance_zero_or_negative_success(tmp_path):
    fixture = dataset()
    fixture["cases"] = [fixture["cases"][0]]
    fixture["cases"][0]["generation_mode"] = "missing"
    result = evaluate(fixture, tmp_path / "failed")
    assert result["status_counts"] == {"failed": 1}
    assert result["positive_attempts"] == 1 and result["scored_positive_queries"] == 0
    assert result["macro_recall_at_k_successful"] is None
    assert result["search_availability"] == 0 and not result["quality_gate_passed"]


def test_existing_output_is_preserved(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    (output / "keep.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluate(dataset(), output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("problem", ["duplicate", "unknown", "overlap", "naive", "evidence"])
def test_invalid_dataset_rejected_before_writing(tmp_path, problem):
    fixture = dataset()
    if problem == "duplicate":
        fixture["cases"].append(fixture["cases"][0])
    elif problem == "unknown":
        fixture["cases"][0]["relevant"] = ["missing"]
    elif problem == "overlap":
        fixture["cases"][0]["forbidden"] = fixture["cases"][0]["relevant"]
    elif problem == "naive":
        fixture["as_of"] = "2026-10-16T18:00:00"
    else:
        fixture["evidence_type"] = "human_reviewed"
    with pytest.raises(ValueError):
        evaluate(fixture, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_exception_record_does_not_leak_message(tmp_path, monkeypatch):
    from bullbear.rag import evaluation
    fixture = dataset()
    fixture["cases"] = fixture["cases"][:1]
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET_SHOULD_NOT_APPEAR")
    monkeypatch.setattr(evaluation.Retriever, "retrieve", broken)
    report = evaluate(fixture, tmp_path / "error")
    assert report["status_counts"] == {"exception": 1}
    assert "SECRET_SHOULD_NOT_APPEAR" not in json.dumps(report)


def test_cli_quality_success_does_not_authorize_operation(tmp_path, capsys):
    assert main([str(DATASET), "--output", str(tmp_path / "cli")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["quality_gate_passed"] and "results" not in summary
    assert not summary["operational_activation_eligible"]
    assert (tmp_path / "cli" / "report.json").exists()


def test_curated_aliases_do_not_match_arbitrary_word_fragments(tmp_path):
    fixture = dataset()
    labels = ["변동성장", "고변동성상품", "주가 수익 비율표", "자기 자본 이익률표", "performance"]
    fixture["cases"] = [{"id": str(i), "description": "별칭 부분문자열 오탐 검사", "concept_label": label}
                        for i, label in enumerate(labels)]
    report = evaluate(fixture, tmp_path / "negative-aliases")
    assert report["successful_searches"] == len(labels)
    assert report["negative_false_positives"] == 0


@pytest.mark.parametrize("label,expanded", [
    ("변동성은 무엇인가", "volatility"), ("주가 수익 비율은", "per"),
    ("자기 자본 이익률이", "roe"), ("주가 순자산 비율을", "pbr"),
    ("PER은", "주가수익비율"),
])
def test_curated_alias_query_expansion(label, expanded):
    from bullbear.rag.evaluation import _snapshot, EvaluationCase
    from bullbear.rag.retrieval import query_terms
    data = EvaluationDataset.model_validate(dataset())
    snapshot = _snapshot(data, EvaluationCase(id="alias", description="test", concept_label=label), "x")
    assert expanded in query_terms(snapshot)

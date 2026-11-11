"""Compact model inputs retain provenance and a complete detail-query path."""
from copy import deepcopy
from csv import DictReader
from datetime import timedelta
from io import StringIO
import json

import pytest

from bullbear.shared_context import (build_compact_fact_context, build_moderator_context, build_shared_push,
                                    expand_fact_ids, referenced_fact_context)
from bullbear.snapshot import build_snapshot
from bullbear.tools import DEBATE_TOOL_DEFINITIONS, SnapshotTools

from .fakes import FakeNews, FakeSource, NOW
from .test_shared_push import compact_rows, index_loader


def rows(text):
    return {row["source_id"]: row for row in DictReader(StringIO(text))}


def snapshot():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW,
                          news=FakeNews(), index_loader=index_loader)


def transcript(source_id):
    return [json.dumps({"evidence": [{"source_id": source_id}]})]


def test_dependency_closure_handles_cycles_and_reports_missing_without_mutation():
    snap = snapshot()
    a = snap.facts["PX.CLOSE"].model_copy(update={"id": "TEST.A", "inputs": ["TEST.B", "TEST.missing"]})
    b = a.model_copy(update={"id": "TEST.B", "inputs": ["TEST.A"]})
    snap.facts.update({a.id: a, b.id: b})
    before = deepcopy(snap)
    facts, missing = expand_fact_ids(snap, [a.id, a.id, "TEST.unknown"])
    assert [f.id for f in facts] == [a.id, b.id]
    assert missing == ["TEST.missing", "TEST.unknown"]
    assert snap == before


def test_moderator_keeps_citations_dependency_ids_neutral_baseline_and_provenance():
    snap = snapshot()
    unrelated = snap.by_category("disclosure")[0]
    snap.warnings.append("테스트 위험 경고")
    context = build_moderator_context(snap, transcript("VAL.OP_MARGIN_TTM"))
    supplied = compact_rows(context)
    assert {"PX.CLOSE", "PX.EXCESS_KOSPI_3D", "PX.EXCESS_KOSPI_7D", "PX.VOL_20D",
            "VAL.PER_TTM", "VAL.PBR", "VAL.DEBT_RATIO", "VAL.OP_MARGIN_TTM"} <= supplied.keys()
    assert unrelated.id not in supplied
    for key in supplied:
        assert json.loads(supplied[key].get("inputs") or "[]") == snap.facts[key].inputs
    assert "VAL.OPERATING_INCOME_TTM" not in supplied
    dependency = json.loads(SnapshotTools(snap)("get_facts", {"source_ids": ["VAL.OPERATING_INCOME_TTM"]}))
    assert "VAL.OPERATING_INCOME_TTM" in rows(dependency["facts_csv"])
    for key in ("FIN.2026H1.OPERATING_INCOME_YTD",):
        assert supplied[key]["value"] == str(int(snap.facts[key].value))
        assert supplied[key]["unit"] == "KRW"
        assert supplied[key]["as_of"] == str(snap.facts[key].as_of)
        assert supplied[key]["source"] == snap.facts[key].source
        assert supplied[key]["report_period"] == snap.facts[key].report_period
        assert supplied[key]["report_basis"] == snap.facts[key].report_basis
    assert context["warnings"] == snap.warnings
    assert context["data_status"] == snap.data_status
    assert context["information_cutoff"] == snap.information_cutoff.isoformat()


def test_per_round_supplement_restores_only_extra_cited_facts_and_dependency_ids():
    snap = snapshot()
    supplement = referenced_fact_context(snap, transcript("VAL.OP_MARGIN_TTM"))
    supplied = rows(supplement["referenced_facts_csv"])
    assert "VAL.OP_MARGIN_TTM" in supplied
    assert "VAL.OPERATING_INCOME_TTM" not in supplied
    assert "VAL.OPERATING_INCOME_TTM" in json.loads(supplied["VAL.OP_MARGIN_TTM"]["inputs"])
    assert "referenced_fact_metadata" in supplement
    assert "PX.CLOSE" not in supplied
    assert referenced_fact_context(snap, transcript("PX.CLOSE")) == {}
    assert referenced_fact_context(snap, transcript("unknown")) == {"missing_referenced_fact_ids": ["unknown"]}


def test_news_preview_is_neutral_deterministic_and_event_deduplicated_with_detail_access():
    snap = snapshot()
    article = snap.by_category("news")[0]
    for n in range(12):
        fact = article.model_copy(update={"id": f"NEWS.extra{n:02}", "label": f"기사 {n}",
            "published_at": article.published_at - timedelta(minutes=n), "event_id": f"event{n // 2}"})
        snap.facts[fact.id] = fact
    push = build_shared_push(snap)
    preview = rows(push["stock_news_csv"])
    assert len(preview) == 2
    assert len({snap.facts[key].event_id for key in preview}) == 2
    assert push["news_available"]["company"] == 13
    assert all("summary" not in row for row in preview.values())
    assert all(snap.facts[key].note not in row.values() for key, row in preview.items())
    reversed_snapshot = snap.model_copy(update={"facts": dict(reversed(list(snap.facts.items())))})
    assert build_shared_push(reversed_snapshot) == push
    tools = SnapshotTools(snap)
    visited, offset = set(), 0
    while offset is not None:
        result = json.loads(tools("get_snapshot_news", {"scope": "company", "offset": offset}))
        page = rows(result["facts_csv"])
        assert len(page) <= 5
        assert not visited & page.keys()
        visited.update(page)
        offset = result["next_offset"]
    assert visited == {f.id for f in snap.by_category("news")}


def test_compact_fact_metadata_round_trips_values_units_dates_basis_and_qualifiers():
    snap = snapshot()
    # All categories, including news strings containing CSV delimiters/newlines.
    article = snap.by_category("news")[0]
    article.note = '원문, "인용"\r다음 줄\n마지막'
    before = deepcopy(snap)
    context = build_compact_fact_context(snap.facts.values(), price_as_of=snap.as_of)
    decoded = compact_rows(context)
    assert decoded.keys() == snap.facts.keys()
    assert snap == before
    for key, fact in snap.facts.items():
        row = decoded[key]
        assert (float(row["value"]) if row["value"] else None) == fact.value
        assert row["unit"] == fact.unit
        assert row["label"] == fact.label
        assert row["as_of"] == str(fact.as_of)
        assert row["category"] == fact.category
        expected_source = (fact.publisher or "news") if fact.category == "news" and (
            fact.source.startswith(("https://", "http://")) or fact.source == fact.url) else fact.source
        assert row["source"] == expected_source
        assert json.loads(row.get("inputs") or "[]") == fact.inputs
        for field in ("report_period", "report_basis", "status", "event_id"):
            assert row.get(field) == getattr(fact, field)
        if fact.note and (fact.report_basis, fact.note) not in {("consolidated", "연결"), ("separate", "별도")}:
            assert row["note"] == fact.note
        for field in ("published_at", "vintage_date"):
            observed = getattr(fact, field)
            if observed:
                assert row[field] == observed.isoformat()
    assert len(rows(build_shared_push(snap)["facts_csv"])) < 20
    assert "PX.RET_3D" not in rows(build_shared_push(snap)["facts_csv"])
    assert "PX.RET_3D" in snap.facts  # Still accessible for detailed validation.


def test_fact_lookup_batches_exact_values_reports_unknown_ids_and_limits_responses():
    snap = snapshot()
    tools = SnapshotTools(snap)
    result = json.loads(tools("get_facts", {"source_ids": ["PX.CLOSE", "missing", "PX.CLOSE"]}))
    assert rows(result["facts_csv"])["PX.CLOSE"]["value"] == "399"
    assert result["missing_source_ids"] == ["missing"]
    assert result["remaining_source_ids"] == result["oversized_source_ids"] == []
    article = snap.by_category("news")[0]
    article.note = "긴 자료" * 3000
    result = json.loads(tools("get_facts", {"source_ids": [article.id, "PX.CLOSE"]}))
    assert result["oversized_source_ids"] == [article.id]
    assert set(rows(result["facts_csv"])) == {"PX.CLOSE"}
    assert "긴 자료" not in result["facts_csv"]  # No misleading partial quote.
    assert article.note == "긴 자료" * 3000
    for arguments in ({"source_ids": []}, {"source_ids": ["PX.CLOSE"] * 9},
                      {"source_ids": [None]}, {"source_ids": "PX.CLOSE"},
                      {"source_ids": ["PX.CLOSE"], "snapshot_id": "other"}):
        with pytest.raises(ValueError):
            tools("get_facts", arguments)


def test_catalog_exposes_omitted_facts_and_rejects_invalid_pagination():
    snap = snapshot()
    tools = SnapshotTools(snap)
    catalog = json.loads(tools("get_fact_catalog", {"category": "disclosure", "offset": 0}))
    source_id = snap.by_category("disclosure")[0].id
    assert source_id in rows(catalog["catalog_csv"])
    assert source_id in rows(json.loads(tools("get_facts", {"source_ids": [source_id]}))["facts_csv"])
    assert catalog["next_offset"] is None
    definitions = {tool["name"] for tool in DEBATE_TOOL_DEFINITIONS}
    assert {"read_snapshot", "get_new_url"} == definitions
    # Stored old requests still have a compatible local handler.
    assert json.loads(tools("get_price_metrics", {}))["items"]
    for offset in (-1, True, "0", 1.5):
        with pytest.raises(ValueError):
            tools("get_fact_catalog", {"category": "price", "offset": offset})
        with pytest.raises(ValueError):
            tools("get_snapshot_news", {"scope": "company", "offset": offset})


def test_batch_character_limit_returns_remaining_ids_without_dropping_facts():
    snap = snapshot()
    template = snap.by_category("news")[0]
    ids = ["NEWS.large1", "NEWS.large2", "NEWS.large3"]
    for key in ids:
        snap.facts[key] = template.model_copy(update={"id": key, "note": "확인된 문장. " * 400})
    tools = SnapshotTools(snap)
    first = json.loads(tools("get_facts", {"source_ids": ids}))
    assert len(first["facts_csv"]) <= 8000
    assert 0 < len(rows(first["facts_csv"])) < len(ids)
    assert first["oversized_source_ids"] == []
    second = json.loads(tools("get_facts", {"source_ids": first["remaining_source_ids"]}))
    assert set(rows(first["facts_csv"])) | set(rows(second["facts_csv"])) == set(ids)
    assert second["remaining_source_ids"] == []
    for result in (first, second):
        for key, fact in rows(result["facts_csv"]).items():
            assert fact["note"] == snap.facts[key].note


@pytest.mark.parametrize("kind,args,legacy,arguments", [
    ("facts", ["PX.CLOSE", "VAL.PBR", "missing"], "get_facts", {"source_ids": ["PX.CLOSE", "VAL.PBR", "missing"]}),
    ("catalog", ["financials", "0"], "get_fact_catalog", {"category": "financials", "offset": 0}),
    ("catalog", ["price", "20"], "get_fact_catalog", {"category": "price", "offset": 20}),
    ("news", ["company", "0"], "get_snapshot_news", {"scope": "company", "offset": 0}),
    ("chart", ["2026-10-03", "2026-10-16"], "get_daily_chart", {"start_date": "2026-10-03", "end_date": "2026-10-16"}),
])
def test_read_snapshot_preserves_exact_legacy_data_and_snapshot(kind, args, legacy, arguments):
    snap = snapshot()
    before = deepcopy(snap)
    tools = SnapshotTools(snap)
    assert tools("read_snapshot", {"kind": kind, "args": args}) == tools(legacy, arguments)
    assert snap == before


@pytest.mark.parametrize("arguments", [
    None, [], {}, {"kind": "facts"}, {"args": ["PX.CLOSE"]},
    {"kind": "facts", "args": ["PX.CLOSE"], "snapshot_id": "other"},
    {"kind": ["facts"], "args": ["PX.CLOSE"]}, {"kind": "unknown", "args": ["PX.CLOSE"]},
    {"kind": "facts", "args": "PX.CLOSE"}, {"kind": "facts", "args": []},
    {"kind": "facts", "args": ["PX.CLOSE"] * 9}, {"kind": "facts", "args": [None]},
    {"kind": "facts", "args": [""]}, {"kind": "facts", "args": [" "]},
    {"kind": "catalog", "args": ["price"]}, {"kind": "catalog", "args": ["price", "0", "extra"]},
    {"kind": "catalog", "args": ["other", "0"]}, {"kind": "catalog", "args": ["price", 0]},
    {"kind": "catalog", "args": ["price", True]}, {"kind": "catalog", "args": ["price", "-1"]},
    {"kind": "catalog", "args": ["price", "+1"]}, {"kind": "catalog", "args": ["price", "1.0"]},
    {"kind": "catalog", "args": ["price", " 0"]}, {"kind": "catalog", "args": ["price", "01"]},
    {"kind": "catalog", "args": ["price", "١"]},
    {"kind": "news", "args": ["other", "0"]}, {"kind": "news", "args": ["company", "-1"]},
    {"kind": "news", "args": ["company", "0", "extra"]},
    {"kind": "chart", "args": ["2026-10-16"]},
    {"kind": "chart", "args": ["2026-10-02", "2026-10-16"]},
    {"kind": "chart", "args": ["2026-10-16", "2026-10-17"]},
    {"kind": "chart", "args": ["20261016", "2026-10-16"]},
    {"kind": "chart", "args": ["2026-10-16", "2026-10-15"]},
])
def test_read_snapshot_rejects_invalid_modes_types_arity_and_ranges(arguments):
    with pytest.raises(ValueError):
        SnapshotTools(snapshot())("read_snapshot", arguments)


def test_read_snapshot_news_pagination_keeps_summaries_and_no_duplicate_rows():
    snap = snapshot()
    template = snap.by_category("news")[0]
    for n in range(7):
        fact = template.model_copy(update={"id": f"NEWS.page{n}", "note": f"기사 {n}의 정확한 요약"})
        snap.facts[fact.id] = fact
    tools = SnapshotTools(snap)
    first = json.loads(tools("read_snapshot", {"kind": "news", "args": ["company", "0"]}))
    assert len(rows(first["facts_csv"])) == 5
    second = json.loads(tools("read_snapshot", {"kind": "news", "args": ["company", str(first["next_offset"])]}))
    assert not rows(first["facts_csv"]).keys() & rows(second["facts_csv"]).keys()
    assert second["next_offset"] is None
    received = {**rows(first["facts_csv"]), **rows(second["facts_csv"])}
    assert received.keys() == {f.id for f in snap.by_category("news")}
    assert all(row["note"] == snap.facts[key].note for key, row in received.items())

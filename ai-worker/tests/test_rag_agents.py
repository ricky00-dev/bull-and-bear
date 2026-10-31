"""RAG prompt wiring and public citation boundaries; no predictive claims."""
import json

import pytest

from bullbear.agents import Debater, Moderator
from bullbear.presentation import knowledge_leakage_issues, moderator_issues, statement_issues, used_sources
from bullbear.rag.context import KnowledgeContext, render_background
from bullbear.rag.schemas import canonical_json
from bullbear.schemas import Side
from bullbear.semantic import BACKGROUND_RULES, SYSTEM, SemanticReviewer
from bullbear.snapshot import build_snapshot
from bullbear.verifier import verify
from .fakes import FakeSource, NOW, ScriptedModerator, statement
from .test_semantic import QueueLLM


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def context_for(snap, **changes):
    payload = {
        "schema_version": "knowledge-context-v1", "snapshot_id": snap.snapshot_id,
        "decision_at": snap.created_at.isoformat(), "generation_id": "G.fixture",
        "profile_version": "knowledge-short-v1", "time_policy": "observed-v1",
        "target": {"value": 7, "unit": "trading_day", "benchmark": "KOSPI"},
        "status": "completed", "items": [{
            "knowledge_id": "K.definition", "chunk_id": "C.fixture", "revision_id": "R.fixture",
            "annotation_id": "A.fixture", "kind": "knowledge", "role": "definition", "horizons": ["common"],
            "text": "RAG_UNIQUE_DEFINITION 변동성은 방향을 보장하지 않는다.",
            "source_ref": "fixture-definition", "source_locator": "paragraph:1",
            "applicability": "개념 설명", "limitations": [], "study_scope": None,
        }],
    }
    payload.update(changes)
    return KnowledgeContext(payload_json=canonical_json(payload))


def good_statement():
    return statement(("E1", "PX.CLOSE", 399), argument="관측된 가격은 방향을 보장하지 않는다 [E1].").model_copy(
        update={"claim": "7거래일 코스피 대비 비슷한 흐름을 예상한다"})


def good_verdict():
    candidate = ScriptedModerator([]).evaluate([], {}, extra_allowed=False)
    candidate.decisive_evidence = ["PX.CLOSE"]
    candidate.reasoning = "7거래일 코스피 대비 비슷하게 움직일 가능성이 있다 [E1]."
    return candidate


def test_same_frozen_background_once_in_debater_moderator_and_both_reviews(snap):
    context = context_for(snap)
    before = snap.model_dump(mode="json")
    llm = QueueLLM([good_statement().model_dump(), {"issues": []},
                    good_verdict().model_dump(mode="json"), {"issues": []}])
    debater = Debater(llm, snap, background_context=context)
    moderator = Moderator(llm, snap, background_context=context)
    assert debater.background is debater.reviewer.background
    assert moderator.background is moderator.reviewer.background
    assert debater.background == moderator.background
    assert debater.speak(Side.BULL, "opening", [], verify=lambda s: verify(s, snap))[-1].verification.passed
    assert moderator.evaluate([], {}, extra_allowed=False).decision.value == "HOLD"
    for conv, _ in llm.calls:
        assert conv.system.endswith(BACKGROUND_RULES + render_background(context))
        assert conv.system.count("RAG_UNIQUE_DEFINITION") == 1
        assert "Fact에 없는 RSI·MACD·EPS·수급" in conv.system
    for index in (1, 3):
        payload = json.loads(llm.calls[index][0].messages[0]["content"])
        assert set(payload["facts"]) == {"PX.CLOSE"}
        assert "RAG_UNIQUE_DEFINITION" not in canonical_json(payload)
    assert snap.model_dump(mode="json") == before


def test_context_copy_mutation_cannot_change_existing_agent_input(snap):
    context = context_for(snap)
    reviewer = SemanticReviewer(QueueLLM([{"issues": []}]), snap, background_context=context)
    frozen = reviewer.background
    copy = context.payload
    copy["items"][0]["text"] = "changed instruction"
    reviewer.check(good_statement(), [], ["PX.CLOSE"])
    assert reviewer.background == frozen
    assert "changed instruction" not in reviewer.llm.calls[0][0].system


@pytest.mark.parametrize("constructor", [Debater, Moderator, SemanticReviewer])
def test_context_snapshot_mismatch_rejected_before_any_call(snap, constructor):
    llm = QueueLLM([])
    with pytest.raises(ValueError, match="does not match"):
        constructor(llm, snap, background_context=context_for(snap, snapshot_id="different-snapshot"))
    assert llm.calls == []


def test_no_background_keeps_original_review_system(snap):
    llm = QueueLLM([{"issues": []}])
    SemanticReviewer(llm, snap).check(good_statement(), [], ["PX.CLOSE"])
    assert llm.calls[0][0].system == SYSTEM
    assert Debater(llm, snap).background == Moderator(llm, snap).background == ""


@pytest.mark.parametrize("private", ["[K1]", "[K.definition]", "K.definition", "KCTX.fixture",
                                     "C.fixture", "R.fixture", "A.fixture"])
@pytest.mark.parametrize("field", ["claim", "argument", "interpretation"])
def test_statement_private_knowledge_ids_rejected_in_all_public_prose(private, field):
    candidate = good_statement()
    if field == "interpretation":
        candidate.evidence[0].interpretation += " " + private
    else:
        setattr(candidate, field, getattr(candidate, field) + " " + private)
    assert any(i.code == "private_knowledge_reference" for i in statement_issues(candidate, "opening", set()))


@pytest.mark.parametrize("field", ["reasoning", "bull", "bear", "extra_question"])
def test_moderator_private_knowledge_ids_rejected_in_all_public_prose(field):
    candidate = good_verdict()
    if field in {"bull", "bear"}:
        getattr(candidate, field).comment = "배경 [K1]"
    elif field == "extra_question":
        candidate.extra_question = "KCTX.fixture"
    else:
        candidate.reasoning += " KCTX.fixture"
    assert any(i.code == "private_knowledge_reference" for i in moderator_issues(candidate))


def test_public_e_fact_citations_and_general_concepts_remain_valid():
    assert knowledge_leakage_issues("PER은 이익 대비 가격이며 변동성은 방향을 보장하지 않는다 [E1].") == []
    assert statement_issues(good_statement(), "opening", set()) == []
    assert moderator_issues(good_verdict()) == []


def test_knowledge_cannot_be_fact_or_count_as_new_market_evidence(snap):
    candidate = good_statement()
    candidate.evidence[0].source_id = "K.definition"
    result = verify(candidate, snap)
    assert not result.passed and result.correct == 0
    assert any(i.code == "unknown_source" for i in result.issues)
    assert used_sources(["근거:\n  E1: K.definition = null\n  E2: C.fixture = null"], snap) == set()


def test_public_knowledge_leak_stops_before_model_review(snap):
    candidate = good_statement()
    candidate.argument += " [K1]"
    llm = QueueLLM([candidate.model_dump()])
    attempts = Debater(llm, snap, max_retries=0, background_context=context_for(snap)).speak(
        Side.BULL, "opening", [], verify=lambda s: verify(s, snap))
    assert not attempts[-1].verification.passed
    assert any(i.code == "private_knowledge_reference" for i in attempts[-1].verification.issues)
    assert len(llm.calls) == 1

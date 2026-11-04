"""Exercise the real agent tool loop and scheduler with an in-process mock transport."""

import json
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace as NS

import pytest

from bullbear.graph import Mediation, build_debate_graph
from bullbear.llm import LLM, LLMError
from bullbear.snapshot import build_snapshot

from .fakes import NOW, FakeSource, statement


class MockModel:
    def __init__(self, barrier, tool, value):
        self.barrier = barrier
        self.tool = tool
        self.value = value
        self.prompts = []
        self.observations = []

    @contextmanager
    def stream(self, *, messages, model, **kwargs):
        if len(messages) == 1:
            self.prompts.append(messages[0]["content"])
            if len(self.prompts) == 1:
                self.barrier.wait(timeout=5)
            content = [NS(type="tool_use", id="t1", name=self.tool, input={})]
        else:
            result = messages[-1]["content"][0]
            assert result["tool_use_id"] == "t1" and not result.get("is_error")
            self.observations.append(result["content"])
            fact = json.loads(result["content"])
            value = fact["value"] if self.value is None else self.value
            answer = statement(("E1", fact["id"], value))
            content = [NS(type="text", text=answer.model_dump_json())]
        message = NS(model=model, usage=NS(input_tokens=1, output_tokens=1),
                     stop_reason="end_turn", content=content)
        yield MockStream(message)

    def llm(self):
        return LLM("claude-sonnet-5-5", client=NS(beta=NS(messages=self)))


class MockStream:
    def __init__(self, message):
        self.message = message

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.message


def run(actions, *, value=None):
    snapshot = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    barrier = Barrier(2)
    bull = MockModel(barrier, "get_price_metrics", value)
    bear = MockModel(barrier, "get_financials", value)
    seen = []
    actions = iter(actions)

    def mediator(state):
        # No initial review until both branches have finished their own tool loops.
        seen.append((len(state["bull"]), len(state["bear"]), list(state.get("research_results", []))))
        action = next(actions)
        return Mediation(action=action, reason=f"검토 {len(seen)}",
                         tool="get_disclosures" if action == "REQUEST_RESEARCH" else None)

    def mock_tools(snap):
        assert snap.snapshot_id == snapshot.snapshot_id
        def lookup(name, args):
            category = {"get_price_metrics": "price", "get_financials": "financials",
                        "get_disclosures": "disclosure"}[name]
            fact = snap.by_category(category)[0]
            return json.dumps({"tool": name, "id": fact.id, "value": fact.value})

        return lookup

    graph = build_debate_graph(bull=bull.llm(), bear=bear.llm(), mediate=mediator,
                               tool_factory=mock_tools)
    state = graph.invoke({"snapshot": snapshot})
    assert next(actions, None) is None
    return state, seen, bull, bear


@pytest.mark.parametrize("count", range(4))
def test_parallel_start_and_selective_challenges(count):
    actions = ["CHALLENGE_BULL", "CHALLENGE_BEAR", "CHALLENGE_BULL"][:count] + ["ACCEPT"]
    state, seen, bull, bear = run(actions)
    assert seen == [(1, 1, []), (2, 1, []), (2, 2, []), (3, 2, [])][:count + 1]
    assert [d.action for d in state["decisions"]] == actions
    assert state["status"] == "accepted" and state["extra_rounds"] == count
    for model, analyses in ((bull, state["bull"]), (bear, state["bear"])):
        assert len(model.prompts) == len(analyses) == len(model.observations)
        assert all(a.tool_calls == (model.tool,) for a in analyses)
        assert all(json.loads(result)["tool"] == model.tool for result in model.observations)
    if count:
        assert "검토 1" in bull.prompts[1]


def test_research_returns_observation_directly_to_mediator_then_abstains():
    state, seen, _, _ = run(["REQUEST_RESEARCH", "ABSTAIN"])
    assert seen == [(1, 1, []), (1, 1, state["research_results"])]
    assert [json.loads(r)["tool"] for r in state["research_results"]] == ["get_disclosures"]
    assert state["status"] == "abstained" and state["extra_rounds"] == 1


@pytest.mark.parametrize("fourth", ["REQUEST_RESEARCH", "CHALLENGE_BULL", "CHALLENGE_BEAR"])
def test_fourth_dispatch_is_blocked_even_for_mixed_routes(fourth):
    state, seen, _, _ = run(["REQUEST_RESEARCH", "CHALLENGE_BEAR", "REQUEST_RESEARCH", fourth])
    assert len(seen) == 4
    assert (len(state["bull"]), len(state["bear"]), len(state["research_results"])) == (1, 2, 2)
    assert state["status"] == "round_limit" and state["extra_rounds"] == 3
    assert state["decisions"][-1].action == fourth


def test_invalid_statement_stops_before_mediation():
    with pytest.raises(LLMError, match="value_mismatch"):
        run([], value=999)

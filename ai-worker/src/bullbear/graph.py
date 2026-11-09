"""Independent worker graph. Invoke with {"snapshot": snapshot} and injected agents."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .llm import Conversation, LLM, LLMError, ToolHandler
from .schemas import STATEMENT_SCHEMA, Side, Statement, Decision, SideScore, ModeratorAnalysis
from .snapshot import Snapshot
from .tools import TOOL_CATEGORIES, TOOL_DEFINITIONS, SnapshotTools
from .verifier import verify

MAX_EXTRA_ROUNDS = 3


class GraphForecast(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reasoning: str
    decisive_evidence: list[str]
    bull: SideScore
    bear: SideScore
    analysis: ModeratorAnalysis


class Mediation(BaseModel):
    action: Literal["ACCEPT", "REQUEST_RESEARCH", "CHALLENGE_BULL", "CHALLENGE_BEAR", "ABSTAIN"]
    reason: str = Field(min_length=1)
    # REQUEST_RESEARCH selects a read-only snapshot tool.
    tool: str | None = None
    forecast: GraphForecast | None = None


class GraphInput(TypedDict):
    snapshot: Snapshot


@dataclass(frozen=True)
class Analysis:
    statement: Statement
    tool_calls: tuple[str, ...]


class DebateState(GraphInput, total=False):
    bull: list[Analysis]
    bear: list[Analysis]
    decisions: list[Mediation]
    research_results: list[str]
    extra_rounds: int
    status: Literal["running", "accepted", "abstained", "round_limit"]


ToolFactory = Callable[[Snapshot], ToolHandler]


def build_debate_graph(
    *, bull: LLM, bear: LLM, mediate: Callable[[DebateState], Mediation],
    tool_factory: ToolFactory = SnapshotTools,
    analyze: Callable[[Side, DebateState, LLM], Analysis] | None = None,
    max_extra_rounds: int = MAX_EXTRA_ROUNDS,
    fixed_rounds: bool = False,
):
    """Build a standalone graph. Each role owns its LLM conversation and usage."""
    if bull is bear:
        raise ValueError("Bull and Bear require independent LLM instances")
    if not 0 <= max_extra_rounds <= MAX_EXTRA_ROUNDS:
        raise ValueError("max_extra_rounds must be between 0 and 3")
    if fixed_rounds and analyze is None:
        raise ValueError("Fixed rounds require a round-aware analyze callback")
    analyze_callback = analyze

    def analyst(side: Side, llm: LLM):
        def analyze(state: DebateState):
            if analyze_callback is not None:
                analysis = analyze_callback(side, state, llm)
                return {side.value: [*state.get(side.value, []), analysis]}
            snapshot = state["snapshot"]
            history = state.get(side.value, [])
            task = f"{snapshot.name} ({snapshot.ticker}), 기준일 {snapshot.as_of}"
            if history:
                previous = history[-1].statement.model_dump_json()
                task += f"\n이전 분석: {previous}\n재검토 요청: {state['decisions'][-1].reason}"
            conversation = Conversation(
                system=f"{side.label} 측에서 가설과 반증을 조사하고 조회한 근거 ID를 인용하세요.",
                messages=[{"role": "user", "content": task}],
            )
            calls = []
            handler = tool_factory(snapshot)

            def call_tool(name: str, arguments: dict):
                calls.append(name)
                return handler(name, arguments)

            raw = llm.structured(conversation, schema=STATEMENT_SCHEMA, effort="medium",
                                 tools=TOOL_DEFINITIONS, tool_handler=call_tool)
            statement = Statement.model_validate(raw)
            result = verify(statement, snapshot)
            if not result.passed:
                raise LLMError(result.feedback())
            return {side.value: [*history, Analysis(statement, tuple(calls))]}

        return analyze

    def review(state: DebateState):
        decision = Mediation.model_validate(mediate(state))
        rounds = state.get("extra_rounds", 0)
        if decision.action == "ACCEPT":
            status = "accepted"
        elif decision.action == "ABSTAIN":
            status = "abstained"
        elif rounds >= max_extra_rounds:
            status = "round_limit"
        else:
            status = "running"
            rounds += 1
        return {"decisions": [*state.get("decisions", []), decision],
                "extra_rounds": rounds, "status": status}

    def route(state: DebateState):
        if state["status"] != "running":
            return END
        return {"REQUEST_RESEARCH": "research", "CHALLENGE_BULL": "analyze_bull",
                "CHALLENGE_BEAR": "analyze_bear"}[state["decisions"][-1].action]

    def research(state: DebateState):
        tool = state["decisions"][-1].tool
        if tool not in TOOL_CATEGORIES:
            raise ValueError(f"Unknown research tool: {tool}")
        observation = tool_factory(state["snapshot"])(tool, {})
        return {"research_results": [*state.get("research_results", []), observation]}

    graph = StateGraph(DebateState, input_schema=GraphInput)
    if fixed_rounds:
        # Explicit joins ensure both speakers see the complete previous round.
        previous = None
        for stage in ('opening', 'rebuttal', 'closing'):
            nodes = [f'{stage}_{side.value}' for side in Side]
            for side, llm, node in zip(Side, (bull, bear), nodes):
                graph.add_node(node, analyst(side, llm))
                graph.add_edge(START if previous is None else previous, node)
            join = f'{stage}_complete'
            graph.add_node(join, lambda state: {})
            graph.add_edge(nodes, join)
            previous = join
        graph.add_node('mediator', review)
        graph.add_edge(previous, 'mediator')
        graph.add_edge('mediator', END)
        return graph.compile()
    graph.add_node("analyze_bull", analyst(Side.BULL, bull))
    graph.add_node("analyze_bear", analyst(Side.BEAR, bear))
    graph.add_node("mediator", review)
    graph.add_node("research", research)
    for node in ("analyze_bull", "analyze_bear"):
        graph.add_edge(START, node)
        # Both initial updates arrive in one superstep. A challenge activates only one.
        graph.add_edge(node, "mediator")
    graph.add_edge("research", "mediator")
    graph.add_conditional_edges("mediator", route, ["analyze_bull", "analyze_bear", "research", END])
    return graph.compile()

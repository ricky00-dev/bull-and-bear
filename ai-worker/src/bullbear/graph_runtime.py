"""Live LangGraph nodes and the legacy HTTP wire-format adapter.

The graph owns scheduling. This module owns model I/O, required shape recovery
and publication; both speakers join after each of three fixed rounds.
"""
import threading

from pydantic import ValidationError

from . import prompts
from .context_ids import RequestIds
from .chart_image import daily_chart_image
from .graph import Analysis, Mediation, build_debate_graph
from .interpretations import bind_statement
from .history_lookup import STATEMENT_DETAIL_TOOL, HistoryLookup
from .llm import Conversation, LLMError
from .model_context import full_model_history, model_history
from .model_wire import (statement_wire_schema, expand_statement_response, mediation_wire_schema,
                         expand_mediation_response, WIRE_STATEMENT_RULES, WIRE_MEDIATION_RULES)
from .news_lookup import NewsLookup
from .schemas import Side, Statement
from .shared_context import build_shared_push, build_moderator_context, referenced_fact_context
from .tools import DEBATE_TOOL_DEFINITIONS, SnapshotTools


# Tools and the output schema lead the cached prefix, so every debater request
# sends these exact objects; get_statement_details is offered even before any
# turn exists (unknown IDs are refused by HistoryLookup).
STATEMENT_WIRE_SCHEMA = statement_wire_schema()
DEBATE_TOOLS = [*DEBATE_TOOL_DEFINITIONS, STATEMENT_DETAIL_TOOL]
MEDIATION_SCHEMA = mediation_wire_schema()
_STAGES = ('opening', 'rebuttal', 'closing', 'verdict')
# Upper bound on Bear's opening wait for Bull's response to start (see analyze).
_PREFIX_WAIT_SECONDS = 30
# Debater-only paragraphs (the student game, stance, lookup, writing) are not
# inherited; only the shared block that both roles need follows.
MEDIATOR_SYSTEM = """당신은 이 투자 교육 토론의 중재자다. 학생은 여섯 발언을 읽고 이미 자기 판정을 냈고, 이제 당신의 판정과 자기 판정을 비교하며 배운다. 그래서 학생에게 필요한 것은 분명한 의견 하나와 그 의견을 가른 사실이 무엇이었는지다. 공정한 심판처럼 차분하고 쉬운 해요체로 쓰고, 지표 이름이나 투자 용어는 학생이 처음 듣는 말이라고 생각하고 풀어 쓰며, 숫자는 읽기 쉽게 어림해 쓴다.

토론자는 배정된 입장을 변호하도록 되어 있어서 두 입장은 독립된 두 표가 아니고, 말투나 확신의 세기는 증거가 아니다. 판정은 자료에서 나온다. 당신은 스냅샷의 수치 자료 전체(최근 20거래일의 날짜별 일봉 포함)와 여섯 발언의 전체 기록(근거별 해석·가정·한계, 반박과 최종변론의 상세)을 받는다. 토론자가 든 수치·날짜는 이 자료에서 확인하고, 더 앞선 일봉이나 기사 내용은 read_snapshot으로 확인한다. 토론자가 무엇을 말했고 무엇에 답했는지는 전체 기록에서 찾는다. 확인된 자료가 어느 쪽 읽기와 더 잘 맞는지로 의견을 정하고, 토론자가 놓친 중요한 사실이 있으면 그것도 판정에 쓴다. 이 종목의 수치·사건·뉴스는 받은 자료와 조회한 자료에 있는 것만 쓰고, 비율과 차이는 자료에 있는 값을 쓴다.

의견은 확인한 근거 가운데 어느 쪽이 더 무거운지로 정하고, 그 판단이 얼마나 굳은지는 확신도로 나타낸다. 근거의 무게는 크기, 같은 방향을 가리키는 다른 자료가 있는지, 짧은 기간의 우연으로 설명될 수 있는지로 따진다. 양쪽에 근거가 하나씩 있다는 것만으로는 보유가 아니다. 보유는 두 힘을 따져 보니 실제로 맞먹는다는 판단이다. 빠진 자료 때문에 생기는 불확실성은 확신도에 담고, 판단에 꼭 필요한 자료가 없어 어느 쪽도 가릴 수 없을 때만 판단을 유보한다. 수익을 약속하거나, 매매를 권하거나, 목표 가격을 말하지 않고 의견으로 말한다.

토론자의 평가와 점수는 학생이 보는 요약·본문·근거 칩을 기준으로 하고, 내부 기록은 그 발언이 무엇을 전제했는지 확인하는 데 쓴다. 토론자를 평가할 때는 추론의 질을 본다. 든 사실과 지표의 뜻이 정확한지, 그 사실에서 결론까지 이어지는 고리가 합리적인지, 상대의 실제 주장에 답했는지, 자기 논거가 틀릴 수 있는 지점을 알고 있는지다. 자료에서 합리적으로 이어지는 해석은 자료에 그대로 적혀 있지 않아도 정당한 논증이다. 양측이 다르게 한 만큼 평가와 점수도 다르게 매긴다.
""" + prompts.DEBATE_SHARED_RULES

MEDIATOR_OUTPUT_INSTRUCTIONS = """
매수·보유·매도 의견을 낸다. 판단에 필요한 자료가 없으면 판단을 유보한다(action=ABSTAIN). confidence는 이 의견이 얼마나 굳은지를 0~1로 나타내며, 확인한 근거가 한쪽으로 모일수록 높고 엇갈릴수록 낮다.
reasoning은 학생 화면에 나오는 유일한 해설이다. 의견을 가른 사실과 그 사실을 어떻게 읽었는지를 담고, 토론에서 사실이나 지표의 뜻이 잘못 쓰인 곳이 있었다면 가장 중요한 하나를 바로잡는다. 이 모두를 한 문단·한국어 최대 3문장에 담는다. 근거 ID 1~3개를 [E1]부터 순서대로 인용한다.
각 측의 comment는 그 측이 가장 잘한 점이나 가장 약했던 고리를 구체적으로 짚는 한 문장이다. 여섯 발언 ID를 각각 한 번씩 검토하고 이유와 확인한 Fact ID를 적는다.
검토 결과는 셋 중 하나다. no_issue_found는 사실과 추론에서 고칠 점을 찾지 못한 발언, concern은 사실 오류나 결론을 흔드는 추론의 빈틈이 있는 발언, uncertain은 결론이 자료로 가릴 수 없는 전제에 크게 기대는 발언이다. 검토 이유는 그 결과를 고른 이유다.
점수는 이 토론의 실제 발언을 기준으로 1(거의 못함)~5(매우 잘함)로 매긴다. relevance는 논거가 이 종목의 지금 상황과 맞닿아 있는지, materiality는 든 근거가 결론을 좌우할 만큼 중요한지, rebuttal은 상대의 실제 주장에 답했는지, risk_awareness는 자기 논거가 틀릴 조건을 알고 있는지다.
""" + WIRE_MEDIATION_RULES


class GraphStopped(LLMError):
    def __init__(self, status):
        self.graph_status = status
        super().__init__('LangGraph ended without an accepted forecast')


class MediationFailed(LLMError):
    reason = 'moderator_validation_failed'


class GraphRuntime:
    def __init__(self, snapshot, *, debate_id, bull, bear, moderator, log, emit=None,
                 max_extra_rounds=1, debater_effort='medium', moderator_effort='high',
                 include_chart_image=True, news_web_fetch=False):
        self.snapshot, self.debate_id, self.log = snapshot, debate_id, log
        self.bull, self.bear, self.moderator = bull, bear, moderator
        self.debater_context = {'shared_push': build_shared_push(snapshot)}
        self.chart_image = daily_chart_image(snapshot) if include_chart_image else None
        self.emit_hook = emit or (lambda *_: None)
        if not 0 <= max_extra_rounds <= 3:
            raise ValueError("max_extra_rounds must be between 0 and 3")
        # Accepted for caller compatibility; fixed rounds never schedule extras.
        self.debater_effort, self.moderator_effort = debater_effort, moderator_effort
        self.lock = threading.RLock()
        self.opening_prefix_cached = threading.Event()
        self.bull_opening_failed = False
        self.news_web_fetch = news_web_fetch
        self.news_results = {}

    def news_lookup(self, stage, role):
        with self.lock:
            previous = {}
            for earlier in _STAGES[:_STAGES.index(stage)]:
                for side in Side:
                    for key, result in self.news_results.get((earlier, side.value), {}).items():
                        if previous.get(key, {}).get('status') != 'body':
                            previous[key] = result

        def record(source_id, result):
            with self.lock:
                self.log.append('news_fetch_result', role=role, round=stage, source_id=source_id, **result)

        return NewsLookup(self.snapshot, enabled=self.news_web_fetch,
                          previous=previous, record=record, require_summary_lookup=True)

    def emit(self, event, payload):
        # Parallel initial nodes must not interleave event sequence assignment.
        with self.lock:
            self.log.append(event, **payload)
            self.emit_hook(event, payload)

    @staticmethod
    def transcript(state):
        """Render model history with citation IDs and the original speech text."""
        return [prompts.render_statement(side, ('opening', 'rebuttal', 'closing')[index],
                                        state[side.value][index].statement, include_observation=False)
                for index in range(3) for side in Side if index < len(state.get(side.value, []))]

    def analyze(self, side, state, llm):
        if state.get(side.value):  # Later rounds start after both openings.
            return self.statement(side, state, llm)
        # Simultaneous requests cannot read each other's cache writes, so Bear's
        # opening starts once Bull's response has begun and reads the shared prefix.
        if side == Side.BULL:
            try:
                return self.statement(side, state, llm, announce=True)
            except BaseException:
                self.bull_opening_failed = True  # Set before Bear can wake.
                raise
            finally:
                self.opening_prefix_cached.set()  # Never leave Bear waiting.
        if not self.opening_prefix_cached.wait(timeout=_PREFIX_WAIT_SECONDS):
            with self.lock:
                self.log.append('opening_wait', side=side, outcome='timeout')
        if self.bull_opening_failed:
            # The debate cannot finish without Bull, so skip a billable request.
            with self.lock:
                self.log.append('opening_wait', side=side, outcome='bull_failed')
            raise LLMError("Bear opening skipped because Bull's opening failed")
        return self.statement(side, state, llm)

    def statement(self, side, state, llm, *, announce=False):
        history = state.get(side.value, [])
        stage = _STAGES[len(history)]
        opponent = Side.BEAR if side == Side.BULL else Side.BULL
        opponent_ids = {turn.statement.statement_id for turn in state.get(opponent.value, [])}
        transcript = self.transcript(state)
        history_lookup = HistoryLookup(transcript)
        ids = RequestIds(self.snapshot, transcript)
        news = self.news_lookup(stage, side.value)
        payload = {'task': prompts.DEBATER_TASKS[stage],
                   'output_instructions': prompts.COMPACT_STATEMENT_STYLE + WIRE_STATEMENT_RULES[stage],
                   'round': stage, 'assigned_outlook': 'BUY' if side == Side.BULL else 'SELL',
                   'history': model_history(transcript, role='debater', side=side, round_kind=stage),
                   'research_results': state.get('research_results', []),
                   **referenced_fact_context(self.snapshot, transcript)}
        # Asking for an article when the snapshot has none put "no article" lines
        # in public text. This request JSON sits after the cached prefix.
        if stage == 'opening' and sum(self.debater_context['shared_push']['news_available'].values()) > 0:
            payload['output_instructions'] += prompts.OPENING_NEWS_INSTRUCTIONS
        if news.results:
            payload['news_lookup_results'] = dict(news.results)
        images = [self.chart_image] if stage == 'opening' and self.chart_image is not None else None
        conv = Conversation.from_snapshot(prompts.debater_role(side), ids.encode_context(self.debater_context),
                                          ids.encode_context(payload), images=images,
                                          common_system=prompts.DEBATER_COMMON_SYSTEM)
        conv.context_ids = ids
        self.emit('turn_started', {'side': side, 'round': stage, 'engine': 'langgraph',
                                   'debate_flow': 'fixed_three_rounds'})
        calls = []
        tools = SnapshotTools(self.snapshot)
        def tool(name, arguments):
            calls.append(name)
            self.emit('tool_call', {'side': side, 'tool': name})
            return history_lookup(arguments) if name == 'get_statement_details' else news.handle_tool(tools, name, arguments)
        def on_event(event, payload):
            if announce and event == 'stream_started':
                self.opening_prefix_cached.set()
            news.observe(event, payload)

        for attempt in range(1, 4):
            raw = llm.structured(conv, schema=STATEMENT_WIRE_SCHEMA, effort=self.debater_effort,
                                 tools=DEBATE_TOOLS, tool_handler=ids.wrap_tool_handler(tool),
                                 on_event=on_event)
            try:
                statement = Statement.model_validate(ids.decode_response(expand_statement_response(raw, stage)))
                rebuttal = statement.analysis.rebuttal if statement.analysis else None
                if rebuttal is not None and rebuttal.target_statement_id not in opponent_ids:
                    # Observed: the whole row filled with '[@S1] "quote": comment' prose.
                    raise ValueError('Rebuttal target is not an opponent statement ID')
            except (ValueError, ValidationError):
                # A response must be decodable into the public data contract.
                # This retry does not assess source correctness or prose quality.
                self.emit('statement_rejected', {'side': side, 'round': stage, 'attempt': attempt,
                    'category': 'schema', 'issues': [
                        {'severity': 'error', 'code': 'invalid_schema', 'message': '발언 형식 오류'}]})
                conv.messages.append({'role': 'user', 'content':
                    '응답 형식이 잘못되었습니다. 제공된 압축 출력 스키마에 맞춰 다시 작성하세요. ' + WIRE_STATEMENT_RULES[stage]})
                continue
            with self.lock:
                self.log.append('statement_attempt', side=side, round=stage, attempt=attempt,
                                statement=statement, verification=None)
                self.news_results[(stage, side.value)] = news.results
            statement = bind_statement(statement, self.snapshot,
                debate_id=f'{self.debate_id}:{side.value}', turn_index=len(history) + 1)
            self.emit('statement_accepted', {'side': side, 'round': stage, 'attempts': attempt,
                'verified': False, 'verification_scope': 'not_checked', 'statement': statement,
                'verification': None, 'engine': 'langgraph'})
            return Analysis(statement, tuple(calls))
        raise LLMError('Graph statement response shape was invalid after retries')

    def mediate(self, state):
        self.emit('moderator_started', {'engine': 'langgraph'})
        transcript = self.transcript(state)
        history_lookup = HistoryLookup(transcript)
        ids = RequestIds(self.snapshot, transcript)
        news = self.news_lookup('verdict', 'moderator')
        tools = SnapshotTools(self.snapshot)
        conv = Conversation.from_snapshot(MEDIATOR_SYSTEM,
            ids.encode_context(build_moderator_context(self.snapshot, transcript)), ids.encode_context({
                'task': '양측의 여섯 발언을 검토하고, 자료를 직접 확인한 뒤 이 종목에 대한 독립적인 의견을 내세요.',
                'output_instructions': MEDIATOR_OUTPUT_INSTRUCTIONS,
                'history': full_model_history(transcript),
                'research_results': state.get('research_results', []),
                **({'news_lookup_results': dict(news.results)} if news.results else {}),
                'remaining_actions': 0}))
        conv.context_ids = ids
        for attempt in range(1, 4):
            raw = self.moderator.structured(conv, schema=MEDIATION_SCHEMA, effort=self.moderator_effort,
                tools=DEBATE_TOOLS,
                tool_handler=ids.wrap_tool_handler(lambda name, arguments: history_lookup(arguments)
                    if name == 'get_statement_details' else news.handle_tool(tools, name, arguments)), on_event=news.observe)
            try:
                decision = Mediation.model_validate(ids.decode_response(expand_mediation_response(raw)))
                if decision.action not in ('ACCEPT', 'ABSTAIN'):
                    raise ValueError('Fixed debate permits only ACCEPT or ABSTAIN')
                if decision.tool is not None:
                    raise ValueError('Unexpected tool')
                if (decision.action == 'ACCEPT') != (decision.forecast is not None):
                    raise ValueError('Only ACCEPT requires a forecast')
            except (ValueError, ValidationError):
                self.log.append('moderator_rejected', attempt=attempt, category='schema_or_action',
                                issue_codes=['invalid_mediation'])
                conv.messages.append({'role': 'user', 'content':
                    '응답 형식이 잘못되었습니다. 압축된 action/reason/forecast 스키마에 맞춰 다시 작성하세요. ' + WIRE_MEDIATION_RULES})
                continue
            with self.lock:
                self.log.append('graph_mediated', decision=decision)
            return decision
        raise MediationFailed('Graph mediation response shape was invalid after retries')

    def run(self):
        graph = build_debate_graph(bull=self.bull, bear=self.bear, mediate=self.mediate,
                                  analyze=self.analyze, max_extra_rounds=0, fixed_rounds=True)
        state = graph.invoke({'snapshot': self.snapshot})
        if state['status'] != 'accepted' or state['decisions'][-1].forecast is None:
            raise GraphStopped(state['status'])
        verdict = state['decisions'][-1].forecast.model_dump(mode='json')
        verdict['scores'] = {side.value: verdict.pop(side.value) for side in Side}
        stats = {}
        for side in Side:
            statements = len(state.get(side.value, []))
            stats[side.value] = {'statements': statements,
                'first_try_pass_rate': None, 'rejected_attempts': 0,
                'final_unverified_statements': statements, 'evidence_accuracy': None}
        return {'debate_id': self.debate_id, 'verdict': verdict, 'stats': stats,
                'engine': 'langgraph', 'graph_status': state['status']}

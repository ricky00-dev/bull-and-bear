"""Live LangGraph nodes and the legacy HTTP wire-format adapter.

The graph owns scheduling. This module owns model I/O, required shape recovery,
review and publication; both speakers join after each of three fixed rounds.
"""
from copy import deepcopy
import threading

from pydantic import ValidationError

from . import prompts
from .context_ids import RequestIds
from .chart_image import daily_chart_image
from .graph import Analysis, Mediation, build_debate_graph
from .interpretations import bind_statement
from .history_lookup import HistoryLookup
from .llm import Conversation, LLMError
from .model_context import model_history
from .model_wire import (statement_wire_schema, expand_statement_response, mediation_wire_schema,
                         expand_mediation_response, WIRE_STATEMENT_RULES, WIRE_MEDIATION_RULES)
from .news_lookup import NewsLookup
from .schemas import Side, Statement, STRUCTURED_MODERATOR_SCHEMA, compact_schema
from .shared_context import build_shared_push, build_moderator_context, referenced_fact_context
from .statement_review import review_statement
from .tools import DEBATE_TOOL_DEFINITIONS, SnapshotTools


def mediation_schema():
    forecast = deepcopy(STRUCTURED_MODERATOR_SCHEMA)
    definitions = forecast.pop('$defs', {})
    for key in ('action', 'extra_question'):
        forecast['properties'].pop(key)
        forecast['required'].remove(key)
    return compact_schema({'type': 'object', 'additionalProperties': False, '$defs': definitions,
            'properties': {'action': {'type': 'string', 'enum': ['ACCEPT', 'ABSTAIN']},
                           'reason': {'type': 'string'},
                           'tool': {'type': ['string', 'null']},
                           'forecast': {'anyOf': [forecast, {'type': 'null'}]}},
            'required': ['action', 'reason', 'tool', 'forecast']})


MEDIATION_SCHEMA = mediation_wire_schema()
_STAGES = ('opening', 'rebuttal', 'closing', 'verdict')
MEDIATOR_SYSTEM = """당신은 투자 교육 토론의 중립 중재자 부엉이다.
여섯 발언 모두를 근거와 대조하여 사실과 가정, 인과관계, 왜곡, 유지되거나 약해진 논거와 불확실성을 평가한다.
황소·곰에게 배정된 입장은 독립적인 투표가 아니다. 말투·확신·같은 모델 간 동의·유효한 ID와 값만으로 사실이나 예측이 입증되지는 않는다.
""" + prompts.DEBATE_RULES + prompts.SNAPSHOT_LOOKUP_RULES + prompts.MODEL_HISTORY_RULES

MEDIATOR_OUTPUT_INSTRUCTIONS = """
근거가 있는 BUY/HOLD/SELL 의견을 내고 판단할 수 없으면 ABSTAIN한다. ABSTAIN은 HOLD와 다르다. confidence는 보정된 확률이 아니다.
reasoning은 핵심 근거와 한계를 담은 한 문단·한국어 최대 3문장이다. 근거 ID 1~3개를 [E1]부터 순서대로 인용한다.
각 측의 comment는 한 문장이다. 여섯 발언 ID를 각각 한 번씩 검토하고 이유와 확인한 Fact ID를 적는다.
no_issue_found는 오류를 찾지 못했다는 뜻이며 옳음이 입증됐다는 뜻이 아니다. 미확인 해석은 한계와 평가에 반영한다.
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
                 statement_reviewers=None, include_chart_image=True, news_web_fetch=False):
        self.snapshot, self.debate_id, self.log = snapshot, debate_id, log
        self.bull, self.bear, self.moderator = bull, bear, moderator
        self.debater_context = {'shared_push': build_shared_push(snapshot)}
        self.chart_image = daily_chart_image(snapshot) if include_chart_image else None
        self.emit_hook = emit or (lambda *_: None)
        if not 0 <= max_extra_rounds <= 3:
            raise ValueError("max_extra_rounds must be between 0 and 3")
        # Accepted for caller compatibility; fixed rounds never schedule extras.
        self.debater_effort, self.moderator_effort = debater_effort, moderator_effort
        self.statement_reviewers = statement_reviewers or {}
        self.lock = threading.RLock()
        # Sonnet requests reserve a full context window; avoid two simultaneous
        # reviewer reservations exhausting a shared pilot budget unnecessarily.
        self.review_lock = threading.Lock()
        self.news_web_fetch = news_web_fetch
        self.news_results = {}

    def news_lookup(self, llm, stage, role):
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

        return NewsLookup(self.snapshot, enabled=self.news_web_fetch and
                          getattr(llm, 'model', '').startswith('claude-sonnet-5-5'),
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
        history = state.get(side.value, [])
        stage = _STAGES[len(history)]
        transcript = self.transcript(state)
        history_lookup = HistoryLookup(transcript)
        ids = RequestIds(self.snapshot, transcript)
        news = self.news_lookup(llm, stage, side.value)
        task = {
            'opening': '첫 주장: 관측·해석·가정·한계를 구분해 배정 입장을 논증하세요.',
            'rebuttal': '상대 첫 주장의 중요한 해석을 인용하고 인정·반박 이유·미해결 쟁점을 작성하세요.',
            'closing': '상대 반박을 읽고 유지된 주장·인정할 부분·남은 불확실성·전망을 바꿀 조건을 정리하세요. '
                       '새 논점과 새 근거는 필수가 아닙니다.',
        }[stage]
        payload = {'task': task, 'output_instructions': prompts.COMPACT_STATEMENT_STYLE + WIRE_STATEMENT_RULES[stage],
                   'round': stage, 'assigned_outlook': 'BUY' if side == Side.BULL else 'SELL',
                   'history': model_history(transcript, role='debater', side=side, round_kind=stage),
                   'research_results': state.get('research_results', []),
                   **referenced_fact_context(self.snapshot, transcript)}
        if news.results:
            payload['news_lookup_results'] = dict(news.results)
        images = [self.chart_image] if stage == 'opening' and self.chart_image is not None else None
        conv = Conversation.from_snapshot(prompts.debater_system(side), ids.encode_context(self.debater_context),
                                          ids.encode_context(payload), images=images)
        conv.context_ids = ids
        self.emit('turn_started', {'side': side, 'round': stage, 'engine': 'langgraph',
                                   'debate_flow': 'fixed_three_rounds'})
        calls = []
        tools = SnapshotTools(self.snapshot)
        def tool(name, arguments):
            calls.append(name)
            self.emit('tool_call', {'side': side, 'tool': name})
            return history_lookup(arguments) if name == 'get_statement_details' else news.handle_tool(tools, name, arguments)
        for attempt in range(1, 4):
            raw = llm.structured(conv, schema=statement_wire_schema(stage), effort=self.debater_effort,
                                 tools=news.tools([*DEBATE_TOOL_DEFINITIONS, *history_lookup.tools]),
                                 tool_handler=ids.wrap_tool_handler(tool), on_event=news.observe)
            try:
                statement = Statement.model_validate(ids.decode_response(expand_statement_response(raw, stage)))
            except (ValueError, ValidationError):
                # A response must be decodable into the public data contract.
                # This retry does not assess source correctness or prose quality.
                self.emit('statement_rejected', {'side': side, 'round': stage, 'attempt': attempt,
                    'category': 'schema', 'issues': [
                        {'severity': 'error', 'code': 'invalid_schema', 'message': '발언 형식 오류'}]})
                conv.messages.append({'role': 'user', 'content':
                    '응답 형식이 잘못되었습니다. 제공된 압축 출력 스키마에 맞춰 다시 작성하세요. ' + WIRE_STATEMENT_RULES[stage]})
                continue
            if side.value in self.statement_reviewers:
                with self.review_lock:
                    review = review_statement(self.statement_reviewers[side.value], statement,
                        self.snapshot, transcript, effort=self.moderator_effort,
                        side=side, round_kind=stage, news_results=news.results,
                        shared_context=self.debater_context, news_lookup=news)
                # Private audit only: unpublished text/reviews never enter the public event stream.
                with self.lock:
                    self.log.append('statement_reviewed', side=side, round=stage, attempt=attempt,
                                    statement=statement, review=review,
                                    original_verification=None)
                if review.revised_statement is not None:
                    statement = review.revised_statement
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
        news = self.news_lookup(self.moderator, 'verdict', 'moderator')
        tools = SnapshotTools(self.snapshot)
        conv = Conversation.from_snapshot(MEDIATOR_SYSTEM,
            ids.encode_context(build_moderator_context(self.snapshot, transcript)), ids.encode_context({
                'task': '양측의 입론·반박·최종변론 6개를 검토하고 종목에 대한 독립적인 의견을 작성하세요.',
                'output_instructions': MEDIATOR_OUTPUT_INSTRUCTIONS,
                'history': model_history(transcript, role='moderator'),
                'research_results': state.get('research_results', []),
                **({'news_lookup_results': dict(news.results)} if news.results else {}),
                'remaining_actions': 0}))
        conv.context_ids = ids
        for attempt in range(1, 4):
            raw = self.moderator.structured(conv, schema=MEDIATION_SCHEMA, effort=self.moderator_effort,
                tools=news.tools([*DEBATE_TOOL_DEFINITIONS, *history_lookup.tools]),
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

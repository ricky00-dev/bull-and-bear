"""Live LangGraph nodes and the legacy HTTP wire-format adapter.

The graph owns scheduling. This module owns model I/O, bounded validation and
publication; the graph joins both speakers after each of three fixed rounds.
"""
from copy import deepcopy
import json
import threading

from pydantic import ValidationError

from . import prompts
from .graph import Analysis, Mediation, build_debate_graph
from .interpretations import analysis_issues, bind_statement, history_records
from .llm import Conversation, LLMError
from .presentation import statement_issues, moderator_issues
from .schemas import (Side, Statement, ModeratorDecision, STRUCTURED_STATEMENT_SCHEMA,
                      STRUCTURED_MODERATOR_SCHEMA)
from .semantic import concept_issues
from .return_grounding import return_context, return_issues
from .source_grounding import source_context, source_issues
from .statement_review import review_statement
from .tools import SnapshotTools, TOOL_DEFINITIONS
from .verifier import verify, Issue, VerificationResult


def mediation_schema():
    forecast = deepcopy(STRUCTURED_MODERATOR_SCHEMA)
    definitions = forecast.pop('$defs', {})
    for key in ('action', 'extra_question'):
        forecast['properties'].pop(key)
        forecast['required'].remove(key)
    return {'type': 'object', 'additionalProperties': False, '$defs': definitions,
            'properties': {'action': {'type': 'string', 'enum': ['ACCEPT', 'ABSTAIN']},
                           'reason': {'type': 'string'},
                           'tool': {'type': ['string', 'null']},
                           'forecast': {'anyOf': [forecast, {'type': 'null'}]}},
            'required': ['action', 'reason', 'tool', 'forecast']}


MEDIATION_SCHEMA = mediation_schema()
MEDIATOR_SYSTEM = """당신은 투자 교육 토론의 중립적인 최종 중재자다. 양측은 배정된 입장을 논증하므로 그 결론을 독립적인 예측 투표로 세지 않는다.
공통 사실, 해석 차이, 반박으로 유지되거나 약해진 논거를 정리한다. 어느 논거가 자료로 더 잘 뒷받침되는지와 결론을 바꿀 불확실성을 설명한다.
발언을 원자료와 대조해 사실·가정 혼동, 근거 없는 인과, 상대 주장 왜곡, 역할 이탈을 살핀다. 문체나 확신의 정도로 근거를 평가하지 않는다.
자료 ID와 인용값 검사가 출처 정확성·인과·예측의 보증은 아니다. 같은 자료·모델에 근거한 합의도 독립 검증으로 취급하지 않는다.
""" + prompts.DEBATE_RULES

MEDIATOR_OUTPUT_INSTRUCTIONS = """
- 추가 라운드나 조사 요청 없이 전망을 제출할 수 있으면 ACCEPT, 불가능하면 ABSTAIN을 선택한다. tool은 null이며 ACCEPT일 때만 forecast를 작성한다. ABSTAIN을 HOLD로 바꾸지 않는다.
- forecast.decision은 종목에 대한 BUY/HOLD/SELL 의견이며 confidence는 보정되지 않은 자기평가다.
- reasoning은 근거와 한계를 담은 한 문단·최대 3문장이다. 실제 Fact ID 1~3개를 decisive_evidence에 넣고 배열 순서대로 [E1]부터 인용한다.
- 양측은 relevance/materiality/rebuttal/risk_awareness를 각각 1~5로 평가하고 comment는 한 문장씩 쓴다.
- analysis에 공통 사실, 쟁점, 이견, 미검증 사항, 전망 근거와 한계를 구분한다. key_interpretation_ids에는 이력의 실제 해석 ID만 넣는다.
- statement_reviews에는 6개 발언 ID를 각각 한 번씩 넣는다. assessment는 no_issue_found/concern/uncertain 중 하나, reason에는 판단 이유, source_ids에는 대조한 Fact ID를 최대 3개(없으면 []) 넣는다. no_issue_found는 오류를 발견하지 못했다는 뜻이다.
- 확인되지 않은 해석을 전망의 확정 사실로 쓰지 말고 unverified/outlook_limits와 평가에 반영한다.
"""


class GraphStopped(LLMError):
    def __init__(self, status):
        self.graph_status = status
        super().__init__('LangGraph ended without an accepted forecast')


class MediationFailed(LLMError):
    reason = 'moderator_validation_failed'


class GraphRuntime:
    def __init__(self, snapshot, *, debate_id, bull, bear, moderator, log, emit=None,
                 max_extra_rounds=1, debater_effort='medium', moderator_effort='high',
                 statement_reviewers=None):
        self.snapshot, self.debate_id, self.log = snapshot, debate_id, log
        self.bull, self.bear, self.moderator = bull, bear, moderator
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
        self.attempts = {side.value: [] for side in Side}

    def emit(self, event, payload):
        # Parallel initial nodes must not interleave event sequence assignment.
        with self.lock:
            self.log.append(event, **payload)
            self.emit_hook(event, payload)

    @staticmethod
    def transcript(state):
        return [prompts.render_statement(side, ('opening', 'rebuttal', 'closing')[index],
                                        state[side.value][index].statement)
                for index in range(3) for side in Side if index < len(state.get(side.value, []))]

    def analyze(self, side, state, llm):
        history = state.get(side.value, [])
        stage = ('opening', 'rebuttal', 'closing')[len(history)]
        transcript = self.transcript(state)
        task = {
            'opening': '첫 주장: 관측·해석·가정·한계를 구분해 배정 입장을 논증하세요.',
            'rebuttal': '상대 첫 주장의 중요한 해석을 인용하고 인정·반박 이유·미해결 쟁점을 작성하세요.',
            'closing': '상대 반박을 읽고 유지된 주장·인정할 부분·남은 불확실성·전망을 바꿀 조건을 정리하세요. '
                       '새 논점과 새 근거는 필수가 아닙니다.',
        }[stage]
        payload = {'task': task, 'output_instructions': prompts.DEBATER_OUTPUT_INSTRUCTIONS,
                   'round': stage, 'assigned_outlook': 'BUY' if side == Side.BULL else 'SELL',
                   'ticker': self.snapshot.ticker, 'name': self.snapshot.name, 'price_as_of': str(self.snapshot.as_of),
                   'history': transcript,
                   'return_context': return_context(self.snapshot),
                   'source_context': source_context(self.snapshot),
                   'research_results': state.get('research_results', []),
                   'decision_at': self.snapshot.created_at.isoformat()}
        conv = Conversation(prompts.debater_system(side),
            [{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}])
        self.emit('turn_started', {'side': side, 'round': stage, 'engine': 'langgraph',
                                   'debate_flow': 'fixed_three_rounds'})
        calls = []
        tools = SnapshotTools(self.snapshot)
        def tool(name, arguments):
            calls.append(name)
            self.emit('tool_call', {'side': side, 'tool': name})
            return tools(name, arguments)
        for attempt in range(1, 4):
            raw = llm.structured(conv, schema=STRUCTURED_STATEMENT_SCHEMA, effort=self.debater_effort,
                                 tools=TOOL_DEFINITIONS, tool_handler=tool)
            try:
                statement = Statement.model_validate(raw)
            except ValidationError:
                failure = VerificationResult(passed=False, checked=0, correct=0,
                    issues=[Issue(severity='error', code='invalid_schema', message='발언 형식 오류')])
                with self.lock:
                    self.attempts[side.value].append((len(history), failure))
                self.emit('statement_rejected', {'side': side, 'round': stage, 'attempt': attempt,
                    'issues': failure.issues})
                conv.messages.append({'role': 'user', 'content': '필수 analysis와 발언 스키마를 지켜 다시 작성하세요.'})
                continue
            result = verify(statement, self.snapshot)
            # Source correctness is independent of the application's later scoring.
            issues = list(result.issues)
            refs = {e.ref: e.source_id for e in statement.evidence}
            for text in (statement.claim, statement.argument):
                issues += return_issues(text, self.snapshot, refs)
                issues += source_issues(text, self.snapshot, refs)
            for evidence in statement.evidence:
                issues += return_issues(f'[{evidence.ref}] ' + evidence.interpretation, self.snapshot, refs)
                issues += source_issues(f'[{evidence.ref}] ' + evidence.interpretation, self.snapshot, refs)
            issues += statement_issues(statement, stage, set())
            issues += analysis_issues(statement, transcript=transcript, side=side, round_kind=stage)
            expected = 'BUY' if side == Side.BULL else 'SELL'
            if statement.analysis is not None and statement.analysis.outlook != expected:
                issues.append(Issue(severity='error', code='role_mismatch',
                    message=f'배정 입장 {expected}를 유지하세요. 지지가 약하면 가정·한계에 명시하고 사실을 만들지 마세요.'))
            issues += concept_issues('\n'.join([statement.claim, statement.argument,
                                              *(e.interpretation for e in statement.evidence)]))
            # Stylistic/semantic concerns are moderator inputs, not generation gates.
            deferred = {'argument_length', 'money_unit', 'concept_error'}
            issues = [i.model_copy(update={'severity': 'warning'}) if i.code in deferred else i for i in issues]
            result = result.model_copy(update={'issues': issues,
                                               'passed': not any(i.severity == 'error' for i in issues)})
            if result.passed and side.value in self.statement_reviewers:
                with self.review_lock:
                    review = review_statement(self.statement_reviewers[side.value], statement,
                        self.snapshot, transcript, effort=self.moderator_effort)
                # Private audit only: unpublished text/reviews never enter the public event stream.
                with self.lock:
                    self.log.append('statement_reviewed', side=side, round=stage, attempt=attempt,
                                    statement=statement, review=review)
                if review.issues:
                    issues += [Issue(severity='error', code='statement_review_' + i.kind,
                        message=f'문제 구절: {i.quote}\n근거 대조: {i.reason}\n수정 방향: {i.instruction}')
                        for i in review.issues]
                    result = result.model_copy(update={'issues': issues, 'passed': False})
            with self.lock:
                self.attempts[side.value].append((len(history), result))
                self.log.append('statement_attempt', side=side, round=stage, attempt=attempt,
                                statement=statement, verification=result)
            if result.passed:
                statement = bind_statement(statement, self.snapshot,
                    debate_id=f'{self.debate_id}:{side.value}', turn_index=len(history) + 1)
                self.emit('statement_accepted', {'side': side, 'round': stage, 'attempts': attempt,
                    'verified': True, 'verification_scope': 'source_values_and_structure', 'statement': statement, 'verification': result, 'engine': 'langgraph'})
                return Analysis(statement, tuple(calls))
            public_issues = [i.model_copy(update={'message': '공개 전 근거 검토에서 수정이 필요합니다.'})
                             if i.code.startswith('statement_review_') else i for i in issues]
            self.emit('statement_rejected', {'side': side, 'round': stage, 'attempt': attempt, 'issues': public_issues})
            conv.messages.append({'role': 'user', 'content': prompts.verifier_feedback(result.feedback())})
        raise LLMError('Graph statement failed verification after retries')

    def mediate(self, state):
        self.emit('moderator_started', {'engine': 'langgraph'})
        transcript = self.transcript(state)
        conv = Conversation(MEDIATOR_SYSTEM,
            [{'role': 'user', 'content': json.dumps({
                'task': '양측의 입론·반박·최종변론 6개를 검토하고 종목에 대한 독립적인 의견을 작성하세요.',
                'output_instructions': MEDIATOR_OUTPUT_INSTRUCTIONS,
                'history': transcript,
                'facts': {key: fact.model_dump(mode='json') for key, fact in self.snapshot.facts.items()},
                'return_context': return_context(self.snapshot),
                'source_context': source_context(self.snapshot),
                'research_results': state.get('research_results', []),
                'remaining_actions': 0,
                'price_as_of': str(self.snapshot.as_of),
                'decision_at': self.snapshot.created_at.isoformat()}, ensure_ascii=False)}])
        for attempt in range(1, 4):
            raw = self.moderator.structured(conv, schema=MEDIATION_SCHEMA, effort=self.moderator_effort,
                tools=TOOL_DEFINITIONS, tool_handler=SnapshotTools(self.snapshot))
            try:
                decision = Mediation.model_validate(raw)
                if decision.action not in ('ACCEPT', 'ABSTAIN'):
                    raise ValueError('Fixed debate permits only ACCEPT or ABSTAIN')
                if decision.tool is not None:
                    raise ValueError('Unexpected tool')
                if (decision.action == 'ACCEPT') != (decision.forecast is not None):
                    raise ValueError('Only ACCEPT requires a forecast')
            except (ValueError, ValidationError):
                self.log.append('moderator_rejected', attempt=attempt, category='schema_or_action',
                                issue_codes=['invalid_mediation'])
                conv.messages.append({'role': 'user', 'content': 'action/tool/forecast 조합과 필수 스키마를 고치세요.'})
                continue
            if decision.forecast is not None:
                candidate = ModeratorDecision(action='verdict', extra_question=None,
                                             **decision.forecast.model_dump())
                issues = moderator_issues(candidate)
                refs = {f'E{i}': key for i, key in enumerate(candidate.decisive_evidence, 1)}
                issues += return_issues(candidate.reasoning, self.snapshot, refs)
                issues += source_issues(candidate.reasoning, self.snapshot, refs)
                issues += concept_issues('\n'.join([candidate.reasoning, candidate.bull.comment, candidate.bear.comment]))
                issues += analysis_issues(candidate, transcript=transcript)
                if any(key not in self.snapshot.facts for key in candidate.decisive_evidence):
                    issues.append(Issue(severity='error', code='unknown_source', message='스냅샷에 없는 판정 근거'))
                records = history_records(transcript)
                reviews = candidate.analysis.statement_reviews
                ids = [r.statement_id for r in reviews]
                if len(ids) != len(set(ids)) or set(ids) != {r['statement_id'] for r in records}:
                    issues.append(Issue(severity='error', code='review_coverage',
                        message='실제 6개 발언 ID를 각각 한 번씩 검토하세요.'))
                if any(key not in self.snapshot.facts for r in reviews for key in r.source_ids):
                    issues.append(Issue(severity='error', code='review_source',
                        message='검토 source_ids는 실제 Fact ID만 사용하세요.'))
                if issues:
                    self.log.append('moderator_rejected', attempt=attempt, category='content_validation',
                                    issues=issues)
                    conv.messages.append({'role': 'user', 'content': prompts.verifier_feedback(
                        '\n'.join(i.message for i in issues), role='moderator')})
                    continue
            with self.lock:
                self.log.append('graph_mediated', decision=decision)
            return decision
        raise MediationFailed('Graph mediation failed validation after retries')

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
            results = self.attempts[side.value]
            firsts = {}
            for index, result in results:
                firsts.setdefault(index, result)
            checked = sum(result.checked for _, result in results)
            stats[side.value] = {'statements': len(state.get(side.value, [])),
                'first_try_pass_rate': round(sum(r.passed for r in firsts.values()) / len(firsts), 2) if firsts else None,
                'rejected_attempts': sum(not r.passed for _, r in results), 'final_unverified_statements': 0,
                'evidence_accuracy': round(sum(r.correct for _, r in results) / checked, 2) if checked else None}
        return {'debate_id': self.debate_id, 'verdict': verdict, 'stats': stats,
                'engine': 'langgraph', 'graph_status': state['status']}

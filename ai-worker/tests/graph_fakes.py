"""Deterministic providers for the real LangGraph runtime, never production fallbacks."""
from types import SimpleNamespace

from bullbear.interpretations import history_records
from bullbear.schemas import Side, Decision
from .prompt_helpers import initial_payload
from .fakes import statement
from .learning_fixtures import with_analysis, moderator_analysis


def model_records(history):
    return [entry if isinstance(entry, dict) else history_records([entry])[0]
            for entry in history]


class GraphLLM:
    def __init__(self, snapshot, *, actions=(), invalid=False, bad_first=False, model='test-model'):
        self.snapshot, self.actions = snapshot, iter(actions)
        self.invalid, self.bad_first = invalid, bad_first
        self.model, self.count = model, 0
        self.client = SimpleNamespace(close=lambda: None)
        self.calls = []

    def usage_payload(self):
        return {'calls': [{'model': self.model, 'input_tokens': self.count * 10, 'output_tokens': self.count * 5}]}

    def structured(self, conv, *, schema, **kwargs):
        self.count += 1
        self.calls.append((conv, schema))
        if 'issues' in schema['properties']:
            result = {'issues': []}
            if 'revised_statement' in schema['properties']:
                result['revised_statement'] = None
            if 'edits' in schema['properties']:
                result['edits'] = []
            return result
        if 'forecast' in schema['properties']:
            action = next(self.actions, 'ACCEPT')
            score = dict(relevance=3, materiality=3, rebuttal=3, risk_awareness=3, comment='자료와 한계를 살폈다.')
            forecast = dict(decision='HOLD', confidence=.5,
                reasoning='7거래일 코스피 대비 비슷한 흐름을 예상하지만 관계의 지속은 불확실하다 [E1].',
                decisive_evidence=['PX.CLOSE'], bull=score, bear=score,
                analysis=moderator_analysis().model_dump(mode='json'))
            records = model_records(initial_payload(conv)['history'])
            forecast['analysis']['statement_reviews'] = [dict(statement_id=r['statement_id'],
                assessment='uncertain', reason='미래 조건은 미확인', source_ids=['PX.CLOSE']) for r in records]
            return dict(action=action, reason='중요한 가정을 재검토하세요.',
                        tool='get_disclosures' if action == 'REQUEST_RESEARCH' else None,
                        forecast=forecast if action == 'ACCEPT' else None)
        candidate = with_analysis(statement(('E1', 'PX.CLOSE', self.snapshot.facts['PX.CLOSE'].value)))
        side = Side.BULL if '매수(상승)' in conv.system else Side.BEAR
        candidate.analysis.outlook = Decision.BUY if side == Side.BULL else Decision.SELL
        direction = '강세' if side == Side.BULL else '약세'
        candidate.claim = f'7거래일 코스피 대비 {direction}를 주장한다'
        candidate.argument = '관측된 가격을 배경으로 비슷한 흐름을 가정하지만 불확실하다 [E1].'
        payload = initial_payload(conv)
        history = payload.get('history', [])
        if payload.get('round') == 'rebuttal':
            from bullbear.schemas import Rebuttal
            side = Side.BULL if '매수(상승)' in conv.system else Side.BEAR
            target = next(r for r in model_records(history) if r['side'] != side.value)
            quote = '7거래일 코스피 대비'
            candidate.argument = f'상대의 “{quote}” 전망은 자료로 확정할 수 없다 [E1].'
            candidate.analysis.rebuttal = Rebuttal(target_statement_id=target['statement_id'],
                target_quote=quote, acknowledged='관측값 인정', reason='지속은 미확인', unresolved=['미래 관계'])
        if payload.get('round') == 'closing':
            from bullbear.schemas import Closing
            candidate.analysis.closing = Closing(retained=['조건부 전망 유지'], conceded=['반대 방향 위험 인정'],
                outlook_reason='배정 입장의 경로를 조건부로 지지', uncertainties=['미래 수급 미확인'],
                change_conditions=['가정이 깨지는 경우'], stance_change='weakened')
        if self.invalid or self.bad_first:
            candidate.evidence[0].value = -1
            self.bad_first = False
        return candidate.model_dump(mode='json')

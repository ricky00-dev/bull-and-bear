"""Small generation schemas expanded into the unchanged public worker models.

Wire rows only encode structure. These adapters never summarize prose, invent
conditions, assign worker IDs, or replace grounding/publication validation.
"""
from copy import deepcopy
import math
import re

from .schemas import Statement


_DECISIONS = ('BUY', 'HOLD', 'SELL')
_SCORE_FIELDS = ('relevance', 'materiality', 'rebuttal', 'risk_awareness')
_CLOSING_FIELDS = ('retained', 'conceded', 'outlook_reason', 'uncertainties',
                   'change_conditions', 'stance_change')
_ANALYSIS_FIELDS = ('common_ground', 'core_issues', 'disagreements', 'unverified',
                    'outlook_basis', 'outlook_limits')
_ASSESSMENTS = ('no_issue_found', 'concern', 'uncertain')
_STANCES = ('maintained', 'weakened', 'revised')

_EVIDENCE_WIRE_RULES = (
    '근거 필드: ref,source_id,value,interpretation,outcome(전망 방향),'
    'assumptions(가정),limits(한계). '
)
WIRE_STATEMENT_RULES = {
    'opening': _EVIDENCE_WIRE_RULES + 'rebuttal=closing=null.',
    'rebuttal': _EVIDENCE_WIRE_RULES +
        'rebuttal=[target_statement_id,exact_quote,acknowledged,reason,*unresolved]; closing=null. '
        '실제 상대 발언을 대상으로 삼고 claim/argument에서 최소 6자를 그대로 인용한다.',
    'closing': _EVIDENCE_WIRE_RULES +
        'rebuttal=null. closing에는 retained,conceded,outlook_reason,'
        'uncertainties,change_conditions,stance_change별로 [kind,*texts] 행을 하나씩 쓴다. '
        'outlook_reason과 stance_change는 값이 하나다. '
        'stance_change=maintained|weakened|revised는 배정된 입장 안에서의 변화를 뜻한다.',
}
WIRE_MEDIATION_RULES = (
    '응답 형식: ACCEPT이면 forecast가 필요하고 ABSTAIN이면 null이다. scores는 정수 8개로, '
    '황소 다음 곰 순서이며 각각 relevance/materiality/rebuttal/risk_awareness 점수(1~5)다. '
    'comments=[황소 평가,곰 평가]. evidence에는 Fact ID를 넣는다. analysis에는 '
    'common_ground,core_issues,disagreements,unverified,outlook_basis,outlook_limits별로 '
    '[kind,*texts] 행을 하나씩 쓴다. keys에는 해석 ID를 넣는다. reviews는 6개 행이며 형식은 '
    '[statement_id,no_issue_found|concern|uncertain,reason,*source_ids]이고 각 행의 근거 ID는 최대 3개다.'
)


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def _array(items, minimum=0, maximum=None):
    result = {'type': 'array', 'items': items, 'minItems': minimum}
    if maximum is not None:
        result['maxItems'] = maximum
    return result


def _strings(minimum=0, maximum=None):
    return _array({'type': 'string'}, minimum, maximum)


def _stage(stage):
    if stage not in ('opening', 'rebuttal', 'closing'):
        raise ValueError(f'Unknown wire statement round: {stage}')


def statement_wire_schema(stage):
    _stage(stage)
    evidence = _object({
        'ref': {'type': 'string', 'pattern': '^E[1-9][0-9]*$'},
        'source_id': {'type': 'string'}, 'value': {'type': ['number', 'null']},
        'interpretation': {'type': 'string'},
        'outcome': {'type': 'string', 'enum': list(_DECISIONS)},
        'assumptions': _strings(1, 3), 'limits': _strings(1, 3),
    })
    return _object({
        'claim': {'type': 'string'}, 'argument': {'type': 'string'},
        'outlook': {'type': 'string', 'enum': list(_DECISIONS)},
        'evidence': _array(evidence, 1, 3),
        'rebuttal': _strings(5, 7) if stage == 'rebuttal' else {'type': 'null'},
        'closing': _array(_strings(2, 4), 6, 6) if stage == 'closing' else {'type': 'null'},
    })


def mediation_wire_schema():
    forecast = _object({
        'decision': {'type': 'string', 'enum': list(_DECISIONS)},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'reasoning': {'type': 'string'}, 'evidence': _strings(1, 3),
        'scores': _array({'type': 'integer', 'enum': [1, 2, 3, 4, 5]}, 8, 8),
        'comments': _strings(2, 2), 'analysis': _array(_strings(1, 4), 6, 6),
        'keys': _strings(0, 6), 'reviews': _array(_strings(3, 6), 6, 6),
    })
    return _object({'action': {'type': 'string', 'enum': ['ACCEPT', 'ABSTAIN']},
                    'reason': {'type': 'string'},
                    'forecast': {'anyOf': [forecast, {'type': 'null'}]}})


def _keys(value, required, name, optional=()):
    if (not isinstance(value, dict) or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise ValueError(f'{name}: invalid object fields')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name}: expected nonempty text')
    return value


def _items(value, minimum, maximum, name):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f'{name}: expected {minimum}..{maximum} items')
    return value


def _texts(value, minimum, maximum, name, *, unique=False):
    values = [_text(item, name) for item in _items(value, minimum, maximum, name)]
    if unique and len(set(values)) != len(values):
        raise ValueError(f'{name}: duplicate values')
    return values


def _enum(value, choices, name):
    _text(value, name)
    if value not in choices:
        raise ValueError(f'{name}: unknown value')
    return value


def _number(value, name, *, nullable=False):
    if value is None and nullable:
        return value
    if type(value) not in (int, float):
        raise ValueError(f'{name}: expected finite number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{name}: expected finite number')
    return value


def _rows(value, kinds, name, *, empty=(), scalar=()):
    result = {}
    for row in _items(value, len(kinds), len(kinds), name):
        row = _texts(row, 1, 4, name)
        kind = _enum(row[0], kinds, name)
        if kind in result:
            raise ValueError(f'{name}: duplicate row kind {kind}')
        count = 1 if kind in scalar else 3
        texts = _texts(row[1:], 0 if kind in empty else 1, count, kind)
        result[kind] = texts[0] if kind in scalar else texts
    if set(result) != set(kinds):
        raise ValueError(f'{name}: missing row kind')
    return result


def _canonical_statement(raw, stage):
    _keys(raw, ('claim', 'argument', 'evidence', 'analysis'), 'statement', ('statement_id',))
    if raw.get('statement_id') is not None:
        raise ValueError('statement_id is worker-generated')
    _text(raw['claim'], 'claim')
    _text(raw['argument'], 'argument')
    refs, sources = [], []
    for evidence in _items(raw['evidence'], 1, 3, 'evidence'):
        _keys(evidence, ('ref', 'source_id', 'value', 'interpretation'), 'evidence',
              ('interpretation_id', 'observation'))
        if evidence.get('interpretation_id') is not None or evidence.get('observation') is not None:
            raise ValueError('evidence identifiers/observations are worker-generated')
        ref = _text(evidence['ref'], 'ref')
        if not re.fullmatch(r'E[1-9][0-9]*', ref):
            raise ValueError('invalid evidence ref')
        refs.append(ref)
        sources.append(_text(evidence['source_id'], 'source_id'))
        _number(evidence['value'], 'value', nullable=True)
        _text(evidence['interpretation'], 'interpretation')
    if len(set(refs)) != len(refs) or len(set(sources)) != len(sources):
        raise ValueError('evidence refs and sources must be unique')
    analysis = raw['analysis']
    _keys(analysis, ('outlook', 'interpretations', 'rebuttal', 'closing'), 'analysis')
    _enum(analysis['outlook'], _DECISIONS, 'outlook')
    context_refs = []
    for context in _items(analysis['interpretations'], 1, 3, 'interpretations'):
        _keys(context, ('evidence_ref', 'expected_outcome', 'assumptions', 'limitations'), 'interpretation context')
        context_refs.append(_text(context['evidence_ref'], 'evidence_ref'))
        _enum(context['expected_outcome'], _DECISIONS, 'expected_outcome')
        for field in ('assumptions', 'limitations'):
            _texts(context[field], 1, 3, field)
    if len(set(context_refs)) != len(context_refs) or set(context_refs) != set(refs):
        raise ValueError('each evidence ref requires exactly one interpretation context')
    for field in ('rebuttal', 'closing'):
        if (analysis[field] is not None) != (stage == field):
            raise ValueError(f'{field}: invalid round field')
    if stage == 'rebuttal':
        rebuttal = analysis['rebuttal']
        _keys(rebuttal, ('target_statement_id', 'target_quote', 'acknowledged', 'reason', 'unresolved'), 'rebuttal')
        for field in ('target_statement_id', 'target_quote', 'acknowledged', 'reason'):
            _text(rebuttal[field], field)
        _texts(rebuttal['unresolved'], 1, 3, 'unresolved')
    if stage == 'closing':
        closing = analysis['closing']
        _keys(closing, _CLOSING_FIELDS, 'closing')
        for field in ('retained', 'conceded', 'uncertainties', 'change_conditions'):
            _texts(closing[field], 1, 3, field)
        _text(closing['outlook_reason'], 'outlook_reason')
        _enum(closing['stance_change'], _STANCES, 'stance_change')
    statement = Statement.model_validate(raw)
    return statement.model_dump(mode='json', exclude={
        'statement_id': True, 'evidence': {'__all__': {'interpretation_id', 'observation'}}})


def expand_statement_response(raw, stage):
    """Accept wire or validated legacy generation output, without mutating it."""
    _stage(stage)
    if isinstance(raw, dict) and 'analysis' in raw:
        # Recorded responses and test clients still produce the canonical model.
        # Keep its original validation path: runtime checks role, quote ownership,
        # reference coverage and round semantics after this structural validation.
        return Statement.model_validate(deepcopy(raw)).model_dump(mode='json')
    _keys(raw, ('claim', 'argument', 'outlook', 'evidence', 'rebuttal', 'closing'), 'statement wire')
    evidence, contexts = [], []
    for item in _items(raw['evidence'], 1, 3, 'evidence'):
        _keys(item, ('ref', 'source_id', 'value', 'interpretation', 'outcome', 'assumptions', 'limits'), 'evidence wire')
        evidence.append({key: deepcopy(item[key]) for key in ('ref', 'source_id', 'value', 'interpretation')})
        contexts.append({'evidence_ref': item['ref'], 'expected_outcome': item['outcome'],
                         'assumptions': deepcopy(item['assumptions']), 'limitations': deepcopy(item['limits'])})
    rebuttal = None
    if stage == 'rebuttal':
        row = _texts(raw['rebuttal'], 5, 7, 'rebuttal')
        rebuttal = dict(zip(('target_statement_id', 'target_quote', 'acknowledged', 'reason'), row[:4]))
        rebuttal['unresolved'] = row[4:]
    elif raw['rebuttal'] is not None:
        raise ValueError('rebuttal must be null outside rebuttal round')
    closing = None
    if stage == 'closing':
        closing = _rows(raw['closing'], _CLOSING_FIELDS, 'closing', scalar=('outlook_reason', 'stance_change'))
    elif raw['closing'] is not None:
        raise ValueError('closing must be null outside closing round')
    result = {'claim': raw['claim'], 'argument': raw['argument'], 'evidence': evidence,
              'analysis': {'outlook': raw['outlook'], 'interpretations': contexts,
                           'rebuttal': rebuttal, 'closing': closing}}
    return _canonical_statement(result, stage)


def _canonical_mediation(raw):
    from .graph import Mediation

    _keys(raw, ('action', 'reason', 'forecast'), 'mediation', ('tool',))
    _enum(raw['action'], ('ACCEPT', 'ABSTAIN'), 'action')
    _text(raw['reason'], 'reason')
    if raw.get('tool') is not None or ((raw['action'] == 'ACCEPT') != (raw['forecast'] is not None)):
        raise ValueError('invalid action/tool/forecast combination')
    if raw['forecast'] is not None:
        forecast = raw['forecast']
        _keys(forecast, ('decision', 'confidence', 'reasoning', 'decisive_evidence', 'bull', 'bear', 'analysis'), 'forecast')
        _enum(forecast['decision'], _DECISIONS, 'decision')
        _number(forecast['confidence'], 'confidence')
        _text(forecast['reasoning'], 'reasoning')
        _texts(forecast['decisive_evidence'], 1, 3, 'decisive_evidence', unique=True)
        for side in ('bull', 'bear'):
            score = forecast[side]
            _keys(score, (*_SCORE_FIELDS, 'comment'), side)
            for field in _SCORE_FIELDS:
                if type(score[field]) is not int or not 1 <= score[field] <= 5:
                    raise ValueError('scores must be integers from 1 to 5')
            _text(score['comment'], 'comment')
        analysis = forecast['analysis']
        _keys(analysis, (*_ANALYSIS_FIELDS, 'key_interpretation_ids', 'statement_reviews'), 'moderator analysis')
        for field in _ANALYSIS_FIELDS:
            _texts(analysis[field], 0 if field in ('common_ground', 'disagreements') else 1, 3, field)
        _texts(analysis['key_interpretation_ids'], 0, 6, 'key_interpretation_ids', unique=True)
        ids = []
        for review in _items(analysis['statement_reviews'], 6, 6, 'statement_reviews'):
            _keys(review, ('statement_id', 'assessment', 'reason', 'source_ids'), 'statement review')
            ids.append(_text(review['statement_id'], 'statement_id'))
            _enum(review['assessment'], _ASSESSMENTS, 'assessment')
            _text(review['reason'], 'review reason')
            _texts(review['source_ids'], 0, 3, 'review source_ids', unique=True)
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate statement review')
    value = deepcopy(raw)
    value['tool'] = None
    return Mediation.model_validate(value).model_dump(mode='json')


def expand_mediation_response(raw):
    """Restore positional scores and tagged analysis rows before validation."""
    _keys(raw, ('action', 'reason', 'forecast'), 'mediation wire', ('tool',))
    forecast = raw['forecast']
    if isinstance(forecast, dict) and 'decisive_evidence' in forecast:
        from .graph import Mediation
        return Mediation.model_validate(deepcopy(raw)).model_dump(mode='json')
    if forecast is None:
        return _canonical_mediation(deepcopy(raw))
    if 'tool' in raw:
        raise ValueError('tool is not a wire field')
    _keys(forecast, ('decision', 'confidence', 'reasoning', 'evidence', 'scores',
                     'comments', 'analysis', 'keys', 'reviews'), 'forecast wire')
    scores = _items(forecast['scores'], 8, 8, 'scores')
    comments = _texts(forecast['comments'], 2, 2, 'comments')
    analysis = _rows(forecast['analysis'], _ANALYSIS_FIELDS, 'analysis', empty=('common_ground', 'disagreements'))
    analysis['key_interpretation_ids'] = deepcopy(forecast['keys'])
    reviews = []
    for row in _items(forecast['reviews'], 6, 6, 'reviews'):
        row = _texts(row, 3, 6, 'review row')
        reviews.append({'statement_id': row[0], 'assessment': row[1], 'reason': row[2], 'source_ids': row[3:]})
    analysis['statement_reviews'] = reviews
    canonical = {'decision': forecast['decision'], 'confidence': forecast['confidence'],
                 'reasoning': forecast['reasoning'], 'decisive_evidence': deepcopy(forecast['evidence']),
                 'analysis': analysis}
    for index, side in enumerate(('bull', 'bear')):
        canonical[side] = dict(zip(_SCORE_FIELDS, scores[index * 4:index * 4 + 4]))
        canonical[side]['comment'] = comments[index]
    return _canonical_mediation({'action': raw['action'], 'reason': raw['reason'],
                                 'tool': None, 'forecast': canonical})

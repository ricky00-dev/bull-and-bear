"""Wire adapters preserve authored meaning and reject malformed positional data."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from bullbear.graph import Mediation
from bullbear.llm import anthropic_schema
from bullbear.model_wire import (WIRE_MEDIATION_RULES, WIRE_STATEMENT_RULES,
                                expand_mediation_response, expand_statement_response,
                                mediation_wire_schema, statement_wire_schema)
from bullbear.schemas import Statement


def statement_wire(stage='opening'):
    return {
        'claim': '이익이 유지되면 개선될 수 있어요. 수급은 아직 확인되지 않았어요.',
        'argument': '상대의 “이익이 이어져야 해요”라는 조건은 인정하지만 전망은 불확실해요 [E1].',
        'outlook': 'BUY',
        'evidence': [{'ref': 'E1', 'source_id': 'FIN.OPERATING_INCOME', 'value': 1230000000000,
                      'interpretation': '지난 실적이며 미래의 지속을 보장하지 않아요.',
                      'outcome': 'HOLD', 'assumptions': ['이익이 이어져야 해요.'],
                      'limits': ['최신 분기는 미확인입니다.', '수급은 별도 조건이에요.']}],
        'rebuttal': ['d:bear:t1', '이익이 이어져야 해요', '관측은 인정해요.',
                     '지속성은 미확인이에요.', '미래 수급', '시장 기대'] if stage == 'rebuttal' else None,
        'closing': [
            ['retained', '조건부 입장을 유지해요.'], ['conceded', '하락 경로도 남아 있어요.'],
            ['outlook_reason', '현재 자료를 조건부로 해석해요.'],
            ['uncertainties', '수급', '최신 분기'], ['change_conditions', '가정이 깨지면 수정해요.'],
            ['stance_change', 'weakened'],
        ] if stage == 'closing' else None,
    }


def mediation_wire():
    return {'action': 'ACCEPT', 'reason': '양측 자료를 대조했어요.', 'forecast': {
        'decision': 'SELL', 'confidence': 0.55,
        'reasoning': '관측은 맞지만 미래 지속은 확인되지 않았어요 [E1].',
        'evidence': ['FIN.OPERATING_INCOME'], 'scores': [1, 2, 3, 4, 5, 4, 3, 2],
        'comments': ['조건부 논증을 유지했어요.', '반대 경로를 설명했어요.'],
        'analysis': [['common_ground'], ['core_issues', '실적의 지속성'], ['disagreements'],
                     ['unverified', '최신 수급'], ['outlook_basis', '서로 반대인 조건부 경로'],
                     ['outlook_limits', '자료의 시차']],
        'keys': ['d:bull:t1:E1'],
        'reviews': [[f'd:{side}:t{index}', 'uncertain', '미래 조건은 미확인', 'FIN.OPERATING_INCOME']
                    for index in range(1, 4) for side in ('bull', 'bear')],
    }}


@pytest.mark.parametrize('stage', ['opening', 'rebuttal', 'closing'])
def test_statement_wire_preserves_prose_citations_conditions_and_round_relations(stage):
    raw = statement_wire(stage)
    original = deepcopy(raw)
    expanded = expand_statement_response(raw, stage)
    value = Statement.model_validate(expanded)
    assert value.claim == raw['claim'] and value.argument == raw['argument']
    assert value.evidence[0].source_id == 'FIN.OPERATING_INCOME'
    assert value.evidence[0].value == 1230000000000
    assert value.evidence[0].interpretation == raw['evidence'][0]['interpretation']
    assert value.statement_id is None and value.evidence[0].interpretation_id is None
    assert value.evidence[0].observation is None
    context, = value.analysis.interpretations
    assert context.evidence_ref == 'E1' and context.expected_outcome == 'HOLD'
    assert context.assumptions == raw['evidence'][0]['assumptions']
    assert context.limitations == raw['evidence'][0]['limits']
    if stage == 'rebuttal':
        assert value.analysis.rebuttal.target_statement_id == raw['rebuttal'][0]
        assert value.analysis.rebuttal.target_quote == raw['rebuttal'][1]
        assert value.analysis.rebuttal.unresolved == raw['rebuttal'][4:]
    if stage == 'closing':
        assert value.analysis.closing.uncertainties == ['수급', '최신 분기']
        assert value.analysis.closing.stance_change == 'weakened'
    assert raw == original
    assert Statement.model_validate(expand_statement_response(value.model_dump(mode='json'), stage)) == value


@pytest.mark.parametrize('field,value', [
    ('value', True), ('value', '1.2'), ('value', float('inf')), ('value', 10 ** 400),
    ('outcome', 'UP'), ('limits', []), ('assumptions', ['']), ('ref', 'x'),
])
def test_statement_wire_rejects_untyped_values_and_missing_conditions(field, value):
    raw = statement_wire()
    raw['evidence'][0][field] = value
    with pytest.raises(ValueError):
        expand_statement_response(raw, 'opening')


def test_statement_wire_rejects_duplicate_refs_sources_extra_keys_and_wrong_rounds():
    raw = statement_wire()
    raw['evidence'].append(deepcopy(raw['evidence'][0]))
    with pytest.raises(ValueError):
        expand_statement_response(raw, 'opening')
    raw['evidence'][1]['ref'] = 'E2'
    with pytest.raises(ValueError):
        expand_statement_response(raw, 'opening')
    raw = statement_wire()
    raw['extra'] = 'not allowed'
    with pytest.raises(ValueError):
        expand_statement_response(raw, 'opening')
    with pytest.raises(ValueError):
        expand_statement_response(statement_wire('rebuttal'), 'closing')
    with pytest.raises(ValueError):
        expand_statement_response(statement_wire(), 'rebuttal')
    # The shared schema allows both fields, so the adapter alone enforces the round.
    for filled in ('rebuttal', 'closing'):
        with pytest.raises(ValueError, match=f'{filled} must be null'):
            expand_statement_response(statement_wire(filled), 'opening')


@pytest.mark.parametrize('row', [
    ['retained', 'another retained'], ['unknown', 'text'],
    ['stance_change', 'BUY'], ['stance_change', 'maintained', 'extra'],
])
def test_closing_rows_reject_duplicate_unknown_and_bad_scalar_values(row):
    raw = statement_wire('closing')
    raw['closing'][-1] = row
    with pytest.raises(ValueError):
        expand_statement_response(raw, 'closing')


def test_mediation_wire_restores_score_order_reviews_and_empty_optional_analysis():
    raw = mediation_wire()
    original = deepcopy(raw)
    expanded = expand_mediation_response(raw)
    mediation = Mediation.model_validate(expanded)
    assert mediation.tool is None
    assert mediation.forecast.bull.model_dump() == {
        'relevance': 1, 'materiality': 2, 'rebuttal': 3, 'risk_awareness': 4,
        'comment': raw['forecast']['comments'][0]}
    assert mediation.forecast.bear.relevance == 5 and mediation.forecast.bear.risk_awareness == 2
    assert mediation.forecast.analysis.common_ground == []
    assert mediation.forecast.analysis.disagreements == []
    assert mediation.forecast.analysis.key_interpretation_ids == ['d:bull:t1:E1']
    assert mediation.forecast.analysis.statement_reviews[5].statement_id == 'd:bear:t3'
    assert mediation.forecast.analysis.statement_reviews[5].reason == raw['forecast']['reviews'][5][2]
    assert raw == original
    assert expand_mediation_response(mediation.model_dump(mode='json')) == expanded


@pytest.mark.parametrize('field,value', [
    ('scores', [1] * 7), ('scores', [1] * 9), ('scores', [True] * 8),
    ('scores', [2.0] * 8), ('scores', [6] * 8), ('comments', ['only one']),
    ('confidence', True), ('confidence', float('nan')), ('confidence', 1.1),
    ('keys', ['same', 'same']), ('evidence', ['same', 'same']),
])
def test_mediation_wire_rejects_wrong_dimensions_types_and_duplicate_ids(field, value):
    raw = mediation_wire()
    raw['forecast'][field] = value
    with pytest.raises(ValueError):
        expand_mediation_response(raw)


@pytest.mark.parametrize('change', ['duplicate_kind', 'unknown_kind', 'empty_required',
                                  'duplicate_review', 'missing_review', 'wrong_assessment',
                                  'extra_review_source', 'empty_reason'])
def test_mediation_wire_rejects_malformed_analysis_and_review_rows(change):
    raw = mediation_wire()
    forecast = raw['forecast']
    if change == 'duplicate_kind':
        forecast['analysis'][-1] = ['core_issues', 'duplicate']
    elif change == 'unknown_kind':
        forecast['analysis'][-1] = ['invented', 'unknown']
    elif change == 'empty_required':
        forecast['analysis'][-1] = ['outlook_limits']
    elif change == 'duplicate_review':
        forecast['reviews'][-1][0] = forecast['reviews'][0][0]
    elif change == 'missing_review':
        forecast['reviews'].pop()
    elif change == 'wrong_assessment':
        forecast['reviews'][0][1] = 'verified_true'
    elif change == 'extra_review_source':
        forecast['reviews'][0].extend(['A', 'B', 'C'])
    else:
        forecast['reviews'][0][2] = ' '
    with pytest.raises(ValueError):
        expand_mediation_response(raw)


def test_abstain_and_canonical_compatibility_still_validate_structure():
    abstain = {'action': 'ABSTAIN', 'reason': '자료가 부족해요.', 'forecast': None}
    assert expand_mediation_response(abstain) == {**abstain, 'tool': None}
    with pytest.raises(ValueError):
        expand_mediation_response({**abstain, 'action': 'ACCEPT'})
    canonical = expand_mediation_response(mediation_wire())
    canonical['forecast']['bull']['relevance'] = 6
    with pytest.raises(ValidationError):
        expand_mediation_response(canonical)
    st = expand_statement_response(statement_wire(), 'opening')
    st['analysis']['outlook'] = 'UNKNOWN'
    with pytest.raises(ValidationError):
        expand_statement_response(st, 'opening')


def test_anthropic_schema_relaxation_does_not_weaken_adapter_row_validation():
    schema = anthropic_schema(mediation_wire_schema())
    scores = schema['properties']['forecast']['properties']['scores']
    assert scores['minItems'] == 1 and 'maxItems' not in scores
    assert 'Constraints:' in scores['description']
    bad = mediation_wire()
    bad['forecast']['scores'] = [3]
    with pytest.raises(ValueError):
        expand_mediation_response(bad)


def test_generation_schemas_are_strict_and_round_independent():
    def inspect(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['properties']) == set(node['required'])
            for child in node.values():
                inspect(child)
        elif isinstance(node, list):
            for child in node:
                inspect(child)
    schema = statement_wire_schema()
    inspect(anthropic_schema(schema))
    # One schema for every round keeps the prompt cache; the adapter enforces the
    # round (see test_statement_wire_rejects_duplicate_refs_sources_extra_keys_and_wrong_rounds).
    for field in ('rebuttal', 'closing'):
        assert [option['type'] for option in schema['properties'][field]['anyOf']] == ['array', 'null']
    for stage in ('opening', 'rebuttal', 'closing'):
        assert isinstance(WIRE_STATEMENT_RULES[stage], str)
    inspect(anthropic_schema(mediation_wire_schema()))
    assert 'scores' in WIRE_MEDIATION_RULES

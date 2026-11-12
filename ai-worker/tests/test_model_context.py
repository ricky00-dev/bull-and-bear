"""Model context stays small without changing the source history or identities."""
from copy import deepcopy
import json

import pytest

from bullbear.model_context import full_model_history, model_history
from bullbear.prompts import debater_system, statement_output_instructions
from bullbear.schemas import Side, compact_schema


def turn(side, stage='opening', index=1, target=None):
    sid = f'd:{side}:t{index}'
    analysis = {'outlook': 'BUY' if side == 'bull' else 'SELL',
                'interpretations': [{'evidence_ref': 'E1', 'expected_outcome': 'HOLD',
                                     'assumptions': ['아직 확인되지 않은 미래 조건'],
                                     'limitations': ['조건이 깨지면 전망을 유지할 수 없다']}],
                'rebuttal': None, 'closing': None}
    if target:
        analysis['rebuttal'] = {'target_statement_id': target,
                               'target_quote': '조건부로 전망합니다',
                               'acknowledged': '관측 인정', 'reason': '미래 조건은 미확인',
                               'unresolved': ['반대 경로도 가능하다']}
    if stage == 'closing':
        analysis['closing'] = {'retained': ['조건부 전망'], 'conceded': ['다른 경로'],
                               'outlook_reason': '자료 범위의 판단', 'uncertainties': ['미확인 수급'],
                               'change_conditions': ['전망의 조건이 깨지는 경우'], 'stance_change': 'weakened'}
    return dict(statement_id=sid, side=side, round=stage,
                claim=f'{side}는 조건부로 전망합니다.', argument=f'{side}의 별도 본문 [E1].',
                evidence=[dict(ref='E1', source_id='PX.CLOSE', value=100,
                               interpretation='근거에만 있는 별개의 설명',
                               interpretation_id=sid + ':E1', observation={'value': 100})],
                analysis=analysis)


def encoded(*records):
    return [json.dumps(record, ensure_ascii=False) for record in records]


def test_full_history_preserves_exact_prose_conditions_and_ids_without_copying_facts():
    records = [turn(side, stage, index, f'd:{"bear" if side == "bull" else "bull"}:t1'
                    if stage == 'rebuttal' else None)
               for index, stage in enumerate(('opening', 'rebuttal', 'closing'), 1)
               for side in ('bull', 'bear')]
    transcript = encoded(*records)
    original = deepcopy(transcript)
    view = full_model_history(transcript)
    assert len(view) == 6
    assert all(isinstance(record, dict) for record in view)
    for source, compact in zip(records, view, strict=True):
        for key in ('statement_id', 'side', 'round', 'claim', 'argument'):
            assert compact[key] == source[key]
        evidence = compact['evidence'][0]
        assert 'value' not in evidence and 'observation' not in evidence
        for key in ('ref', 'source_id', 'interpretation', 'interpretation_id'):
            assert evidence[key] == source['evidence'][0][key]
        context = source['analysis']['interpretations'][0]
        for key in ('expected_outcome', 'assumptions', 'limitations'):
            assert evidence[key] == context[key]
        for key in ('outlook', 'rebuttal', 'closing'):
            if source['analysis'][key] is not None:
                assert compact[key] == source['analysis'][key]
    view[0]['evidence'][0]['assumptions'].append('edited view')
    assert transcript == original
    assert len(json.dumps(view, ensure_ascii=False)) < len(json.dumps(transcript, ensure_ascii=False))


@pytest.mark.parametrize('role', ['moderator', 'debater'])
def test_initial_history_keeps_public_conditions_and_moves_private_analysis_to_detail(role):
    source = turn('bear', 'rebuttal', 2, 'd:bull:t1')
    source['claim'] = '반등이 가능하지만 실적이 유지되어야 해요.'
    source['argument'] = '수급은 미확인이므로 확신할 수 없어요 [E1].'
    transcript = encoded(source)
    lean, = model_history(transcript, role=role, side='bull', round_kind='closing')
    detailed, = full_model_history(transcript)
    assert lean['claim'] == source['claim']
    assert lean['argument'] == source['argument']
    assert lean['statement_id'] == source['statement_id']
    assert lean['rebuttal'] == {'target_statement_id': 'd:bull:t1', 'target_quote': '조건부로 전망합니다'}
    expected = {'ref': 'E1', 'source_id': 'PX.CLOSE'}
    if role == 'moderator':
        expected['interpretation_id'] = source['evidence'][0]['interpretation_id']
    assert lean['evidence'] == [expected]
    assert 'analysis' not in lean and 'outlook' not in lean
    assert detailed['evidence'][0]['assumptions'] == ['아직 확인되지 않은 미래 조건']
    assert detailed['evidence'][0]['interpretation'] == '근거에만 있는 별개의 설명'
    assert detailed['rebuttal']['unresolved'] == ['반대 경로도 가능하다']
    assert json.loads(transcript[0]) == source


def test_opening_has_no_history_and_unknown_role_is_rejected():
    assert model_history(encoded(turn('bull')), role='debater', round_kind='opening') == []
    for role in ('unknown', 'reviewer'):
        with pytest.raises(ValueError):
            model_history([], role=role)


def test_compact_schema_preserves_field_names_and_constraints():
    schema = {'title': 'Root', 'type': 'object', 'properties': {
        'title': {'title': 'Title field', 'type': 'string', 'minLength': 2},
        'default': {'type': 'integer', 'default': 1, 'minimum': 0}},
        '$defs': {'Unused': {'type': 'string'}}, 'required': ['title', 'default']}
    compact = compact_schema(schema)
    assert compact == {'type': 'object', 'properties': {
        'title': {'type': 'string', 'minLength': 2}, 'default': {'type': 'integer', 'minimum': 0}},
        'required': ['title', 'default']}


@pytest.mark.parametrize('stage', ['opening', 'rebuttal', 'closing'])
def test_round_instructions_keep_citation_and_condition_requirements(stage):
    text = statement_output_instructions(stage)
    assert all(term in text for term in ('두 문장 요약', '최대 3문장', 'source_id', 'value',
                                         '가정', '한계', 'STALE', 'get_statement_details'))
    system = debater_system(Side.BULL)
    assert '뉴스는 제목만으로 내용을 말하지 않는다' in system
    assert '기사 요약에 따르면' in system
    assert 'metadata.groups' in system and 'facts_csv는 fact_metadata' in system
    if stage == 'rebuttal':
        assert '실제 상대 statement_id' in text and '복사한 원문' in text
        assert 'stance_change' not in text
    elif stage == 'opening':
        assert 'rebuttal/closing은 null' in text and 'stance_change' not in text
    else:
        assert 'stance_change' in text and '변경 조건' in text

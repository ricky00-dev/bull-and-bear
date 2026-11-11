from copy import deepcopy
import csv
from io import StringIO
import json

import pytest

from bullbear.llm import LLMError
from bullbear import prompts
from bullbear.schemas import Decision, Rebuttal, Side
from bullbear.statement_review import review_statement
from .test_statement_review import ReviewSequence, review_candidate, revised_review
from .test_graph_runtime import snapshot


@pytest.mark.parametrize('edit', [
    {'path': 'evidence.0.source_id', 'value': 'PX.OTHER'},
    {'path': 'evidence.0.ref', 'value': 'E2'},
    {'path': 'evidence.0.value', 'value': '100'},
    {'path': 'statement_id', 'value': 'forged'},
    {'path': 'analysis.outlook', 'value': 'SELL'},
    {'path': 'analysis.interpretations.0.expected_outcome', 'value': 'UNKNOWN'},
    {'path': 'analysis.interpretations.0.assumptions.-1', 'value': 'edited'},
    {'path': 'analysis.interpretations.00.assumptions.0', 'value': 'edited'},
    {'path': 'analysis.interpretations.0.assumptions.1', 'value': 'new item'},
    {'path': '__class__', 'value': 'edited'},
    {'path': 'argument', 'value': '  '},
    {'path': 'argument', 'value': 123},
    {'path': 'argument', 'value': None},
    {'path': 'argument', 'value': ['text']},
    {'path': 'argument', 'value': 'text', 'operation': 'delete'},
])
def test_review_rejects_structure_identity_and_type_changes(snapshot, edit):
    candidate = review_candidate(snapshot)
    before = candidate.model_dump()
    response = revised_review(candidate)
    response['edits'] = [edit]
    reviewer = ReviewSequence([response, response])
    with pytest.raises(LLMError):
        review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert candidate.model_dump() == before
    assert len(reviewer.messages) == 2


def test_review_rejects_duplicate_edit_paths(snapshot):
    candidate = review_candidate(snapshot)
    response = revised_review(candidate)
    response['edits'].append({'path': 'argument', 'value': '덮어쓴 다른 설명이에요.'})
    with pytest.raises(LLMError, match='unique field'):
        review_statement(ReviewSequence([response, response]), candidate, snapshot, [], effort='high')


def test_review_applies_nested_text_edit_without_changing_other_content(snapshot):
    candidate = review_candidate(snapshot)
    before = candidate.model_dump(mode='json')
    response = revised_review(candidate)
    response['edits'] = [{'path': 'analysis.interpretations.0.limitations.0',
                          'value': '이 관측값만으로 미래 상승을 확정할 수 없어요.'}]
    result = review_statement(ReviewSequence([response]), candidate, snapshot, [], effort='high')
    expected = deepcopy(before)
    expected['analysis']['interpretations'][0]['limitations'][0] = response['edits'][0]['value']
    assert result.revised_statement.model_dump(mode='json') == expected
    assert candidate.model_dump(mode='json') == before


def test_review_can_expand_conditions_and_correct_a_provided_citation(snapshot):
    candidate = review_candidate(snapshot)
    new_fact = snapshot.facts['PX.CLOSE'].model_copy(update={'id': 'PX.BASE', 'value': 42.0})
    snapshot.facts['PX.BASE'] = new_fact
    snapshot.facts['PX.CLOSE'] = snapshot.facts['PX.CLOSE'].model_copy(update={'inputs': ['PX.BASE']})
    response = revised_review(candidate)
    response['edits'] = [
        {'path': 'evidence.0.source_id', 'value': 'PX.BASE'},
        {'path': 'evidence.0.value', 'value': 42.0},
        {'path': 'analysis.interpretations.0.expected_outcome', 'value': 'SELL'},
        {'path': 'analysis.interpretations.0.limitations', 'value': ['전망은 미확인', '추가 자료가 필요']},
    ]
    result = review_statement(ReviewSequence([response]), candidate, snapshot, [], effort='high')
    revised = result.revised_statement
    assert revised.evidence[0].source_id == 'PX.BASE' and revised.evidence[0].value == 42
    assert revised.evidence[0].ref == candidate.evidence[0].ref
    assert revised.analysis.outlook == candidate.analysis.outlook
    assert revised.analysis.interpretations[0].expected_outcome == 'SELL'
    assert revised.analysis.interpretations[0].limitations == ['전망은 미확인', '추가 자료가 필요']


@pytest.mark.parametrize('edits', [
    [{'path': 'evidence.0.value', 'value': float('nan')}],
    [{'path': 'analysis.interpretations.0.limitations', 'value': []}],
    [{'path': 'analysis.interpretations.0.limitations', 'value': ['a', 'b', 'c', 'd']}],
    [{'path': 'analysis.interpretations.0.limitations', 'value': ['a', '']}],
    [{'path': 'analysis.interpretations.0.limitations', 'value': ['a', 'b']},
     {'path': 'analysis.interpretations.0.limitations.0', 'value': 'c'}],
])
def test_review_rejects_nonfinite_numbers_and_invalid_array_changes(snapshot, edits):
    candidate = review_candidate(snapshot)
    response = revised_review(candidate)
    response['edits'] = edits
    with pytest.raises(LLMError):
        review_statement(ReviewSequence([response, response]), candidate, snapshot, [], effort='high')


@pytest.mark.parametrize('value', [-1.0, None])
def test_reviewer_value_edit_is_not_rejected_by_snapshot_numeric_comparison(snapshot, value):
    candidate = review_candidate(snapshot)
    response = revised_review(candidate)
    response['edits'] = [{'path': 'evidence.0.value', 'value': value}]
    reviewer = ReviewSequence([response])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert result.revised_statement.evidence[0].value == value
    assert len(reviewer.messages) == 1


def test_review_text_patch_preserves_original_numbers_without_secondary_verification(snapshot):
    candidate = review_candidate(snapshot)
    candidate.evidence[0].value = -1.0
    response = revised_review(candidate)
    result = review_statement(ReviewSequence([response]), candidate, snapshot, [], effort='high')
    assert result.revised_statement.argument == response['edits'][0]['value']
    assert result.revised_statement.evidence[0].value == -1.0


def test_review_text_patch_preserves_original_unknown_source(snapshot):
    candidate = review_candidate(snapshot)
    candidate.evidence[0].source_id = 'UNKNOWN.ORIGINAL'
    response = revised_review(candidate, sources=())
    reviewer = ReviewSequence([response])
    result = review_statement(reviewer, candidate, snapshot, [], effort='high')
    assert result.revised_statement.argument == response['edits'][0]['value']
    assert result.revised_statement.evidence[0].source_id == 'UNKNOWN.ORIGINAL'
    assert len(reviewer.messages) == 1


def test_review_keeps_original_outlook_without_rechecking_assigned_role(snapshot):
    candidate = review_candidate(snapshot)
    candidate.analysis.outlook = Decision.SELL
    response = revised_review(candidate)
    result = review_statement(ReviewSequence([response]), candidate, snapshot, [],
                              effort='high', side=Side.BULL)
    assert result.revised_statement.analysis.outlook == Decision.SELL


def test_review_cannot_ground_a_concern_in_an_identifier(snapshot):
    candidate = review_candidate(snapshot)
    response = revised_review(candidate, quote='PX.CLOSE')
    with pytest.raises(LLMError, match='fabricated target'):
        review_statement(ReviewSequence([response, response]), candidate, snapshot, [], effort='high')


def test_review_includes_recursive_fact_dependencies_and_missing_dependency_notice(snapshot):
    candidate = review_candidate(snapshot)
    snapshot.facts['PX.CLOSE'] = snapshot.facts['PX.CLOSE'].model_copy(update={'inputs': ['PX.BASE']})
    snapshot.facts['PX.BASE'] = snapshot.facts['PX.CLOSE'].model_copy(
        update={'id': 'PX.BASE', 'inputs': ['PX.MISSING']})
    reviewer = ReviewSequence([{'issues': [], 'edits': []}])
    review_statement(reviewer, candidate, snapshot, [], effort='high')
    fixed = json.loads(reviewer.messages[0][0]['content'][0]['text'])
    from bullbear.context_ids import RequestIds
    fixed = RequestIds(snapshot, []).decode_response(fixed)
    dynamic = RequestIds(snapshot, []).decode_response(json.loads(reviewer.messages[0][1]['content']))
    rows = list(csv.DictReader(StringIO(dynamic['facts_csv'])))
    rows += [row for row in csv.DictReader(StringIO(fixed['shared_push']['facts_csv'])) if row['source_id'] == 'PX.CLOSE']
    assert {row['source_id'] for row in rows} == {'PX.CLOSE', 'PX.BASE'}
    assert dynamic['missing_fact_ids'] == ['PX.MISSING']


def test_opening_review_has_no_history_tool(snapshot):
    class OpeningReviewer:
        def structured(self, conv, **kwargs):
            assert {tool['name'] for tool in kwargs['tools']} == {'read_snapshot', 'get_new_url'}
            assert '제공된 도구만 호출한다' in conv.messages[1]['content']
            return {'issues': [], 'edits': []}

    result = review_statement(OpeningReviewer(), review_candidate(snapshot), snapshot, [],
                              effort='high', side=Side.BULL, round_kind='opening')
    assert result.revised_statement is None


def test_review_can_lookup_prior_conditions_and_ground_edits_in_newly_read_facts(snapshot):
    snapshot.facts['PX.BASE'] = snapshot.facts['PX.CLOSE'].model_copy(update={'id': 'PX.BASE', 'value': 42.0})
    current = review_candidate(snapshot)
    target = review_candidate(snapshot)
    target.statement_id = 'debate:bear:t1'
    other = review_candidate(snapshot)
    other.statement_id = 'debate:bull:t1'
    other.evidence[0].source_id, other.evidence[0].value = 'PX.BASE', 42.0
    other.analysis.interpretations[0].limitations = ['예전 발언의 별도 조건은 검증되지 않았어요.']
    current.analysis.rebuttal = Rebuttal(target_statement_id=target.statement_id,
        target_quote=target.argument, acknowledged='관측값은 인정해요.',
        reason='미래는 확정할 수 없어요.', unresolved=['미래 관계는 미확인'])
    transcript = [prompts.render_statement(Side.BEAR, 'opening', target, include_observation=False),
                  prompts.render_statement(Side.BULL, 'opening', other, include_observation=False)]

    class HistoryReviewer:
        def structured(self, conv, **kwargs):
            assert {tool['name'] for tool in kwargs['tools']} == {'read_snapshot', 'get_new_url', 'get_statement_details'}
            fixed = conv.context_ids.decode_response(json.loads(conv.messages[1]['content']))
            assert 'PX.BASE' not in fixed['facts_csv']
            handle = kwargs['tool_handler']
            with pytest.raises(ValueError):
                handle('get_price_metrics', {})
            with pytest.raises(ValueError):
                handle('get_statement_details', {'statement_id': 'another-debate:t1'})
            details = conv.context_ids.decode_response(json.loads(handle('get_statement_details',
                {'statement_id': conv.context_ids.statement_ids[other.statement_id]})))
            assert details['argument'] == other.argument
            assert details['analysis']['interpretations'][0]['limitations'] == other.analysis.interpretations[0].limitations
            assert 'observation' not in details['evidence'][0]
            assert 'PX.BASE' in details['facts_csv']
            response = revised_review(current, sources=('PX.BASE',))
            response['edits'] = [{'path': 'evidence.0.source_id', 'value': 'PX.BASE'},
                                 {'path': 'evidence.0.value', 'value': 42.0}]
            return conv.context_ids.encode_context(response)

    result = review_statement(HistoryReviewer(), current, snapshot, transcript,
                              effort='high', side=Side.BULL, round_kind='rebuttal')
    assert result.revised_statement.evidence[0].source_id == 'PX.BASE'
    assert result.revised_statement.evidence[0].value == 42.0

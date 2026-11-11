from copy import deepcopy
import csv
from io import StringIO
import json
from types import SimpleNamespace

import pytest

from bullbear.context_ids import RequestIds


@pytest.fixture
def request_ids():
    snapshot = SimpleNamespace(facts={key: None for key in ('PX.CLOSE', 'NEWS.A', 'PX.BASE')})
    transcript = [json.dumps({'statement_id': statement, 'side': side,
                             'claim': 'PX.CLOSE', 'argument': 'F3도 원문입니다.',
                             'evidence': [{'ref': 'E1', 'source_id': 'PX.CLOSE',
                                           'interpretation_id': statement + ':E1'}]})
                  for statement, side in [('deb:bull:t1', 'bull'), ('deb:bear:t1', 'bear')]]
    return RequestIds(snapshot, transcript)


def test_request_aliases_are_stable_and_do_not_mutate_storage(request_ids):
    assert request_ids.fact_ids == {'NEWS.A': '@F1', 'PX.BASE': '@F2', 'PX.CLOSE': '@F3'}
    assert request_ids.statement_ids == {'deb:bull:t1': '@S1', 'deb:bear:t1': '@S2'}
    original = {'statement_id': 'deb:bull:t1', 'evidence': [{'ref': 'E1', 'source_id': 'PX.CLOSE',
                  'interpretation_id': 'deb:bull:t1:E1', 'value': 123.0}],
                'analysis': {'rebuttal': {'target_statement_id': 'deb:bear:t1', 'target_quote': 'PX.CLOSE'}}}
    before = deepcopy(original)
    encoded = request_ids.encode_context(original)
    assert encoded['statement_id'] == '@S1'
    assert encoded['evidence'][0] == {'ref': 'E1', 'source_id': '@F3', 'interpretation_id': '@I1', 'value': 123.0}
    assert encoded['analysis']['rebuttal'] == {'target_statement_id': '@S2', 'target_quote': 'PX.CLOSE'}
    assert request_ids.decode_response(encoded) == original
    assert original == before


@pytest.mark.parametrize('field', [
    'claim', 'argument', 'target_quote', 'quote', 'interpretation', 'assumptions', 'limitations',
    'limits', 'acknowledged', 'reason', 'unresolved', 'retained', 'conceded', 'outlook_reason',
    'uncertainties', 'change_conditions', 'comment', 'comments', 'reasoning', 'common_ground',
    'core_issues', 'disagreements', 'unverified', 'outlook_basis', 'outlook_limits', 'instruction',
    'summary', 'text', 'note', 'label', 'title', 'description', 'warnings',
])
def test_prose_is_never_replaced_even_when_equal_to_an_id(request_ids, field):
    for value in ['F1', 'PX.CLOSE', '@F3', ['PX.CLOSE', '@F3'], {'source_id': 'PX.CLOSE'}]:
        payload = {field: value}
        assert request_ids.encode_context(payload) == payload
        assert request_ids.decode_response(payload) == payload


def test_csv_aliases_only_identifier_columns_and_preserves_quoted_prose(request_ids):
    text = StringIO(newline='')
    writer = csv.writer(text, lineterminator='\r\n')
    note = 'PX.CLOSE, "그대로"\r\nF3도 바꾸지 않아요.'
    inputs = ['PX.BASE', ['PX.CLOSE', 'UNKNOWN']]
    writer.writerow(['source_id', 'label', 'value', 'inputs', 'note'])
    writer.writerow(['PX.CLOSE', 'PX.CLOSE', '123.0', json.dumps(inputs), note])
    original = text.getvalue()
    encoded = request_ids.encode_context({'referenced_facts_csv': original})
    row, = csv.DictReader(StringIO(encoded['referenced_facts_csv'], newline=''))
    assert row['source_id'] == '@F3'
    assert json.loads(row['inputs']) == ['@F2', ['@F3', 'UNKNOWN']]
    assert row['label'] == 'PX.CLOSE' and row['note'] == note and row['value'] == '123.0'
    decoded = request_ids.decode_response(encoded)
    restored, = csv.DictReader(StringIO(decoded['referenced_facts_csv'], newline=''))
    assert restored['source_id'] == 'PX.CLOSE' and json.loads(restored['inputs']) == inputs
    assert restored['note'] == note
    chart = {'weekly_ohlcv_csv': 'date,open,close\n2026-11-11,1,2\n'}
    assert request_ids.encode_context(chart) == chart


def test_news_result_keys_are_aliases_but_article_content_is_verbatim(request_ids):
    original = {'news_lookup_results': {'NEWS.A': {'status': 'summary', 'summary_read': True,
                                                 'summary': 'PX.CLOSE', 'text': '@F3'}}}
    encoded = request_ids.encode_context(original)
    assert encoded['news_lookup_results'] == {'@F1': original['news_lookup_results']['NEWS.A']}
    assert request_ids.decode_response(encoded) == original


def test_compact_wire_only_rewrites_documented_id_positions(request_ids):
    wire = {'claim': 'PX.CLOSE', 'rebuttal': ['deb:bear:t1', 'PX.CLOSE', 'PX.CLOSE', 'PX.CLOSE', 'PX.CLOSE'],
            'forecast': {'evidence': ['PX.CLOSE'], 'keys': ['deb:bull:t1:E1'],
                         'comments': ['PX.CLOSE', '@F3'],
                         'analysis': [['common', 'PX.CLOSE']],
                         'reviews': [['deb:bull:t1', 'concern', 'PX.CLOSE', 'PX.CLOSE', 'NEWS.A']]}}
    encoded = request_ids.encode_context(wire)
    assert encoded['rebuttal'] == ['@S2', 'PX.CLOSE', 'PX.CLOSE', 'PX.CLOSE', 'PX.CLOSE']
    assert encoded['forecast']['evidence'] == ['@F3']
    assert encoded['forecast']['keys'] == ['@I1']
    assert encoded['forecast']['analysis'] == [['common', 'PX.CLOSE']]
    assert encoded['forecast']['reviews'] == [['@S1', 'concern', 'PX.CLOSE', '@F3', '@F1']]
    assert request_ids.decode_response(encoded) == wire


def test_reviewer_patch_values_are_decoded_only_at_id_paths(request_ids):
    response = {'issues': [{'quote': '@F3', 'source_ids': ['@F1'], 'reason': '@F3'}],
                'edits': [{'path': 'evidence.0.source_id', 'value': '@F3'},
                          {'path': 'argument', 'value': '@F3'},
                          {'path': 'analysis.interpretations.0.limitations', 'value': ['@F3']}]}
    decoded = request_ids.decode_response(response)
    assert decoded['issues'] == [{'quote': '@F3', 'source_ids': ['NEWS.A'], 'reason': '@F3'}]
    assert decoded['edits'][0]['value'] == 'PX.CLOSE'
    assert decoded['edits'][1:] == response['edits'][1:]


def test_tool_wrapper_decodes_ids_before_execution_and_encodes_only_returned_ids(request_ids):
    calls = []

    def handler(name, args):
        calls.append((name, args))
        return json.dumps({'source_id': args['args'][0], 'note': 'PX.CLOSE'})

    result = request_ids.wrap_tool_handler(handler)('read_snapshot', {'kind': 'facts', 'args': ['@F3']})
    assert calls == [('read_snapshot', {'kind': 'facts', 'args': ['PX.CLOSE']})]
    assert json.loads(result) == {'source_id': '@F3', 'note': 'PX.CLOSE'}
    assert request_ids.decode_tool_arguments('get_statement_details', {'statement_id': '@S2'}) == {
        'statement_id': 'deb:bear:t1'}
    assert request_ids.decode_tool_arguments('get_new_url', {'source_id': '@F1'}) == {'source_id': 'NEWS.A'}
    assert request_ids.decode_tool_arguments('read_snapshot', {'kind': 'catalog', 'args': ['@F3', '0']}) == {
        'kind': 'catalog', 'args': ['@F3', '0']}
    assert request_ids.encode_tool_result('plain error PX.CLOSE') == 'plain error PX.CLOSE'


def test_unknown_aliases_remain_for_canonical_validation(request_ids):
    response = {'statement_id': '@S99', 'evidence': [{'source_id': '@F999'}],
                'analysis': {'key_interpretation_ids': ['@I999']}}
    assert request_ids.decode_response(response) == response
    assert request_ids.decode_tool_arguments('read_snapshot', {'kind': 'facts', 'args': ['@F999']}) == {
        'kind': 'facts', 'args': ['@F999']}


def test_existing_canonical_alias_shaped_ids_do_not_create_ambiguity():
    ids = RequestIds(SimpleNamespace(facts={'@F1': None, 'PX.CLOSE': None}), [])
    encoded = ids.encode_context({'source_ids': ['@F1', 'PX.CLOSE']})
    assert len(set(encoded['source_ids'])) == 2
    assert '@F1' not in encoded['source_ids']
    assert ids.decode_response(encoded) == {'source_ids': ['@F1', 'PX.CLOSE']}

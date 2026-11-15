import json

import pytest
from fastapi.testclient import TestClient

from bullbear.events import EventLog
from bullbear.interpretations import analysis_issues, bind_statement
from bullbear.llm import LLMError, anthropic_schema
from bullbear.prompts import render_statement
from bullbear.schemas import (Statement, ModeratorDecision, Rebuttal, Closing, Side, Decision,
                              STRUCTURED_STATEMENT_SCHEMA, STRUCTURED_MODERATOR_SCHEMA)
from bullbear.server.progress import generation_progress
from bullbear.server.store import Store
from bullbear.snapshot import build_snapshot
from bullbear.verifier import verify
from .fakes import FakeSource, NOW, statement, ScriptedModerator
from .learning_fixtures import with_analysis
from .test_semantic import QueueLLM
from .test_server import setup, app_for, start, completed, AUTH, parse_sse
from .http_fixture import TestRunner


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)


def candidate():
    st = with_analysis(statement(('E1', 'PX.CLOSE', 399), argument='관측된 가격은 방향을 보장하지 않는다 [E1].'))
    st.claim = '7거래일 코스피 대비 비슷한 흐름을 예상한다'
    return st




def test_same_source_has_distinct_stable_interpretation_ids_and_snapshot_copy(snap):
    original = candidate()
    bull = bind_statement(original, snap, debate_id='d', turn_index=1)
    original.evidence[0].interpretation = '같은 가격의 다른 해석'
    bear = bind_statement(original, snap, debate_id='d', turn_index=2)
    assert bull.evidence[0].source_id == bear.evidence[0].source_id
    assert bull.evidence[0].interpretation_id != bear.evidence[0].interpretation_id
    assert bull.evidence[0].interpretation != bear.evidence[0].interpretation
    assert original.statement_id is None and original.evidence[0].observation is None
    assert bull.evidence[0].observation == snap.facts['PX.CLOSE']
    snap.facts['PX.CLOSE'].value = 999
    assert bull.evidence[0].observation.value == 399
    assert Statement.model_validate_json(bull.model_dump_json()) == bull


def test_unknown_source_keeps_authored_evidence_without_fabricating_observation(snap):
    original = candidate()
    original.evidence[0].source_id = 'UNKNOWN.FACT'
    bound = bind_statement(original, snap, debate_id='d', turn_index=1)
    assert bound.evidence[0].source_id == 'UNKNOWN.FACT'
    assert bound.evidence[0].value == original.evidence[0].value
    assert bound.evidence[0].observation is None
    assert bound.evidence[0].interpretation_id == 'd:t1:E1'


@pytest.mark.parametrize('target,quote,bad', [('d:t1', '관측된 가격은 방향을', False),
    ('missing', '관측된 가격은 방향을', True), ('d:t2', '관측된 가격은 방향을', True),
    ('d:t1', '상대가 말하지 않은 문장', True)])
def test_rebuttal_targets_real_opposing_statement(snap, target, quote, bad):
    history = [render_statement(side, 'opening', bind_statement(candidate(), snap,
        debate_id='d', turn_index=i)) for i, side in enumerate((Side.BEAR, Side.BULL), 1)]
    st = candidate()
    st.analysis.rebuttal = Rebuttal(target_statement_id=target, target_quote=quote,
        acknowledged='가격 관측은 인정', reason='향후 지속은 미확인', unresolved=['관계 지속 여부'])
    assert bool(analysis_issues(st, transcript=history, side=Side.BULL, round_kind='rebuttal')) is bad






@pytest.mark.parametrize('round_kind,code', [('rebuttal', 'missing_rebuttal'), ('closing', 'missing_closing')])
def test_round_specific_summary_cannot_be_omitted(round_kind, code):
    assert code in {i.code for i in analysis_issues(candidate(), transcript=[], side=Side.BULL,
                                                   round_kind=round_kind)}


def test_blank_assumptions_do_not_satisfy_structured_output():
    st = candidate()
    st.analysis.interpretations[0].assumptions = ['   ']
    assert 'empty_analysis' in {i.code for i in analysis_issues(st, transcript=[], side=Side.BULL,
                                                              round_kind='opening')}






@pytest.mark.parametrize('schema', [STRUCTURED_STATEMENT_SCHEMA, STRUCTURED_MODERATOR_SCHEMA])
def test_generation_schema_requires_analysis_and_resolves_nested_definitions(schema):
    result = anthropic_schema(schema)
    assert 'analysis' in result['required']
    def visit(node):
        if isinstance(node, dict):
            if '$ref' in node:
                assert node['$ref'].split('/')[-1] in result['$defs']
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['properties']) == set(node['required'])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(result)




def test_restart_distinguishes_interrupted_moderator_and_keeps_events(tmp_path):
    store = Store(tmp_path)
    row, _ = store.create('r', 'fp', '005930', '2026-10-16', 1)
    for stage in ('opening', 'rebuttal', 'closing'):
        for side in ('bull', 'bear'):
            store.emit(row['id'], 'statement_accepted', {'side': side, 'round': stage})
    store.emit(row['id'], 'moderator_started', {})
    assert generation_progress(store.events(row['id']))['moderator_status'] == 'running'
    store.close()
    store = Store(tmp_path)
    try:
        events = store.events(row['id'])
        assert generation_progress(events)['moderator_status'] == 'interrupted'
        assert generation_progress(events)['debate_complete'] is True
        assert json.loads(events[-1]['data'])['error']['reason'] == 'worker_restart'
        assert len(events) == 8
    finally:
        store.close()


def test_incomplete_debate_and_extra_round_failure_are_distinct():
    def event(kind, **data):
        return {'type': kind, 'data': json.dumps(data)}
    events = [event('turn_started', side='bull', round='opening')]
    assert generation_progress(events, terminal='failed')['moderator_status'] == 'not_started'
    assert not generation_progress(events, terminal='failed')['debate_complete']
    events += [event('statement_accepted', side=side, round=stage)
               for side in ('bull', 'bear') for stage in ('opening', 'rebuttal', 'closing')]
    events += [event('moderator_started'), event('extra_round_requested')]
    progress = generation_progress(events, terminal='failed')
    assert progress['base_rounds_complete'] and not progress['debate_complete']
    assert progress['moderator_status'] == 'waiting'

import json

import pytest

from bullbear.history import contains_quote, history_entry, reference_map, structured_record
from bullbear.interpretations import bind_statement, history_records
from bullbear.presentation import used_sources
from bullbear.prompts import render_statement
from bullbear.schemas import Side
from bullbear.semantic import SemanticReviewer
from .fakes import statement
from .learning_fixtures import with_analysis
from .test_graph_runtime import snapshot
from .test_semantic import QueueLLM


def legacy(record, *, structured=True):
    speaker = '매수' if record['side'] == 'bull' else '매도'
    text = f"[첫 주장] {speaker} 측\n주장: {record['claim']}\n{record['argument']}\n근거:\n"
    text += '\n'.join(f"  {e['ref']}: {e['source_id']} = {e['value']} ({e['interpretation']})"
                      for e in record['evidence'])
    return text + ('\n구조화 정보: ' + json.dumps(record, ensure_ascii=False) if structured else '')


def test_single_json_preserves_full_statement_and_escaped_prose(snapshot):
    st = with_analysis(statement(('E1', 'PX.CLOSE', 399),
        argument='인용 "문장"과 줄바꿈\n구조화 정보: 를 포함한 본문 [E1].'))
    bound = bind_statement(st, snapshot, debate_id='d', turn_index=1)
    rendered = render_statement(Side.BULL, 'opening', bound)
    record = json.loads(rendered)
    assert record == dict(side='bull', round='opening', **bound.model_dump(mode='json'))
    assert record['evidence'][0]['observation'] == snapshot.facts['PX.CLOSE'].model_dump(mode='json')
    assert record['statement_id'] == 'd:t1'
    assert record['evidence'][0]['interpretation_id']
    assert structured_record(rendered) == record
    assert history_records([rendered]) == history_records([legacy(record)])
    assert len(rendered) < len(legacy(record))


@pytest.mark.parametrize('format', ['json', 'legacy_json', 'legacy_text'])
def test_quote_ownership_and_turn_local_refs_survive_formats(snapshot, format):
    quote = '가격 관측만으로 방향을 확정할 수 없습니다'
    evidence_only = '이 문구는 근거 해석에만 있습니다'
    entries = []
    for side, source, value in [(Side.BULL, 'PX.CLOSE', 399), (Side.BEAR, 'VAL.PER_TTM', 8)]:
        st = statement(('E1', source, value), argument=quote + ' [E1].')
        st.evidence[0].interpretation = evidence_only
        entry = render_statement(side, 'opening', st)
        if format != 'json':
            entry = legacy(json.loads(entry), structured=format == 'legacy_json')
        entries.append(entry)
    candidate = statement(('E1', 'PX.CLOSE', 399),
        argument=f'“{quote}”라는 주장과 상대의 “{evidence_only}”라는 설명을 구분합니다 [E1].')
    llm = QueueLLM([{'issues': []}])
    SemanticReviewer(llm, snapshot).check(candidate, entries, ['PX.CLOSE'],
                                        side=Side.BEAR, round_kind='rebuttal')
    payload = json.loads(llm.calls[0][0].messages[0]['content'])
    assert payload['candidate_role'] == 'bear'
    assert payload['candidate_round'] == 'rebuttal'
    assert payload['reference_map'] == {'E1': 'PX.CLOSE'}
    assert [turn['speaker'] for turn in payload['history']] == ['bull', 'bear']
    assert payload['history'][1]['text'] == entries[1]
    assert [turn['reference_map'] for turn in payload['history']] == [
        {'E1': 'PX.CLOSE'}, {'E1': 'VAL.PER_TTM'}]
    assert payload['argument_quotes'][0]['source_matches'] == [
        {'history_index': 0, 'speaker': 'bull'}, {'history_index': 1, 'speaker': 'bear'}]
    assert payload['argument_quotes'][1]['source_matches'] == []
    assert used_sources(entries, snapshot) == {'PX.CLOSE', 'VAL.PER_TTM'}
    assert contains_quote(history_entry(entries[0]), quote)
    assert not contains_quote(history_entry(entries[0]), evidence_only)
    assert reference_map(history_entry(entries[0])) == {'E1': 'PX.CLOSE'}


@pytest.mark.parametrize('entry', [None, 'invalid', '[]', 'null', 'text\n구조화 정보: broken'])
def test_non_record_history_is_ignored(entry):
    assert structured_record(entry) is None
    assert history_records([entry]) == []
    assert history_entry(entry) == {}

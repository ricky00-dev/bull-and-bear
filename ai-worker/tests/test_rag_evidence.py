"""Offline evidence routing, actual SQLite retrieval and authenticated HTTP."""
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from bullbear.config import load_settings
from bullbear.snapshot import Snapshot, Fact
from bullbear.rag.evidence import DocumentRequest, FactRequest, parse_request, METRICS, assess
from bullbear.rag.retrieval import Retriever
from bullbear.rag.selection import SelectionPolicy
from bullbear.rag.store import RagStore
from bullbear.rag.index import GenerationIndex
from bullbear.server.app import create_app
from .http_fixture import fixture_market
from .test_rag_retrieval import seed
from .test_server import AUTH

DAY = date(2026, 11, 2)
AT = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)


def snapshot():
    return Snapshot(snapshot_id='evidence-fixture', ticker='005930', name='삼성전자',
        as_of=DAY, created_at=AT, provider='offline', facts={
            'PX.CLOSE': Fact(id='PX.CLOSE', category='price', label='종가', value=1000, unit='KRW/share',
                             as_of=DAY, source='fixture'),
            'VAL.PER_TTM': Fact(id='VAL.PER_TTM', category='valuation', label='PER', value=12, unit='x',
                                as_of=DAY, source='fixture')})


def request(**kwargs):
    return FactRequest(**{'ticker': '005930', 'metric': 'per_ttm', **kwargs})


def test_price_per_share_unit_and_dependent_valuation():
    snap = snapshot()
    snap.facts['VAL.PER_TTM'].source = 'derived'
    snap.facts['VAL.PER_TTM'].inputs = ['PX.CLOSE']
    assert assess(snap, request(metric='close', unit='KRW/share'))['answerability'] == 'supported_fact'
    assert assess(snap, request(metric='close', unit='KRW'))['reasons'] == ['unit_mismatch']
    assert assess(snap, request())['answerability'] == 'supported_fact'
    snap.facts['PX.CLOSE'].unit = 'KRW'
    assert assess(snap, request())['reasons'] == ['dependency_unit_mismatch']


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    from bullbear.rag.embeddings import OpenAIEmbeddings
    from bullbear.llm import LLM
    monkeypatch.setattr(OpenAIEmbeddings, 'embed', lambda *a, **k: pytest.fail('embedding network forbidden'))
    monkeypatch.setattr(LLM, '__init__', lambda *a, **k: pytest.fail('generation network forbidden'))


@pytest.mark.parametrize('metric', list(METRICS))
def test_structured_metric_binds_exact_fact(metric):
    snap = snapshot()
    fact_id, unit = METRICS[metric]
    snap.facts[fact_id] = Fact(id=fact_id, category='valuation', label='value', value=12,
                             unit=unit, as_of=DAY, source='fixture')
    result = assess(snap, request(metric=metric))
    assert result['answerability'] == 'supported_fact'
    assert result['facts'][0]['fact_id'] == fact_id
    assert result['facts'][0]['unit'] == unit


@pytest.mark.parametrize('question', ['안녕', '현재 PER은 몇 배인가', 'SK하이닉스의 종가',
    'PER 뜻과 현재 값을 알려줘', '내일 주가 예측', '이익에 비해 가격이 비싼가', '000660 설명'])
def test_documents_never_classify_question_or_bind_facts(question):
    result = assess(snapshot(), DocumentRequest(question=question, ticker='005930'))
    assert result['route'] == 'background'
    assert result['mode'] == 'documents' and result['facts'] == []
    assert 'intent' not in result and result['reasons'] == []


@pytest.mark.parametrize('payload', [
    {'ticker': '005930', 'question': 'PER'},  # CLI requires an explicit mode.
    {'mode': 'facts', 'ticker': '005930', 'question': 'PER'},
    {'mode': 'facts', 'ticker': '005930', 'metric': 'per_ttm', 'question': 'PER'},
    {'mode': 'facts', 'ticker': '005930', 'metric': 'operating_margin_quarter'},
    {'mode': 'facts', 'ticker': '005930', 'metric': 'per_ttm', 'period': 'quarter'},
    {'mode': 'documents', 'ticker': '005930', 'question': 'PER', 'unit': 'x'},
    {'mode': 'documents', 'ticker': '005930', 'question': '   '},
])
def test_invalid_or_mixed_payload_is_not_inferred(payload):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        parse_request(payload)


def test_structured_constraints_and_cutoff():
    snap = snapshot()
    assert assess(snap, request(unit='%'))['reasons'] == ['unit_mismatch']
    assert assess(snap, request(as_of=DAY-timedelta(days=1)))['reasons'] == ['fact_date_mismatch']
    assert assess(snap, request(ticker='000660'))['reasons'] == ['ticker_mismatch']
    assert assess(snap, DocumentRequest(ticker='000660', question='PER'))['reasons'] == ['ticker_mismatch']
    assert assess(snap, request(as_of=DAY+timedelta(days=1)))['reasons'] == ['unconfirmed_or_future_date']
    assert assess(snap, request(metric='pbr'))['reasons'] == ['required_fact_missing']
    early = snap.model_copy(update={'created_at': AT.replace(hour=0)})
    assert assess(early, request(metric='close', as_of=DAY))['reasons'] == ['unconfirmed_or_future_date']


@pytest.mark.parametrize('update,reason', [({'value': None}, 'fact_value_unavailable'),
    ({'value': float('nan')}, 'fact_value_unavailable'), ({'unit': '%'}, 'fact_unit_mismatch'),
    ({'id': 'wrong'}, 'invalid_fact_identity_or_source'), ({'source': ''}, 'invalid_fact_identity_or_source'),
    ({'source': 'derived', 'inputs': ['missing']}, 'missing_fact_dependency'),
    ({'source': 'derived', 'inputs': ['VAL.PER_TTM']}, 'cyclic_fact_dependencies'),
    ({'published_at': AT+timedelta(seconds=1)}, 'fact_not_published_at_cutoff')])
def test_invalid_fact_or_lineage_not_exposed(update, reason):
    snap = snapshot()
    snap.facts['VAL.PER_TTM'] = snap.facts['VAL.PER_TTM'].model_copy(update=update)
    result = assess(snap, request())
    assert result['reasons'] == [reason] and not result['facts']


def test_derived_lineage_and_unit_check():
    snap = snapshot()
    snap.facts['VAL.PER_TTM'].source = 'derived'
    snap.facts['VAL.PER_TTM'].inputs = ['PX.CLOSE']
    assert assess(snap, request())['facts'][0]['verified_lineage'] == ['PX.CLOSE', 'VAL.PER_TTM']
    snap.facts['PX.CLOSE'].unit = '%'
    assert assess(snap, request())['reasons'] == ['dependency_unit_mismatch']


def test_search_routes_facts_without_index_and_persists_replay(tmp_path, monkeypatch):
    with RagStore(tmp_path) as store:
        retriever = Retriever(store)
        monkeypatch.setattr(retriever, '_search', lambda *a, **k: pytest.fail('facts must bypass background'))
        good = retriever.retrieve(snapshot(), generation_id='not-needed', request=request())
        assert good.payload['status'] == 'empty'  # No knowledge paragraphs masquerading as market facts.
        assert good.payload['answerability'] == 'supported_fact'
        assert retriever.load_context(good.context_id) == good
        bad = retriever.retrieve(snapshot(), generation_id='not-needed', request=request(unit='%'))
        assert bad.context_id != good.context_id and bad.payload['answerability'] == 'insufficient_evidence'


def test_evidence_storage_failure_is_not_success(tmp_path, monkeypatch):
    from bullbear.rag import retrieval
    def unavailable(*args, **kwargs):
        raise OSError('storage offline')
    monkeypatch.setattr(retrieval, 'save_context', unavailable)
    with RagStore(tmp_path) as store:
        with pytest.raises(OSError):
            Retriever(store).retrieve(snapshot(), generation_id='', request=request())


def test_cli_requires_explicit_mode_and_facts_need_no_generation(tmp_path, monkeypatch, capsys):
    from bullbear.rag.cli import main
    for name in ('ARCHIVE', 'CONTEXT'):
        monkeypatch.setenv('BULLBEAR_RAG_' + name + '_BACKEND', 'sqlite')
    monkeypatch.setenv('BULLBEAR_RAG_OBJECT_BACKEND', 'local')
    snap_file, request_file = tmp_path / 'snapshot.json', tmp_path / 'request.json'
    snap_file.write_text(snapshot().model_dump_json(), encoding='utf-8')
    request_file.write_text(request().model_dump_json(), encoding='utf-8')
    args = ['--data-dir', str(tmp_path), 'retrieve', str(snap_file), '--request', str(request_file)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)['payload']['answerability'] == 'supported_fact'
    request_file.write_text(json.dumps({'ticker': '005930', 'question': 'PER'}), encoding='utf-8')
    assert main(args) == 1
    request_file.write_text(DocumentRequest(ticker='005930', question='PER').model_dump_json(), encoding='utf-8')
    assert main(args) == 1  # No generation; never silently switches to facts.


def test_actual_concept_search_uses_question_not_snapshot_labels(tmp_path):
    with RagStore(tmp_path) as store:
        _, per, _ = seed(store, text='PER 주가수익비율 산식')
        generation = GenerationIndex(store).publish(AT)
        retriever = Retriever(store, selection_policy=SelectionPolicy())
        result = retriever.retrieve(snapshot(), generation_id=generation, time_policy='reconstructed-v1',
                                    request=DocumentRequest(question='PER 정의를 설명해 주세요', ticker='005930')).payload
        assert result['answerability'] == 'documents_found', result
        assert result['items'][0]['chunk_id'] == per.chunk_id
        assert result['evidence']['facts'] == []
        assert '종가' not in result['query_terms']


def test_http_facts_missing_concept_auth_and_no_model_or_market_calls(tmp_path, monkeypatch):
    settings = replace(load_settings(), data_dir=tmp_path, rag_enabled=True,
                       rag_archive_backend='sqlite', rag_context_backend='sqlite', rag_object_backend='local')
    with RagStore(tmp_path / 'rag') as store:
        seed(store, text='PER 주가수익비율 산식')
        generation = GenerationIndex(store).publish(AT)
    settings = replace(settings, rag_generation_id=generation)
    market = fixture_market(settings)
    monkeypatch.setattr(market, 'snapshot', lambda *a: pytest.fail('market collection forbidden'))
    app = create_app(settings=settings, market=market, token='test-token',
                     runner_factory=lambda: pytest.fail('runner forbidden'))
    try:
        with TestClient(app) as client:
            svc = app.state.service
            snap = snapshot()
            row, _ = svc.store.create('seed', 'seed', snap.ticker, str(DAY), 2)
            svc.store.save_snapshot(row['id'], snap, binding_factory=svc.capture_generation)
            svc.store.emit(row['id'], 'debate_completed', {})
            body = dict(request().model_dump(mode='json'), snapshot_id=snap.snapshot_id)
            assert client.post('/rag/facts', json=body).status_code == 401
            first = client.post('/rag/facts', json=body, headers=AUTH)
            assert first.status_code == 200, first.text
            assert first.json()['facts'][0]['value'] == 12
            assert 'documents' not in first.json() and first.json()['mode'] == 'facts'
            assert client.post('/rag/facts', json=body, headers=AUTH).json() == first.json()
            missing = client.post('/rag/facts', json={**body, 'metric': 'pbr'}, headers=AUTH).json()
            assert missing['answerability'] == 'insufficient_evidence' and missing['facts'] == []
            search = dict(snapshot_id=snap.snapshot_id, ticker=snap.ticker, question='PER 현재 값과 정의')
            concept = client.post('/rag/search', json=search, headers=AUTH)
            assert concept.status_code == 200, concept.text
            assert concept.json()['documents'] and 'facts' not in concept.json()
            assert concept.json()['answer_scope'] == 'retrieved_documents_not_verified_numeric_answer'
            assert concept.json()['answerability'] == 'documents_found'
            assert client.post('/rag/query', json=search, headers=AUTH).status_code == 410
            assert client.post('/rag/query', json=search).status_code == 401
            assert client.post('/rag/search', json={**search, 'metric': 'per_ttm'}, headers=AUTH).status_code == 400
            assert client.post('/rag/facts', json=search, headers=AUTH).status_code == 400
            assert client.post('/rag/facts', json={**body, 'question': 'PER'}, headers=AUTH).status_code == 400
            assert client.post('/rag/facts', json={**body, 'snapshot_id': 'missing'}, headers=AUTH).status_code == 404
            assert client.post('/rag/facts', json={**body, 'strategy': 'paid'}, headers=AUTH).status_code == 400
    finally:
        market.close()

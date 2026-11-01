import json
from dataclasses import replace

import pytest

from bullbear.rag.selection import SelectionPolicy, focused_query, focused_terms, gate, query_text
from bullbear.rag.selection_evaluation import calibrate
from bullbear.rag.retrieval import Retriever
from bullbear.rag.store import RagStore
from bullbear.rag.index import GenerationIndex
from bullbear.rag.vectors import VectorIndex
from bullbear.rag.vector_evaluation import ComparisonCase, compare
from bullbear.snapshot import Fact, Snapshot, build_snapshot
from .fakes import FakeSource, NOW
from .test_rag_retrieval import seed
from .test_rag_vectors import archive_dsn, vector_service
from .test_rag_http import setup


def probe(label):
    fact = Fact(id='EVAL.PROBE', category='valuation', label=label, value=None,
                unit='text', as_of=NOW.date(), source='test')
    return Snapshot(snapshot_id='SEL.TEST', ticker='005930', name='삼성전자', as_of=NOW.date(),
                    created_at=NOW, provider='test', facts={fact.id: fact})


def test_focused_query_drops_injected_scaffolding_and_preserves_label_order():
    snapshot = probe('PER은 무엇인가')
    assert focused_query(snapshot) == 'PER은 무엇인가'
    terms = focused_terms(snapshot)
    assert 'per' in terms and '주가수익비율' in terms
    assert not {'kospi', 'event_relevance', '삼성전자', 'valuation', '005930'} & set(terms)
    assert query_text(snapshot, None) != query_text(snapshot, SelectionPolicy())


def test_lexical_relevance_and_explicit_abstention(tmp_path):
    with RagStore(tmp_path) as store:
        _, good, _ = seed(store, 'per', text='PER 주가수익비율 산식', horizons=('common',))
        seed(store, 'unrelated', text='코스피 거래일 초과수익', horizons=('short',))
        generation = GenerationIndex(store).publish(NOW)
        retriever = Retriever(store, selection_policy=SelectionPolicy())
        context = retriever.retrieve(probe('PER'), generation_id=generation, time_policy='reconstructed-v1')
        assert [m['chunk_id'] for m in context.payload['items']] == [good.chunk_id]
        assert context.payload['answerability'] == 'supported_background'
        empty = retriever.retrieve(probe('요리'), generation_id=generation, time_policy='reconstructed-v1')
        assert empty.payload['status'] == 'empty'
        assert empty.payload['answerability'] == 'abstain'
        assert empty.payload['abstention_reason'] == 'no_supported_candidates'
        broken = retriever.retrieve(probe('요리'), generation_id='missing', time_policy='reconstructed-v1')
        assert broken.payload['status'] == 'failed'
        assert 'answerability' not in broken.payload


def test_vector_gate_rejects_weak_and_distant_candidates(vector_service, tmp_path):
    snapshot = probe('volatility')
    with RagStore(tmp_path) as store:
        _, good, _ = seed(store, 'good', text='가격의 흔들림 크기', horizons=('common',))
        seed(store, 'bad', text='unrelated', horizons=('short',))
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        policy = SelectionPolicy(embedding_version=index.version_id, max_distance=0.4)
        vector_service.prepare(query_text(snapshot, policy), 'query', daily_budget_nano=100000)
        for strategy in ('dense', 'hybrid'):
            result = Retriever(store, strategy=strategy, vector_index=index, selection_policy=policy).retrieve(
                snapshot, generation_id=generation, time_policy='reconstructed-v1').payload
            assert [r['chunk_id'] for r in result['items']] == [good.chunk_id]
            assert any(c['reason'] == 'below_relevance_threshold' for c in result['candidates'])
        with pytest.raises(ValueError, match='version mismatch'):
            Retriever(store, strategy='dense', vector_index=index, selection_policy=SelectionPolicy())


def test_band_and_score_boundary_and_policy_identity():
    p = SelectionPolicy(max_distance=0.5, distance_band=0.1)
    row = dict(cosine_distance=0.5, score=-0.2)
    assert gate(p, 'dense', {}, row, [], 0.4, 0) == 'selected'
    assert gate(p, 'dense', {}, row, [], 0.3, 0) == 'outside_best_evidence_band'
    member = dict(title='PER', text='주가수익비율')
    assert gate(p, 'bm25', member, row, ['per'], 0, 1) == 'below_lexical_score_band'
    assert gate(p, 'bm25', member, row, ['공시'], 0, 1) == 'no_content_overlap'
    assert p.policy_id != p.model_copy(update={'max_items': 1}).policy_id


def test_calibration_never_accepts_holdout_labels():
    with pytest.raises(ValueError, match='development'):
        calibrate([dict(split='holdout')], 'v')
    samples = [dict(split='development', relevant=['good'], scores=[dict(chunk_id='good',
        rowid=1, distance=0.35, document_id='doc', text_hash='text', duplicate_group_id=None, horizons=['common'])]),
        dict(split='development', relevant=[], scores=[dict(chunk_id='wrong', rowid=1, distance=0.7,
             document_id='other', text_hash='other', duplicate_group_id=None, horizons=['common'])])]
    policy, report = calibrate(samples, 'v')
    assert report['selected']['negative_specificity'] == 1
    assert report['selected']['recall'] == 1
    assert policy.max_distance < 0.7


def test_negative_metric_checks_other_horizons(vector_service, tmp_path):
    snapshot = probe('volatility')
    with RagStore(tmp_path) as store:
        seed(store, horizons=('short',))
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        index.build(store, generation, daily_budget_nano=100000)
        vector_service.prepare(query_text(snapshot), 'query', daily_budget_nano=100000)
        report = compare(store, index, generation, [ComparisonCase(id='negative', snapshot=snapshot,
            path='common', relevant=[], expect_empty=True)], context_repository=None)
        assert report['summary']['dense']['unexpected_answers'] == 1
        assert report['summary']['dense']['unnecessary_selected'] == 1


def test_empty_query_abstains_without_vector_lookup(vector_service, tmp_path, monkeypatch):
    with RagStore(tmp_path) as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        index = VectorIndex(vector_service)
        monkeypatch.setattr(index, 'distances', lambda *a, **k: pytest.fail('empty query lookup'))
        policy = SelectionPolicy(embedding_version=index.version_id)
        snapshot = probe('뉴스 제목은 검색 문맥으로 사용하지 않음')
        snapshot.facts['EVAL.PROBE'] = snapshot.facts['EVAL.PROBE'].model_copy(update={'category': 'news'})
        result = Retriever(store, strategy='dense', vector_index=index, selection_policy=policy).retrieve(
            snapshot, generation_id=generation, time_policy='reconstructed-v1').payload
        assert result['status'] == 'empty' and result['abstention_reason'] == 'no_supported_query'


def test_selective_shadow_uses_same_query_and_frozen_policy(vector_service, tmp_path):
    from datetime import datetime, timezone
    from bullbear.config import load_settings
    from bullbear.rag.shadow import ShadowRunner
    version = tmp_path / 'spec.json'
    version.write_text(vector_service.spec.model_dump_json())
    policy_file = tmp_path / 'policy.json'
    policy = SelectionPolicy(embedding_version=vector_service.spec.version_id)
    policy_file.write_text(policy.model_dump_json())
    settings = replace(load_settings(), data_dir=tmp_path, rag_postgres_dsn=vector_service.repository.dsn,
                       rag_shadow_spec=version, rag_shadow_selection_policy=policy_file,
                       rag_archive_backend='sqlite', rag_object_backend='local')
    with RagStore(tmp_path / 'rag') as store:
        seed(store)
        generation = GenerationIndex(store).publish(NOW)
        VectorIndex(vector_service).build(store, generation, daily_budget_nano=100000)
        snapshot = probe('volatility').model_copy(update={'created_at': datetime.now(timezone.utc)})
        vector_service.prepare(query_text(snapshot, policy), 'query', daily_budget_nano=100000)
        primary = Retriever(store).retrieve(snapshot, generation_id=generation)
    runner = ShadowRunner(settings)
    policy_file.write_text('{}')
    assert runner.submit('selective', snapshot, primary, generation)
    runner.close()
    record = json.loads((tmp_path / 'rag-shadow/selective.json').read_text())
    assert record['status'] == 'completed', record
    assert record['selection_policy_id'] == policy.policy_id
    assert all(c['selected_chunk_ids'] for c in record['comparisons'])


def test_primary_http_policy_is_frozen_and_audited(setup, monkeypatch):
    import sys
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from bullbear.server.app import create_app
    from .http_fixture import TestRunner
    from .test_rag_http import context_for, manifest
    from .test_server import start, completed
    settings, market = setup
    path = settings.data_dir / 'selection.json'
    policy = SelectionPolicy()
    path.write_text(policy.model_dump_json())
    settings = replace(settings, rag_selection_policy=path)
    seen = []
    class Capture:
        def __init__(self, store, *, context_repository, selection_policy):
            seen.append(selection_policy)
        def retrieve(self, snapshot, *, generation_id, generation_binding=None):
            return context_for(snapshot)
    monkeypatch.setitem(sys.modules, 'bullbear.rag.retrieval', SimpleNamespace(Retriever=Capture))
    app = create_app(settings=settings, market=market, token='test-token', runner_factory=lambda: TestRunner(settings))
    with TestClient(app) as client:
        path.write_text('{}')
        run_id = start(client).json()['debate_id']
        assert completed(client, run_id)['status'] == 'completed'
        assert seen == [policy]
        assert manifest(settings, run_id)['knowledge_context']['retrieval_config']['selection_policy_id'] == policy.policy_id


def test_bundle_metrics_do_not_hide_false_abstentions():
    from bullbear.rag.vector_evaluation import bundle_summary
    rows = [dict(bundle_selected=['good', 'bad'], unnecessary_selected=1, abstained=False, bundle_recall=1),
            dict(bundle_selected=[], unnecessary_selected=0, abstained=True, bundle_recall=0),
            dict(bundle_selected=[], unnecessary_selected=0, abstained=True, bundle_recall=None)]
    result = bundle_summary(rows)
    assert result['bundle_micro_precision'] == 0.5
    assert result['false_abstentions'] == 1
    assert result['unnecessary_selected'] == 1


def test_selection_experiment_budget_refused_before_paid_work(tmp_path, monkeypatch):
    from pathlib import Path
    from bullbear.rag import selection_evaluation
    from .test_rag_vectors import spec
    monkeypatch.setattr(selection_evaluation, 'OpenAIEmbeddings', lambda: pytest.fail('paid call attempted'))
    with pytest.raises(ValueError, match='budget'):
        selection_evaluation.run('unused', Path('knowledge/common-short-v1.json'),
            Path('knowledge/embedding-evaluation-v2.json'), tmp_path,
            [spec().model_copy(update={'provider': 'openai'})], 0)

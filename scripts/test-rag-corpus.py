"""Persist a small experimental corpus and inspect real retrieval; no model calls.

Run from the repository with PYTHONPATH=ai-worker/src. Existing data is retained.
Reports are unique; the source corpus is never rewritten or backdated.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from bullbear.rag.context import execution_policy, render_background
from bullbear.rag.corpus import Corpus, import_corpus
from bullbear.rag.index import GenerationIndex
from bullbear.rag.retrieval import Retriever
from bullbear.rag.schemas import digest
from bullbear.rag.store import RagStore
from bullbear.snapshot import Fact, Snapshot


# Direct labels are smoke tests; paraphrases are exploratory, not tuned pass criteria.
CASES = [
    ('per', 'common', 'PER 주가수익비율', 'per-definition'),
    ('margin', 'common', '영업이익률', 'operating-margin'),
    ('volatility', 'common', '변동성은', 'volatility-direction'),
    ('expectations', 'short', '실적 발표 기대 차이', 'earnings-expectations'),
    ('filing', 'short', '공시 공개 시각', 'release-vs-filing'),
    ('momentum', 'short', 'momentum 추세', 'momentum-limit'),
    ('per_paraphrase', 'common', '이익 대비 주가가 비싼가', 'per-definition'),
    ('margin_paraphrase', 'common', '매출 중 본업으로 남긴 이익의 비중', 'operating-margin'),
    ('volatility_paraphrase', 'common', '가격의 흔들림은 오를 가능성을 뜻하나', 'volatility-direction'),
    ('expectations_paraphrase', 'short', '좋은 실적인데 전망이 나쁘면', 'earnings-expectations'),
    ('filing_paraphrase', 'short', '공시 전에 실적을 먼저 발표', 'release-vs-filing'),
    ('momentum_paraphrase', 'short', '최근 상승이 계속 이어질까', 'momentum-limit'),
    ('negative_common', 'common', '광합성 식물세포', None),
    ('negative_short', 'short', '광합성 식물세포', None),
]


def probe(at, case, label):
    fact = Fact(id='EVAL.PROBE', category='valuation', label=label, value=None,
                unit='text', as_of=at.date(), source='synthetic_concept_probe')
    return Snapshot(snapshot_id='RAG-PILOT.' + digest([case, at.isoformat()]),
                    ticker='000000', name='검색검증', as_of=at.date(), created_at=at,
                    provider='synthetic_probe_not_live_market', facts={fact.id: fact})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--allow-agent-reviewed', action='store_true')
    args = parser.parse_args()
    if not args.allow_agent_reviewed:
        parser.error('experimental agent-reviewed data requires --allow-agent-reviewed')
    package = Corpus.model_validate_json(args.corpus.read_text(encoding='utf-8'))
    if {c[3] for c in CASES if c[3]} - {n.id for n in package.notes}:
        parser.error('this smoke suite requires the six common-short-v1 note IDs')
    observed = datetime.now(timezone.utc)
    rows = []
    with RagStore(args.data_dir / 'rag') as store:
        imported = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        counts = store.counts()
        again = import_corpus(store, package, allow_agent_reviewed=True, observed_at=observed)
        assert imported == again and counts == store.counts(), 'non-idempotent exact reimport'
        index = GenerationIndex(store)
        generation = index.publish(observed)
        reader, manifest = index.open(generation)
        reader.close()
        mapping = {n['chunk_id']: n['id'] for n in imported['notes']}
        at = datetime.now(timezone.utc)  # After the actual generation commit receipt.
        for case, path, label, gold in CASES:
            snapshot = probe(at, case, label)
            frozen = snapshot.model_dump_json()
            context = Retriever(store).retrieve(snapshot, generation_id=generation)
            data = context.payload
            assert data['status'] in {'completed', 'empty'}, data['warnings']
            assert snapshot.model_dump_json() == frozen
            assert Retriever(store).load_context(context.context_id) == context
            selected = [mapping.get(i['chunk_id'], i['chunk_id']) for i in data['items'] if i['path'] == path]
            candidates = [mapping.get(i['chunk_id'], i['chunk_id']) for i in data.get('candidates', []) if i['path'] == path]
            if gold and not case.endswith('_paraphrase'):
                assert gold in selected, f'direct concept missing: {case}'
            rows.append({'case': case, 'path': path, 'label': label, 'expected': gold,
                         'selected': selected, 'candidates': candidates,
                         'hit': gold in selected if gold else None,
                         'context_id': context.context_id, 'status': data['status'],
                         'policy_action': execution_policy(context)['action'],
                         'private_background_bytes': len(render_background(context).encode('utf-8'))})
        assert next(r for r in rows if r['case'] == 'negative_common')['selected'] == []
        early = Retriever(store).retrieve(probe(observed-timedelta(seconds=1), 'early', 'PER'),
                                          generation_id=generation)
        assert early.payload['status'] == 'failed' and 'future_generation' in early.payload['warnings']
        assert execution_policy(early)['action'] == 'abort'
        for note in imported['notes']:
            meta = store.revision(note['revision_id'])['content']['metadata']
            assert meta['human_reviewed'] is False and meta['release_status'] == 'experimental'
        report = {'corpus_version': package.corpus_version, 'corpus_hash': imported['corpus_hash'],
                  'observed_at': observed.isoformat(), 'generation_id': generation,
                  'generation_members': len(manifest['members']), 'counts': counts,
                  'exact_reimport_idempotent': True, 'future_generation_blocked': True,
                  'snapshot_unchanged': True, 'replay_identical': True,
                  'time_policy': 'observed-v1', 'market_data': 'synthetic_probes',
                  'human_reviewed': False, 'operational_activation_eligible': False,
                  'model_calls': 0, 'cost_usd': 0, 'results': rows}
    reports = args.data_dir / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    output = reports / f'corpus-{uuid4().hex}.json'
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'report': str(output.resolve()), 'generation_id': generation,
                      'notes': len(imported['notes']), 'direct_hits': sum(r['hit'] is True for r in rows[:6]),
                      'paraphrase_hits': sum(r['hit'] is True for r in rows[6:12])}, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Development-only calibration, then frozen holdout comparison with real embeddings."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..snapshot import Fact, Snapshot
from .context_repository import PostgresContextRepository
from .corpus import Corpus, import_corpus
from .embeddings import EmbeddingService, EmbeddingSpec, OpenAIEmbeddings
from .index import GenerationIndex
from .schemas import digest, stamp
from .selection import SelectionPolicy, query_text
from .store import RagStore
from .vector_evaluation import ComparisonCase, compare
from .vectors import VectorIndex


def calibrate(samples, version):
    """Fixed grid/objective. Input must contain development cases only.

    Scores simulate dense selection on eligible members; final reports use the
    real retrieval path. No hybrid or holdout score selects the policy.
    """
    if not samples or any(s['split'] != 'development' for s in samples):
        raise ValueError('calibration accepts development samples only')
    if not any(s['relevant'] for s in samples) or not any(not s['relevant'] for s in samples):
        raise ValueError('calibration needs positive and negative development cases')
    trials = []
    for threshold in (0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
        for band in (0.0, 0.04, 0.08, 0.12):
            positive_f1, recalls, negatives, extra = [], [], [], 0
            for sample in samples:
                best = min((r['distance'] for r in sample['scores']), default=2)
                selected, docs, hashes, groups = set(), set(), set(), set()
                for path in ('common', 'short'):
                    rows = sorted((r for r in sample['scores'] if path in r['horizons']),
                                  key=lambda r: (r['distance'], r['rowid']))
                    for r in rows:
                        if (r['distance'] > threshold or r['distance'] > best + band or len(selected) >= 2
                                or r['document_id'] in docs or r['text_hash'] in hashes
                                or (r['duplicate_group_id'] and r['duplicate_group_id'] in groups)):
                            continue
                        selected.add(r['chunk_id'])
                        docs.add(r['document_id'])
                        hashes.add(r['text_hash'])
                        groups.add(r['duplicate_group_id'])
                gold = set(sample['relevant'])
                hits = len(selected & gold)
                extra += len(selected - gold)
                if gold:
                    positive_f1.append(2 * hits / (len(selected) + len(gold)))
                    recalls.append(hits / len(gold))
                else:
                    negatives.append(not selected)
            f1 = sum(positive_f1) / len(positive_f1)
            specificity = sum(negatives) / len(negatives)
            trials.append(dict(max_distance=threshold, distance_band=band,
                objective=(f1 + specificity) / 2, positive_f1=f1,
                negative_specificity=specificity, recall=sum(recalls) / len(recalls), unnecessary=extra))
    best = max(trials, key=lambda r: (r['objective'], r['negative_specificity'], -r['unnecessary'],
                                     r['recall'], -r['max_distance'], -r['distance_band']))
    policy = SelectionPolicy(embedding_version=version, max_distance=best['max_distance'],
                             distance_band=best['distance_band'])
    return policy, {'objective': 'mean(positive_macro_f1,negative_specificity)',
                    'calibration_strategy': 'dense', 'trials': trials, 'selected': best}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(dsn, corpus_path, dataset_path, output, specs, budget_nano):
    corpus = Corpus.model_validate_json(corpus_path.read_text(encoding='utf-8'))
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    rows = dataset['cases']
    if (not rows or len({r['id'] for r in rows}) != len(rows)
            or {r['split'] for r in rows} != {'development', 'holdout'}):
        raise ValueError('unique split cases required')
    for r in rows:
        if (r['path'] not in {'common', 'short'} or bool(r['relevant']) == r['expect_empty']
                or len(set(r['relevant'])) != len(r['relevant'])):
            raise ValueError('invalid judgment')
    if (not specs or len({s.model for s in specs}) != len(specs)
            or any(s.provider != 'openai' or s.nano_usd_per_token <= 0 for s in specs)):
        raise ValueError('explicit real API specs and prices required')
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'state.json'
    hashes = {'corpus_hash': digest(corpus.model_dump(mode='json')), 'dataset_hash': digest(dataset),
              'experiment_version': 'focused-evidence-v1'}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if any(state[k] != v for k, v in hashes.items()):
            raise ValueError('frozen inputs changed')
    else:
        state = {**hashes, 'observed_at': datetime.now(timezone.utc).isoformat()}
        write(state_path, state)
    observed = datetime.fromisoformat(state['observed_at'])
    summary = {**state, 'human_reviewed': False, 'budget_nano': budget_nano, 'models': []}
    with RagStore(output / 'archive') as store:
        imported = import_corpus(store, corpus, allow_agent_reviewed=True, observed_at=observed)
        lookup = {r['id']: r['chunk_id'] for r in imported['notes']}
        generation = GenerationIndex(store).publish(observed)
        db, manifest = GenerationIndex(store).open(generation)
        db.close()
        cases = {}
        for r in rows:
            fact = Fact(id='EVAL.PROBE', category='valuation', label=r['label'], value=None,
                        unit='text', as_of=observed.date(), source='agent_authored_evaluation')
            snapshot = Snapshot(snapshot_id='EVAL.' + digest([state, r['id']]), ticker='005930',
                name='평가종목', as_of=observed.date(), created_at=observed,
                provider='synthetic_concept_probe', facts={fact.id: fact})
            cases[r['id']] = ComparisonCase(id=r['id'], snapshot=snapshot, path=r['path'],
                relevant=[lookup[k] for k in r['relevant']], expect_empty=r['expect_empty'])
        summary.update(generation_id=generation, documents=len(manifest['members']), cases=len(rows))
        texts = [m['text'] for m in manifest['members']]
        query_pairs = [query_text(c.snapshot, p) for c in cases.values() for p in (None, SelectionPolicy())]
        upper = sum(s.nano_usd_per_token * (sum(len((s.document_prefix + t).encode()) for t in texts)
                    + sum(len((s.query_prefix + t).encode()) for t in query_pairs)) for s in specs)
        if upper > budget_nano:
            raise ValueError('planned upper bound exceeds budget before calls')
        summary['planned_upper_bound_nano'] = upper
        write(output / 'cases.json', [dict(cases[r['id']].model_dump(mode='json'), split=r['split'],
                                         category=r['category']) for r in rows])
        for spec in specs:
            service = EmbeddingService(dsn, spec, OpenAIEmbeddings())
            index = VectorIndex(service)
            model = {'model': spec.model, 'embedding_version': spec.version_id}
            try:
                index.build(store, generation, daily_budget_nano=budget_nano)
                samples = []
                for r in rows:
                    if r['split'] != 'development':
                        continue
                    c = cases[r['id']]
                    query = query_text(c.snapshot, SelectionPolicy())
                    service.prepare(query, 'query', daily_budget_nano=budget_nano)
                    distances, _ = index.distances(dict(enumerate(manifest['members'], 1)), generation,
                        manifest, query, cutoff=stamp(observed), time_policy='reconstructed-v1')
                    samples.append(dict(case_id=c.id, split='development', relevant=c.relevant,
                        scores=[dict(m, rowid=i, distance=distances[i]) for i, m in enumerate(manifest['members'], 1)]))
                policy, calibration = calibrate(samples, spec.version_id)
                policy_path = output / (spec.model + '-policy.json')
                # Never silently re-tune a completed experiment on a rerun.
                if policy_path.exists() and json.loads(policy_path.read_text()) != policy.model_dump(mode='json'):
                    raise ValueError('frozen policy differs')
                write(policy_path, policy.model_dump(mode='json'))
                write(output / (spec.model + '-calibration.json'), dict(calibration,
                    development_hash=digest(samples), frozen_before_holdout=True))
                model['policy'] = policy.model_dump(mode='json')
                model['reports'] = {}
                # Holdout labels and embeddings have not been used to choose the policy.
                for split in ('development', 'holdout'):
                    group = [cases[r['id']] for r in rows if r['split'] == split]
                    for name, selected_policy in (('legacy', None), ('selective', policy)):
                        for c in group:
                            service.prepare(query_text(c.snapshot, selected_policy), 'query', daily_budget_nano=budget_nano)
                        report = compare(store, index, generation, group,
                            context_repository=PostgresContextRepository(dsn), selection_policy=selected_policy)
                        report.update(split=split, human_reviewed=False, embedding_spec=spec.model_dump(mode='json'))
                        key = split + '-' + name
                        write(output / (spec.model + '-' + key + '.json'), report)
                        model['reports'][key] = report['summary']
                model['status'] = 'completed'
            except Exception:
                model['status'] = 'failed_or_unknown'
                raise
            finally:
                if service.provider.client is not None:
                    service.provider.client.close()
                summary['models'].append(model)
                summary['ledger'] = service.ledger()
                write(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--spec', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-nano', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        specs = [EmbeddingSpec.model_validate_json(p.read_text(encoding='utf-8')) for p in args.spec]
        result = run(os.environ['BULLBEAR_RAG_POSTGRES_DSN'], args.corpus, args.cases, args.output, specs, args.budget_nano)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({'error': 'selection_evaluation_failed', 'inspect': 'private summary and ledger'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

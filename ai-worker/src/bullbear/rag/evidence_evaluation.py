"""Offline regression replay. Uses SQLite BM25 only; no provider or model client."""
import argparse
import json
from pathlib import Path
from ..snapshot import Snapshot
from .evidence import DocumentRequest
from .retrieval import Retriever
from .selection import SelectionPolicy
from .store import RagStore


def evaluate(cases, archive, generation):
    results = []
    with RagStore(archive) as store:
        retriever = Retriever(store, selection_policy=SelectionPolicy())
        for case in cases:
            snap = Snapshot.model_validate(case['snapshot'])
            label = snap.facts['EVAL.PROBE'].label
            context = retriever.retrieve(snap, generation_id=generation, time_policy='reconstructed-v1',
                request=DocumentRequest(question=label, ticker=snap.ticker))
            payload = context.payload
            selected = {i['chunk_id'] for i in payload['items']}
            gold = set(case['relevant'])
            results.append(dict(id=case['id'], split=case['split'], category=case['category'], question=label,
                context_id=context.context_id, mode=payload['evidence']['mode'],
                answerability=payload['answerability'], reasons=payload['evidence']['reasons'],
                status=payload['status'], selected=sorted(selected), relevant=sorted(gold),
                unexpected=bool(case['expect_empty'] and selected),
                recall=len(selected & gold)/len(gold) if gold else None, unnecessary=len(selected-gold)))
    summary = {}
    for split in sorted({r['split'] for r in results}):
        rows = [r for r in results if r['split'] == split]
        positives = [r for r in rows if r['relevant']]
        total = sum(len(r['selected']) for r in rows)
        extra = sum(r['unnecessary'] for r in rows)
        summary[split] = dict(cases=len(rows), unexpected=sum(r['unexpected'] for r in rows),
            recall=sum(r['recall'] for r in positives)/len(positives) if positives else None,
            micro_precision=(total-extra)/total if total else None,
            false_abstentions=sum(not r['selected'] for r in positives), unnecessary=extra,
            failures=sum(r['status'] not in ('empty', 'completed') for r in rows))
    return dict(schema='document-search-regression-v2', mode='documents_only_not_answerability_classification', external_model_calls=0,
        evaluation_scope='reused_cases_not_new_blind_validation', human_reviewed=False,
        summary=summary, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(args.cases.read_text(encoding='utf-8')), args.archive, args.generation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()

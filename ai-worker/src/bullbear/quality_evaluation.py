"""Offline follow-up to diagnostics.review-queue; never calls a model.

Bind annotations to frozen source bytes, report human-only denominators, and
replay the narrow deterministic horizon guard without reinterpreting LLM reviews.
Raw candidates and reviewer prose are never copied to outputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


LABELS = {"candidate_error", "reviewer_false_positive", "both",
          "no_identified_error", "insufficient_evidence"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode())


def bind_cases(arm: Path, queue: list[dict]) -> list[tuple[dict, object]]:
    """Validate diagnostics v1 identities, including complete attempt coverage."""
    report_bytes = (arm / 'report.json').read_bytes()
    events_bytes = (arm / 'events.jsonl').read_bytes()
    source = {'report_sha256': sha(report_bytes), 'events_sha256': sha(events_bytes)}
    events = [json.loads(line) for line in events_bytes.splitlines() if line.strip()]
    attempts = {i: event for i, event in enumerate(events, 1)
                if event.get('type') in ('single_attempt', 'statement_attempt')}
    if not isinstance(queue, list):
        raise ValueError('Expected diagnostic queue')
    seen, bound = set(), []
    for row in queue:
        index = row['event_record']
        if type(index) is not int or index not in attempts or index in seen:
            raise ValueError('Invalid or duplicate event identity')
        seen.add(index)
        event = attempts[index]
        candidate = event.get('candidate', event.get('statement', event.get('raw')))
        identity = {**source, 'event_record': index, 'candidate_sha256': canonical_hash(candidate)}
        if any(row.get(k) != v for k, v in identity.items()) or row['case_id'] != canonical_hash(identity):
            raise ValueError('Stale source or modified case identity')
        passed = event.get('passed') if event['type'] == 'single_attempt' else event.get('verification', {}).get('passed')
        if type(passed) is not bool or type(row.get('automatic_passed')) is not bool or row['automatic_passed'] != passed:
            raise ValueError('Modified automatic result')
        bound.append((row, candidate))
    if seen != set(attempts):
        raise ValueError('Queue omits attempts; accepted attempts must also be reviewed')
    return bound


def evaluate(arm: Path, queue: list[dict], annotations: list[dict], *, snapshot: Path):
    bound = bind_cases(arm, queue)
    snapshot_bytes = snapshot.read_bytes()
    snapshot_hash = sha(snapshot_bytes)
    frozen = json.loads(snapshot_bytes)
    report = json.loads((arm / 'report.json').read_bytes())
    if (not frozen.get('snapshot_id') or report.get('snapshot_id') != frozen['snapshot_id']
            or report.get('snapshot_sha256') != canonical_hash(frozen)):
        raise ValueError('Snapshot does not match benchmark report')
    ids = {row['case_id'] for row, _ in bound}
    if not isinstance(annotations, list):
        raise ValueError('Expected annotation list')
    labelled = {}
    statuses = Counter()
    for annotation in annotations:
        key = annotation['case_id']
        if key not in ids or key in labelled:
            raise ValueError('Unknown or duplicate annotation')
        if annotation.get('snapshot_sha256') != snapshot_hash:
            raise ValueError('Stale annotation snapshot')
        status = annotation.get('status')
        if status not in ('unreviewed', 'proposed', 'human_reviewed'):
            raise ValueError('Invalid review status')
        label = annotation.get('label')
        if label is not None and label not in LABELS:
            raise ValueError('Invalid label')
        if status == 'human_reviewed':
            # This is an explicit human attestation, not machine authentication.
            if (label is None or annotation.get('human_attested') is not True
                    or not all(isinstance(annotation.get(k), str) and annotation[k].strip()
                               for k in ('reviewer', 'rationale'))
                    or set(annotation.get('evidence_checked', [])) != {'candidate', 'facts', 'history', 'review'}):
                raise ValueError('Human review requires attribution, rationale and evidence checks')
        statuses[status] += 1
        labelled[key] = annotation

    counts, cells = Counter(), Counter()
    cases, template = [], []
    # Lazy import keeps input validation and report aggregation free of providers.
    from .semantic import horizon_issues
    for row, candidate in bound:
        key = row['case_id']
        annotation = labelled.get(key)
        status = annotation['status'] if annotation else 'unreviewed'
        if annotation is None:
            statuses[status] += 1
        label = annotation.get('label') if annotation else None
        if status == 'human_reviewed':
            counts[label] += 1
            if label != 'insufficient_evidence':
                erroneous = label in ('candidate_error', 'both')
                cells[('accepted' if row['automatic_passed'] else 'rejected') +
                      ('_candidate_error' if erroneous else '_no_identified_error')] += 1
        # Replay only this guard; no empty result is promoted to semantic pass.
        text = candidate.get('claim', candidate.get('reasoning')) if isinstance(candidate, dict) else None
        replay = [i.code for i in horizon_issues(text)] if isinstance(text, str) else None
        cases.append({'case_id': key, 'event_record': row['event_record'],
                      'automatic_passed': row['automatic_passed'], 'status': status,
                      'human_label': label if status == 'human_reviewed' else None,
                      'proposed_label': label if status == 'proposed' else None,
                      'horizon_guard_codes': replay})
        template.append({'case_id': key, 'snapshot_sha256': snapshot_hash,
                         'status': 'unreviewed', 'label': None, 'reviewer': None,
                         'rationale': None, 'human_attested': False, 'evidence_checked': []})
    conclusive = sum(cells.values())
    rejected = sum(v for k, v in cells.items() if k.startswith('rejected_'))
    summary = {
        'schema_version': 'worker-quality-v1', 'snapshot_sha256': snapshot_hash,
        'queue_sha256': canonical_hash(queue), 'annotations_sha256': canonical_hash(annotations),
        'implementation_sha256': {name: sha(Path(__file__).with_name(name).read_bytes())
                                  for name in ('quality_evaluation.py', 'semantic.py')},
        'cases': len(bound), 'review_status_counts': dict(sorted(statuses.items())),
        'human_label_counts': dict(sorted(counts.items())), 'confusion_counts': dict(sorted(cells.items())),
        'conclusive_human_cases': conclusive, 'conclusive_rejected_cases': rejected,
        'candidate_error_fraction': (counts['candidate_error'] + counts['both']) / conclusive if conclusive else None,
        'false_rejection_fraction': cells['rejected_no_identified_error'] / rejected if rejected else None,
        'limitations': ['human_attestation_is_not_authenticated', 'proposals_are_not_ground_truth',
                       'quote_grounding_is_not_correctness', 'attempts_are_not_independent_samples',
                       'horizon_replay_is_not_semantic_review', 'no_claude_quality_or_profitability_estimate'],
        'network_calls': 0,
    }
    return summary, cases, template


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arm', type=Path)
    parser.add_argument('--queue', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        queue = json.loads(args.queue.read_text(encoding='utf-8'))
        annotations = json.loads(args.annotations.read_text(encoding='utf-8')) if args.annotations else []
        summary, cases, template = evaluate(args.arm, queue, annotations, snapshot=args.snapshot)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, value in [('summary', summary), ('cases', cases), ('annotation-template', template)]:
            (args.output / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f'Offline quality evaluation failed: {type(exc).__name__}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Offline benchmark diagnostics and an unlabelled human review queue.

Reads one benchmark arm's report.json/events.jsonl. No provider imports, dotenv,
network requests, model calls, or changes to the original experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate_hash(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode())


def code(value):
    # Never echo free-form vendor errors or candidate prose in aggregate output.
    return value if isinstance(value, str) and re.fullmatch('[a-z][a-z0-9_]{0,63}', value) else 'unknown'


def analyse(directory: Path) -> tuple[dict, list[dict]]:
    raw_report = (directory / 'report.json').read_bytes()
    raw_events = (directory / 'events.jsonl').read_bytes()
    report = json.loads(raw_report)
    events = [json.loads(line) for line in raw_events.splitlines() if line.strip()]
    if not isinstance(report, dict) or report.get('status') not in ('completed', 'failed'):
        raise ValueError('Expected a finished benchmark arm report')
    if not all(isinstance(event, dict) for event in events):
        raise ValueError('Invalid event record')
    reviews = report.get('semantic_reviews', {})
    if not isinstance(reviews, dict) or not all(isinstance(v, list) for v in reviews.values()):
        raise ValueError('Invalid semantic reviews')
    source = {'report_sha256': digest(raw_report), 'events_sha256': digest(raw_events)}
    errors, warnings, queue = Counter(), Counter(), []
    passed = rejected = 0
    for line, event in enumerate(events, 1):
        if event.get('type') not in ('single_attempt', 'statement_attempt'):
            continue
        verification = event.get('verification', {})
        success = event.get('passed') if event['type'] == 'single_attempt' else verification.get('passed')
        if not isinstance(success, bool):
            raise ValueError('Attempt missing explicit pass/fail')
        passed += success
        rejected += not success
        # single_attempt.issues already includes verification.issues; do not count twice.
        issues = event.get('issues', []) if event['type'] == 'single_attempt' else verification.get('issues', [])
        for issue in issues:
            if isinstance(issue, str):
                errors[code(issue)] += 1
            elif issue.get('severity') == 'error':
                errors[code(issue.get('code'))] += 1
            elif issue.get('severity') == 'warning':
                warnings[code(issue.get('code'))] += 1
        candidate = event.get('candidate', event.get('statement', event.get('raw')))
        matches = []
        for role, records in reviews.items():
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    raise ValueError('Invalid review record')
                if candidate is not None and record.get('candidate') == candidate:
                    matches.append({'role': code(role), 'index': index,
                                    'quote_grounded': record.get('grounded'),
                                    'issues_count': len(record.get('review', {}).get('issues', []))})
        identity = {**source, 'event_record': line, 'candidate_sha256': candidate_hash(candidate)}
        queue.append({
            'case_id': candidate_hash(identity), **identity,
            'automatic_passed': success, 'semantic_reviews': matches,
            'semantic_review_observed': bool(matches),
            # No inferred truth labels: include accepted candidates to detect misses too.
            'human_label': None, 'human_rationale': None, 'reviewer': None,
            'allowed_labels': ['candidate_error', 'reviewer_false_positive', 'both',
                               'no_identified_error', 'insufficient_evidence'],
        })
    requested, received = report.get('requests_attempted'), report.get('responses_received')
    failed_calls = requested - received if isinstance(requested, int) and isinstance(received, int) else None
    if failed_calls is not None and failed_calls < 0:
        raise ValueError('Response count exceeds request count')
    summary = {
        'schema_version': 'worker-offline-diagnostics-v1', 'source': source,
        'status': report['status'], 'attempts': passed + rejected,
        'accepted_attempts': passed, 'rejected_attempts': rejected,
        'error_findings_by_code': dict(sorted(errors.items())),
        'warning_findings_by_code': dict(sorted(warnings.items())),
        'attempts_without_semantic_review': sum(not row['semantic_review_observed'] for row in queue),
        'review_records': sum(len(rows) for rows in reviews.values()),
        'requests_without_recorded_response': failed_calls,
        'verification_rejections_observed': bool(rejected),
        'failure_cause': 'not_inferred_from_rejections' if report['status'] == 'failed' else None,
        'human_labelled_cases': 0, 'candidate_error_rate': None, 'reviewer_false_positive_rate': None,
        'network_calls': 0,
        'limitations': ['automatic_findings_are_not_ground_truth',
                       'accepted_candidates_also_require_review',
                       'repeated_attempts_are_not_independent_samples',
                       'unmatched_or_missing_reviews_do_not_prove_a_gate_was_skipped',
                       'historical_provider_results_do_not_measure_claude_quality'],
    }
    return summary, queue


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing output is never replaced')
    args = parser.parse_args(argv)
    try:
        summary, queue = analyse(args.directory)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.output / 'review-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Avoid exception strings that may contain raw source text or private paths.
        parser.exit(2, f'Offline diagnostics failed: {type(exc).__name__}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

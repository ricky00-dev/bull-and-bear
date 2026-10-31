import json
from pathlib import Path
import socket

import pytest

from bullbear.quality_evaluation import bind_cases, canonical_hash, evaluate, main, sha
from bullbear.semantic import horizon_issues


FIXTURES = Path(__file__).parent / 'fixtures' / 'quality'


@pytest.mark.parametrize('case', json.loads((FIXTURES / 'horizon-v1.json').read_text(encoding='utf-8')),
                         ids=lambda case: case['id'])
def test_horizon_regression(case):
    assert [i.code for i in horizon_issues(case['text'])] == case['expected_codes']


@pytest.fixture
def arm(tmp_path):
    folder = tmp_path / 'arm'
    folder.mkdir()
    events = [
        {'type': 'single_attempt', 'candidate': {'claim': '7 거래일 코스피 대비 private prose'}, 'passed': False},
        {'type': 'statement_accepted'},
        {'type': 'statement_attempt', 'statement': {'claim': '장기 절대수익 private prose'}, 'verification': {'passed': True}},
        {'type': 'single_attempt', 'raw': None, 'passed': False},
    ]
    (folder / 'events.jsonl').write_text('\n\n'.join(json.dumps(e) for e in events))
    snapshot = tmp_path / 'snapshot.json'
    frozen = {'snapshot_id': 'synthetic', 'facts': {}, 'note': 'private prose'}
    snapshot.write_text(json.dumps(frozen))
    (folder / 'report.json').write_text(json.dumps({'status': 'failed', 'snapshot_id': 'synthetic',
                                                 'snapshot_sha256': canonical_hash(frozen)}))
    source = {f'{name}_sha256': sha((folder / filename).read_bytes())
              for name, filename in [('report', 'report.json'), ('events', 'events.jsonl')]}
    queue = []
    for index in [1, 3, 4]:
        e = events[index - 1]
        candidate = e.get('candidate', e.get('statement', e.get('raw')))
        identity = {**source, 'event_record': index, 'candidate_sha256': canonical_hash(candidate)}
        queue.append({'case_id': canonical_hash(identity), **identity,
                      'automatic_passed': e.get('passed', e.get('verification', {}).get('passed'))})
    return folder, queue, snapshot


def annotation(row, snapshot, label, status='human_reviewed'):
    return {'case_id': row['case_id'], 'snapshot_sha256': sha(snapshot.read_bytes()),
            'status': status, 'label': label, 'human_attested': True,
            'reviewer': 'fixture reviewer', 'rationale': 'private prose',
            'evidence_checked': ['candidate', 'facts', 'history', 'review']}


def test_unreviewed_remains_unknown_and_replay_is_not_acceptance(arm, monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Network forbidden during offline evaluation')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    folder, queue, snapshot = arm
    summary, cases, template = evaluate(folder, queue, [], snapshot=snapshot)
    assert summary['candidate_error_fraction'] is None
    assert summary['false_rejection_fraction'] is None
    assert summary['review_status_counts'] == {'unreviewed': 3}
    assert cases[0]['horizon_guard_codes'] == [] and cases[0]['automatic_passed'] is False
    assert cases[1]['horizon_guard_codes'] == ['horizon_mismatch'] and cases[1]['automatic_passed'] is True
    assert cases[2]['horizon_guard_codes'] is None
    assert 'private prose' not in json.dumps([summary, cases, template])
    assert evaluate(folder, queue, template, snapshot=snapshot)[0]['candidate_error_fraction'] is None


def test_proposals_and_insufficient_evidence_excluded_from_denominators(arm):
    folder, queue, snapshot = arm
    annotations = [annotation(queue[0], snapshot, 'reviewer_false_positive', 'proposed'),
                   annotation(queue[1], snapshot, 'candidate_error'),
                   annotation(queue[2], snapshot, 'insufficient_evidence')]
    summary, cases, _ = evaluate(folder, queue, annotations, snapshot=snapshot)
    assert summary['conclusive_human_cases'] == 1
    assert summary['candidate_error_fraction'] == 1
    assert summary['false_rejection_fraction'] is None
    assert cases[0]['human_label'] is None
    assert summary['confusion_counts'] == {'accepted_candidate_error': 1}


def test_both_is_not_a_false_rejection(arm):
    folder, queue, snapshot = arm
    annotations = [annotation(queue[0], snapshot, 'both'),
                   annotation(queue[2], snapshot, 'reviewer_false_positive')]
    summary, _, _ = evaluate(folder, queue, annotations, snapshot=snapshot)
    assert summary['candidate_error_fraction'] == .5
    assert summary['false_rejection_fraction'] == .5
    assert summary['conclusive_rejected_cases'] == 2


def test_wrong_snapshot_and_duplicate_annotations_rejected(arm):
    folder, queue, snapshot = arm
    row = annotation(queue[0], snapshot, 'both')
    with pytest.raises(ValueError, match='duplicate'):
        evaluate(folder, queue, [row, row], snapshot=snapshot)
    snapshot.write_text('{"snapshot_id":"synthetic","facts":{"changed":1}}')
    with pytest.raises(ValueError, match='Snapshot'):
        evaluate(folder, queue, [], snapshot=snapshot)


@pytest.mark.parametrize('mutation', ['source', 'candidate_hash', 'case_id', 'passed', 'missing', 'duplicate'])
def test_modified_or_incomplete_queue_rejected(arm, mutation):
    folder, queue, snapshot = arm
    if mutation == 'source':
        with (folder / 'report.json').open('a') as f:
            f.write('\n')
    elif mutation in ('candidate_hash', 'case_id'):
        queue[0]['candidate_sha256' if mutation == 'candidate_hash' else 'case_id'] = 'changed'
    elif mutation == 'passed':
        queue[0]['automatic_passed'] = True
    elif mutation == 'missing':
        queue.pop()
    else:
        queue.append(queue[0])
    with pytest.raises(ValueError):
        bind_cases(folder, queue)


@pytest.mark.parametrize('field,value', [('snapshot_sha256', 'stale'), ('case_id', 'unknown'),
    ('status', 'model_reviewed'), ('label', 'pass'), ('human_attested', False),
    ('rationale', ''), ('reviewer', None), ('evidence_checked', ['candidate'])])
def test_invalid_human_review_rejected(arm, field, value):
    folder, queue, snapshot = arm
    row = annotation(queue[0], snapshot, 'both')
    row[field] = value
    with pytest.raises(ValueError):
        evaluate(folder, queue, [row], snapshot=snapshot)


def test_cli_is_non_destructive_and_sanitizes_errors(arm, tmp_path, capsys):
    folder, queue, snapshot = arm
    queue_file = tmp_path / 'queue.json'
    queue_file.write_text(json.dumps(queue))
    output = tmp_path / 'out'
    args = [str(folder), '--queue', str(queue_file), '--snapshot', str(snapshot), '--output', str(output)]
    before = {p: p.read_bytes() for p in [*folder.iterdir(), snapshot, queue_file]}
    assert main(args) == 0
    saved = (output / 'summary.json').read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert (output / 'summary.json').read_bytes() == saved
    assert all(p.read_bytes() == content for p, content in before.items())
    assert 'private prose' not in capsys.readouterr().out

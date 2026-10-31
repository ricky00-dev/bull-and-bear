import json

import pytest

from bullbear.diagnostics import analyse, main


def write_arm(path, events, reviews=None, **fields):
    path.mkdir()
    (path / 'report.json').write_text(json.dumps({'status': 'failed', 'semantic_reviews': reviews or {},
        'requests_attempted': 2, 'responses_received': 2, **fields}), encoding='utf-8')
    (path / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
    return path


def test_warning_not_counted_as_error_and_combined_single_issues_not_duplicated(tmp_path):
    issue = {'severity': 'error', 'code': 'money_unit', 'message': 'private prose'}
    arm = write_arm(tmp_path / 'arm', [{'type': 'single_attempt', 'passed': False,
        'candidate': {'claim': 'private prose'}, 'verification': {'issues': [issue]},
        'issues': [issue, {'severity': 'warning', 'code': 'unbacked_number'}]}])
    summary, queue = analyse(arm)
    assert summary['error_findings_by_code'] == {'money_unit': 1}
    assert summary['warning_findings_by_code'] == {'unbacked_number': 1}
    assert summary['reviewer_false_positive_rate'] is None
    assert queue[0]['human_label'] is None
    assert 'private prose' not in json.dumps([summary, queue])


def test_passed_cases_and_ungrounded_reviewer_record_remain_unlabelled(tmp_path):
    candidate = {'claim': 'conditional prediction'}
    events = [{'type': 'statement_attempt', 'statement': candidate,
               'verification': {'passed': True, 'issues': []}},
              {'type': 'statement_accepted', 'statement': candidate}]
    arm = write_arm(tmp_path / 'arm', events, {'debater': [{'candidate': candidate,
                    'grounded': False, 'review': {'issues': [{'code': 'concept_error'}]}}]})
    summary, queue = analyse(arm)
    assert summary['attempts'] == 1
    assert queue[0]['semantic_reviews'][0]['quote_grounded'] is False
    assert queue[0]['human_label'] is None
    assert analyse(arm) == (summary, queue)


def test_network_failure_without_attempt_is_not_verification_failure(tmp_path):
    arm = write_arm(tmp_path / 'arm', [], requests_attempted=1, responses_received=0)
    summary, queue = analyse(arm)
    assert not summary['verification_rejections_observed']
    assert summary['requests_without_recorded_response'] == 1
    assert not queue


def test_source_change_changes_case_identity_and_output_cannot_be_overwritten(tmp_path):
    arm = write_arm(tmp_path / 'arm', [{'type': 'single_attempt', 'passed': False,
                                      'issues': ['invalid_schema'], 'raw': {}}])
    before = {p.name: p.read_bytes() for p in arm.iterdir()}
    output = tmp_path / 'output'
    assert main([str(arm), '--output', str(output)]) == 0
    saved = (output / 'review-queue.json').read_bytes()
    with pytest.raises(SystemExit) as exc:
        main([str(arm), '--output', str(output)])
    assert exc.value.code == 2
    assert (output / 'review-queue.json').read_bytes() == saved
    assert {p.name: p.read_bytes() for p in arm.iterdir()} == before
    old_id = analyse(arm)[1][0]['case_id']
    with (arm / 'report.json').open('a') as f:
        f.write('\n')
    assert analyse(arm)[1][0]['case_id'] != old_id


def test_truncated_event_log_is_rejected_before_output_creation(tmp_path):
    arm = write_arm(tmp_path / 'arm', [])
    (arm / 'events.jsonl').write_text('{broken', encoding='utf-8')
    with pytest.raises(SystemExit):
        main([str(arm), '--output', str(tmp_path / 'out')])
    assert not (tmp_path / 'out').exists()


def test_missing_usage_observations_are_unknown_not_zero(tmp_path):
    arm = write_arm(tmp_path / 'arm', [], requests_attempted=None, responses_received=None)
    assert analyse(arm)[0]['requests_without_recorded_response'] is None

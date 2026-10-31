"""Opt-in PR23/24 end-to-end pairing against disposable real Spring and worker."""
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import UUID

import httpx
import pytest

from .test_spring_usage_recovery import query, wait_for

CONFIG = os.getenv('BULLBEAR_TEST_RECOVERY_CONFIG')
pytestmark = pytest.mark.skipif(not CONFIG, reason='requires disposable Spring fixture')


def test_spring_single_uses_same_snapshot_and_report_pairs():
    config = json.loads(Path(CONFIG).read_text(encoding='utf-8-sig'))
    Path(os.environ['BULLBEAR_TEST_CLOCK_FILE']).write_text('2026-10-16T18:00:00+09:00', encoding='utf-8')
    with httpx.Client(base_url=os.environ['BULLBEAR_TEST_API_URL'], timeout=15) as client:
        client.headers['Authorization'] = 'Bearer ' + client.post('/api/auth/guest').json()['token']
        response = client.post('/api/debates', json={'ticker': '005930'})
        response.raise_for_status()
        debate_id = str(UUID(response.json()['id']))
        wait_for(lambda: client.get(f'/api/debates/{debate_id}').json()['status'] == 'COMPLETED')
        result = subprocess.run([*config['sql_command'], '--schedule-debate'], input=debate_id,
                                capture_output=True, text=True, encoding='utf-8', timeout=20, check=True)
        assert json.loads(result.stdout) is True
        def single():
            return query(config, f"SELECT row_to_json(s) FROM single_verdicts s WHERE debate_id='{debate_id}' AND status='COMPLETED' UNION ALL SELECT NULL LIMIT 1")
        row = wait_for(single, timeout=100)
        debate = query(config, f"SELECT row_to_json(d) FROM debates d WHERE id='{debate_id}'")
        with httpx.Client(base_url=config['worker_url'], headers={'X-Worker-Token': 'integration-test-token'}) as worker:
            detail = worker.get('/debates/' + row['worker_id']).json()
            assert row['worker_id'] != debate['worker_debate_id']
            assert detail['snapshot_id'] == debate['snapshot_id']
            assert detail['verdict']['scores'] is None and detail['stats'] is None
            assert detail['statements'] == []
            replay = worker.post('/debates', json={'ticker': '005930', 'mode': 'single',
                'snapshot_id': debate['snapshot_id'], 'request_id': 'single-integration-reuse'}).json()
            assert replay['reused'] and replay['debate_id'] == row['worker_id']
        Path(os.environ['BULLBEAR_TEST_CLOCK_FILE']).write_text('2026-10-27T18:00:00+09:00', encoding='utf-8')
        def report_ready():
            response = client.get('/api/report?scope=all')
            response.raise_for_status()
            report = response.json()
            return report if all(h['single']['n'] >= 1 for h in report['horizons']) else None
        report = wait_for(report_ready)
        assert {h['days'] for h in report['horizons']} == {3, 7}
        for horizon in report['horizons']:
            assert horizon['debatePaired']['n'] == horizon['single']['n']
        time.sleep(1.2)
        assert single()['attempts'] == row['attempts'] == 1

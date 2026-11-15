"""Opt-in real Spring/Postgres checks against the disposable launcher fixture."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import UUID

import httpx
import pytest

CONFIG = os.getenv('BULLBEAR_TEST_RECOVERY_CONFIG')
pytestmark = pytest.mark.skipif(not CONFIG, reason='requires disposable Spring recovery fixture')


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    pytest.fail('Fixture condition did not become ready')


def query(config, sql):
    result = subprocess.run(config['sql_command'], input=sql, capture_output=True, text=True,
                            encoding='utf-8', check=True, timeout=20)
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize('ticker,crash', [('035420', False), ('035720', True)])
def test_unknown_usage_stays_null_and_retains_estimate_in_postgres(ticker, crash):
    config = json.loads(Path(CONFIG).read_text(encoding='utf-8-sig'))
    data = Path(config['worker_data'])
    Path(os.environ['BULLBEAR_TEST_CLOCK_FILE']).write_text('2026-10-16T18:00:00+09:00', encoding='utf-8')
    restarted = None
    with httpx.Client(base_url=os.environ['BULLBEAR_TEST_API_URL'], timeout=15) as c:
        guest = c.post('/api/auth/guest')
        guest.raise_for_status()
        c.headers['Authorization'] = 'Bearer ' + guest.json()['token']
        created = c.post('/api/debates', json={'ticker': ticker})
        created.raise_for_status()
        debate_id = str(UUID(created.json()['id']))
        worker_id = query(config, f"SELECT to_json(worker_debate_id) FROM debates WHERE id='{debate_id}'")
        manifest_path = data / 'audits' / worker_id / 'manifest.json'
        def observed():
            if not manifest_path.exists():
                return False
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            return bool(manifest['llm_calls']) and any(event['type'] == 'turn_started' for event in manifest['events'])
        wait_for(observed)
        before = manifest_path.read_bytes()
        try:
            if crash:
                # The fixture itself exits after persisting a synthetic pending call.
                # No production control endpoint or process-kill command is used.
                (data / 'crash-trigger').touch()
                def stopped():
                    try:
                        httpx.get(config['worker_url'] + '/health', timeout=.2)
                    except httpx.HTTPError:
                        return True
                    return False
                wait_for(stopped)
                with (data.parent / 'restarted-worker.log').open('wb') as log:
                    restarted = subprocess.Popen(config['restart_command'], stdout=log, stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                def ready():
                    try:
                        return httpx.get(config['worker_url'] + '/health', timeout=.2).status_code == 200
                    except httpx.HTTPError:
                        return False
                wait_for(ready)
            wait_for(lambda: c.get(f'/api/debates/{debate_id}').json()['status'] == 'FAILED')
            with httpx.Client(base_url=config['worker_url'], headers={'X-Worker-Token': 'integration-test-token'}) as worker:
                detail = worker.get(f'/debates/{worker_id}').json()
                assert detail['status'] == 'failed' and 'usage' not in detail
                replay = worker.get(f'/debates/{worker_id}/events').text
                assert replay.count('event: debate_failed') == 1
                assert 'synthetic uncertain usage' not in replay
            result = query(config, f"""SELECT json_build_object(
                'cost_unknown', cost_usd IS NULL, 'input_unknown', input_tokens IS NULL,
                'output_unknown', output_tokens IS NULL, 'estimated', coalesce(cost_usd, 0.15),
                'failures', (SELECT count(*) FROM debate_events WHERE debate_id=d.id AND type='debate_failed'),
                'usage_present', (SELECT bool_or(payload ? 'usage') FROM debate_events
                                   WHERE debate_id=d.id AND type='debate_failed'))
                FROM debates d WHERE id='{debate_id}'""")
            assert result == {'cost_unknown': True, 'input_unknown': True, 'output_unknown': True,
                              'estimated': .15, 'failures': 1, 'usage_present': False}
            stream = c.get(f'/api/debates/{debate_id}/stream').text
            assert 'debate_failed' in stream and 'decisive_evidence' not in stream
            assert c.get(f'/api/debates/{debate_id}/reveal').status_code == 403
            manifest = json.loads(manifest_path.read_bytes())
            assert manifest['usage']['calls'][0]['input_tokens'] == 123
            if crash:
                assert manifest_path.read_bytes() == before
                with sqlite3.connect(data / 'http' / 'worker.sqlite3') as db:
                    recovered = json.loads(db.execute('SELECT data FROM recoveries WHERE debate_id=?', (worker_id,)).fetchone()[0])
                assert recovered['usage_complete'] is False
                assert recovered['known_usage'] == manifest['usage']
                assert recovered['unfinished_call_ids'] == [1]
            else:
                assert manifest['usage_complete'] is False
        finally:
            if restarted is not None:
                restarted.terminate()
                try:
                    restarted.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    restarted.kill()
                    restarted.wait(timeout=10)

"""Opt-in HTTP integration against Spring + PostgreSQL + tests.http_fixture.

BULLBEAR_TEST_API_URL=http://127.0.0.1:18080 uv run pytest tests/test_spring_integration.py
"""
import os
import time
from pathlib import Path

import httpx
import pytest

API = os.getenv('BULLBEAR_TEST_API_URL')
pytestmark = pytest.mark.skipif(not API, reason='requires running Spring + PostgreSQL + HTTP fixture worker')


@pytest.mark.parametrize('ticker', ['005930', '000660'])
def test_search_debate_sse_seal_reveal_and_scoring_reservation(ticker):
    clock_file = os.getenv('BULLBEAR_TEST_CLOCK_FILE')
    if clock_file:
        Path(clock_file).write_text('2026-10-16T18:00:00+09:00', encoding='utf-8')
    with httpx.Client(base_url=API, timeout=15) as c:
        guest = c.post('/api/auth/guest')
        guest.raise_for_status()
        c.headers['Authorization'] = 'Bearer ' + guest.json()['token']
        search = c.get('/api/stocks/search', params={'q': 'ㅅㅅㅈㅈ'})
        search.raise_for_status()
        assert search.json()['items'][0]['ticker'] == '005930'
        quote = c.get('/api/stocks/' + ticker)
        quote.raise_for_status()
        created = c.post('/api/debates', json={'ticker': ticker})
        created.raise_for_status()
        debate_id = created.json()['id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail = c.get(f'/api/debates/{debate_id}').json()
            if detail['status'] == 'COMPLETED':
                break
            assert detail['status'] != 'FAILED', detail
            time.sleep(0.1)
        assert detail['status'] == 'COMPLETED', detail
        assert detail['tradeDate'] == '2026-10-16' and detail['basePrice'] == 399
        assert 'verdict' not in detail
        assert c.get(f'/api/debates/{debate_id}/reveal').status_code == 403
        stream = c.get(f'/api/debates/{debate_id}/stream')
        stream.raise_for_status()
        assert 'debate_sealed' in stream.text
        assert 'debate_completed' not in stream.text and 'decisive_evidence' not in stream.text
        assert 'PRIVATE' not in stream.text
        judgment = c.post(f'/api/debates/{debate_id}/judgment', json={
            'decision': 'HOLD', 'confidence': 50, 'evidencePicks': ['PX.CLOSE'], 'memo': 'HTTP integration'})
        judgment.raise_for_status()
        reveal = c.get(f'/api/debates/{debate_id}/reveal')
        reveal.raise_for_status()
        assert reveal.json()['verdict']['decision'] == 'HOLD'
        assert set(reveal.json()['verdict']['scores']) == {'bull', 'bear'}
        judgments = c.get('/api/me/judgments')
        judgments.raise_for_status()
        assert len(judgments.json()['items']) == 1
        assert {s['horizonDays'] for s in judgments.json()['items'][0]['scores']} == {3, 7}
        reused = c.post('/api/debates', json={'ticker': ticker})
        reused.raise_for_status()
        assert reused.json()['id'] == debate_id and reused.json()['reused']
        if clock_file:
            Path(clock_file).write_text('2026-10-21T18:00:00+09:00', encoding='utf-8')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                scores = c.get('/api/me/judgments').json()['items'][0]['scores']
                by_horizon = {s['horizonDays']: s for s in scores}
                if by_horizon[3]['status'] == 'SCORED':
                    break
                time.sleep(0.2)
            assert by_horizon[3]['status'] == 'SCORED'
            assert by_horizon[7]['status'] == 'PENDING'
            # Advance the fixture market clock, not system time; Spring's actual
            # scorer polls via a test-only cron override supplied by the launcher.
            Path(clock_file).write_text('2026-10-28T18:00:00+09:00', encoding='utf-8')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                scores = c.get('/api/me/judgments').json()['items'][0]['scores']
                if all(s['status'] == 'SCORED' for s in scores):
                    break
                time.sleep(0.2)
            assert all(s['status'] == 'SCORED' for s in scores), scores
            by_horizon = {s['horizonDays']: s for s in scores}
            assert by_horizon[3]['scoredTradeDate'] == '2026-10-21'
            assert by_horizon[7]['scoredTradeDate'] == '2026-10-27'
            for horizon, row in by_horizon.items():
                expected = ((399 + 5*horizon)/399 - 1)*100 - ((1399 + 5*horizon)/1399 - 1)*100
                assert float(row['excessReturn']) == pytest.approx(expected, abs=0.001)
            stats = c.get('/api/me/stats').json()
            assert stats['scored'] == 1  # main score is seven trading days

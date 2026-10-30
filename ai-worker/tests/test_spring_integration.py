"""Opt-in HTTP integration against Spring + PostgreSQL + tests.http_fixture.

BULLBEAR_TEST_API_URL=http://127.0.0.1:18080 uv run pytest tests/test_spring_integration.py
"""
import os
import time
from decimal import Decimal, ROUND_HALF_UP

import httpx
import pytest

API = os.getenv('BULLBEAR_TEST_API_URL')
pytestmark = pytest.mark.skipif(not API, reason='requires running Spring + PostgreSQL + HTTP fixture worker')


@pytest.mark.parametrize('ticker', ['005930', '000660'])
def test_search_debate_sse_seal_reveal_and_scoring_reservation(ticker):
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
        if os.getenv('BULLBEAR_TEST_EXPECT_SCORED') == '1':
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                graded = c.get('/api/me/judgments')
                graded.raise_for_status()
                scores = graded.json()['items'][0]['scores']
                if all(s['status'] == 'SCORED' for s in scores):
                    break
                time.sleep(0.1)
            assert all(s['status'] == 'SCORED' for s in scores), scores
            for score in scores:
                horizon = score['horizonDays']
                assert score['scoredTradeDate'] == {3: '2026-10-21', 7: '2026-10-27'}[horizon]
                stock = (Decimal(horizon) / Decimal(399) * 100).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                index = (Decimal(horizon) / Decimal(1399) * 100).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                assert Decimal(str(score['excessReturn'])) == stock - index
                assert score['userHit'] is True and score['moderatorHit'] is True
        reused = c.post('/api/debates', json={'ticker': ticker})
        reused.raise_for_status()
        assert reused.json()['id'] == debate_id and reused.json()['reused']

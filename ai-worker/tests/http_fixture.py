"""Loopback-only integration server using real HTTP/pipeline and deterministic providers.

uv run python -m tests.http_fixture --port 18000 --data <temporary directory>
No production switch enables these fixtures.
"""
import argparse
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from bullbear.config import load_settings
from bullbear.debate import Debate, verification_stats
from bullbear.events import EventLog
from bullbear.server.app import create_app
from bullbear.server.market import Market
from .fakes import AS_OF, NOW, FakeNews, FakeSource, ScriptedDebater, ScriptedModerator, statement


class TestRunner:
    __test__ = False

    def __init__(self, settings, *, gate=None, invalid=False, extra=False):
        self.settings, self.gate, self.invalid, self.extra = settings, gate, invalid, extra

    def usage(self):
        return {'calls': [{'model': 'test-model', 'input_tokens': 100, 'output_tokens': 20,
                           'cache_read_input_tokens': 10, 'cache_creation_input_tokens': 5}]}

    def run(self, snapshot, debate_id, max_extra_rounds, emit):
        if self.gate:
            if not self.gate.wait(10):
                raise TimeoutError('test gate')
        emit('token', {'text': 'PRIVATE RAW TOKEN'})
        emit('moderator_evaluated', {'verdict': 'PRIVATE VERDICT'})
        emit('tool_call', {'side': 'bull', 'name': 'get_price'})
        good = statement(('E1', 'PX.CLOSE', -1 if self.invalid else snapshot.facts['PX.CLOSE'].value))
        bad = statement(('E1', 'PX.CLOSE', -1))
        result = Debate(snapshot, ScriptedDebater(good, bad_first=bad),
                        ScriptedModerator(['extra_round', 'verdict'] if self.extra else ['verdict']),
                        EventLog(self.settings.debate_dir / f'{debate_id}.jsonl'),
                        debate_id=debate_id, max_extra_rounds=max_extra_rounds, on_event=emit).run()
        v = result.verdict.model_dump(mode='json')
        v['scores'] = {side: v.pop(side) for side in ('bull', 'bear')}
        v.pop('action')
        v.pop('extra_question')
        return {'debate_id': debate_id, 'verdict': v, 'stats': verification_stats(result.turns)}

    def close(self):
        pass


class SettledFixtureMarket(Market):
    """Test-only later closes; quote/snapshot retain the original fixed date."""

    def daily(self, symbol, start, end, *, index=False):
        result = super().daily(symbol, start, end, index=index)
        # Validate symbols even when the normal fixture's cutoff precedes start.
        super().daily(symbol, AS_OF, AS_OF, index=index)
        rows = {row['date']: row['close'] for row in result['items']}
        day = AS_OF
        step = 0
        while day < min(end, AS_OF + timedelta(days=14)):
            day += timedelta(days=1)
            if day.weekday() >= 5:
                continue
            step += 1
            if start <= day:
                rows[day.isoformat()] = float((1399 if index else 399) + step)
        return {'items': [{'date': day, 'close': close} for day, close in sorted(rows.items())]}


def fixture_market(settings, now=lambda: NOW, *, settled_prices=False):
    source = FakeSource()
    market_type = SettledFixtureMarket if settled_prices else Market
    return market_type(settings, source=source, news=FakeNews(),
                  catalog={'005930': ('삼성전자', 'KOSPI'), '005935': ('삼성전자우', 'KOSPI'),
                           '000660': ('SK하이닉스', 'KOSPI')}, now=now,
                  index_loader=lambda code, start, end: [(b.date, 1000 + b.close) for b in source.get_daily_prices('005930', start, end)])


def main():
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=18000)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--settled-prices', action='store_true',
                   help='test-only fixed later prices for end-to-end 3/7-session scoring')
    args = p.parse_args()
    settings = replace(load_settings(), data_dir=args.data)
    app = create_app(settings=settings, market=fixture_market(settings, settled_prices=args.settled_prices),
                     runner_factory=lambda: TestRunner(settings), token='integration-test-token')
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()

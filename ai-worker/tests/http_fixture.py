"""Loopback-only integration server using real HTTP/pipeline and deterministic providers.

uv run python -m tests.http_fixture --port 18000 --data <temporary directory>
No production switch enables these fixtures.
"""
import argparse
import os
import time
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from bullbear.config import load_settings
from bullbear.graph_runtime import GraphRuntime
from bullbear.events import EventLog
from bullbear.server.app import create_app
from bullbear.server.market import Market
from bullbear.server.service import LiveRunner
from bullbear.llm import Conversation
from types import SimpleNamespace
from .fakes import NOW, FakeNews, FakeSource
from .graph_fakes import GraphLLM


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
        return GraphRuntime(snapshot, debate_id=debate_id,
            bull=GraphLLM(snapshot, invalid=self.invalid, bad_first=True),
            bear=GraphLLM(snapshot, invalid=self.invalid),
            moderator=GraphLLM(snapshot, actions=['CHALLENGE_BULL', 'ACCEPT'] if self.extra else []),
            log=EventLog(self.settings.debate_dir / f'{debate_id}.jsonl'),
            max_extra_rounds=max_extra_rounds, emit=emit).run()

    def close(self):
        pass

    def run_single(self, snapshot, debate_id, emit):
        emit('moderator_started', {})
        return {'debate_id': debate_id, 'verdict': {
            'decision': 'HOLD', 'confidence': 0.55,
            'reasoning': '7거래일 코스피 대비 비슷한 움직임을 예상합니다 [E1].',
            'decisive_evidence': ['PX.CLOSE'], 'scores': None}, 'stats': None}


class UncertainUsageRunner(LiveRunner):
    """Test-only persisted paid-call surrogate; no provider is instantiated."""
    def run(self, snapshot, debate_id, max_extra_rounds, emit):
        known = {'calls': [{'model': 'claude-haiku-5-5', 'input_tokens': 123, 'output_tokens': 7}]}
        self.audit.data['usage'] = known
        self.audit.begin_call('debater', 'debater', SimpleNamespace(model='claude-haiku-5-5'),
                              Conversation('synthetic'), {}, 'medium', [])
        emit('turn_started', {'side': 'bull', 'round': 'opening'})
        if snapshot.ticker == '035720':
            trigger = self.settings.data_dir / 'crash-trigger'
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if trigger.exists():
                    os._exit(23)
                time.sleep(.05)
        raise RuntimeError('synthetic uncertain usage')


def fixture_market(settings, now=lambda: NOW, *, source=None):
    source = source or FakeSource()
    return Market(settings, source=source, news=FakeNews(),
                  catalog={'005930': ('삼성전자', 'KOSPI'), '005935': ('삼성전자우', 'KOSPI'),
                           '000660': ('SK하이닉스', 'KOSPI')}, now=now,
                  index_loader=lambda code, start, end: [(b.date, 1000 + b.close) for b in source.get_daily_prices('005930', start, end)])


class ScoringSource(FakeSource):
    """Only the standalone integration fixture exposes future weekday closes."""
    def get_daily_prices(self, ticker, start, end):
        from bullbear.data import PriceBar
        rows = super().get_daily_prices(ticker, start, end)
        date = NOW.date()
        for number in range(1, 8):
            date += timedelta(days=1)
            while date.weekday() >= 5:
                date += timedelta(days=1)
            if start <= date <= end:
                close = 399 + number * 5
                rows.append(PriceBar(date, close, close, close, close, 1000))
        return rows


def main():
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=18000)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--uncertain-usage', action='store_true', help='test-only failure/crash tickers')
    p.add_argument('--clock-file', type=Path, help='test-only explicit simulated market clock')
    args = p.parse_args()
    settings = replace(load_settings(), data_dir=args.data)
    def now():
        return datetime.fromisoformat(args.clock_file.read_text(encoding='utf-8').strip()) if args.clock_file else NOW
    market = fixture_market(settings, now=now, source=ScoringSource())
    if args.uncertain_usage:
        market.catalog.update({'035420': ('실패 fixture', 'KOSPI'), '035720': ('재시작 fixture', 'KOSPI')})
    def runner():
        class RoutedRunner(UncertainUsageRunner):
            def run_single(self, snapshot, debate_id, emit):
                return TestRunner(settings).run_single(snapshot, debate_id, emit)

            def run(self, snapshot, debate_id, max_extra_rounds, emit):
                if snapshot.ticker in ('035420', '035720'):
                    return super().run(snapshot, debate_id, max_extra_rounds, emit)
                return TestRunner(settings).run(snapshot, debate_id, max_extra_rounds, emit)
            def usage(self):
                return TestRunner(settings).usage()
        return RoutedRunner(settings) if args.uncertain_usage else TestRunner(settings)
    app = create_app(settings=settings, market=market,
                     runner_factory=runner, token='integration-test-token')
    try:
        # Every standalone integration route must stay offline, including new modes.
        with patch('bullbear.server.service.LLM', side_effect=AssertionError('fixture cannot create a live LLM')):
            uvicorn.run(app, host='127.0.0.1', port=args.port)
    finally:
        market.close()



if __name__ == '__main__':
    main()

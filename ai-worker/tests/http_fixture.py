"""Loopback-only integration server using real HTTP/pipeline and deterministic providers.

uv run python -m tests.http_fixture --port 18000 --data <temporary directory>
No production switch enables these fixtures.
"""
import argparse
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from bullbear.config import load_settings
from bullbear.debate import Debate, verification_stats
from bullbear.events import EventLog
from bullbear.server.app import create_app
from bullbear.server.market import Market
from .fakes import NOW, FakeNews, FakeSource, ScriptedDebater, ScriptedModerator, statement


class TestRunner:
    __test__ = False
    background_context = None

    def __init__(self, settings, *, gate=None, invalid=False, extra=False, require_context=False):
        self.settings, self.gate, self.invalid, self.extra = settings, gate, invalid, extra
        self.require_context = require_context

    def usage(self):
        return {'calls': [{'model': 'test-model', 'input_tokens': 100, 'output_tokens': 20,
                           'cache_read_input_tokens': 10, 'cache_creation_input_tokens': 5}]}

    def run(self, snapshot, debate_id, max_extra_rounds, emit):
        if self.require_context:
            assert self.background_context is not None
            assert self.background_context.payload['status'] == 'completed'
            assert 'PRIVATE_RAG_BACKGROUND' in self.background_context.rendered
        if self.background_context is not None:
            emit('token', {'text': self.background_context.rendered})
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


def prepare_rag(settings):
    """Synthetic background with an explicitly simulated historical publication clock."""
    from bullbear.rag import AnnotationInput, ChunkInput, RagStore
    from bullbear.rag.index import GenerationIndex
    from .test_rag_ingest import document, batch
    observed = NOW - timedelta(days=1)
    with RagStore(settings.data_dir / 'rag') as store:
        doc = document('PRIVATE_RAG_BACKGROUND volatility 변동성은 방향을 보장하지 않는다.',
                       observed=observed, published_at=observed-timedelta(hours=1),
                       kind='knowledge', source_item_id='http-integration-rag')
        store.import_collection(batch([doc], 'http-integration-rag'))
        chunk = ChunkInput(revision_id=doc.revision_id, ordinal=0, text=doc.text,
                           source_locator='paragraph:1', chunker_version='integration-v1')
        store.add_chunk(chunk)
        store.annotate(AnnotationInput(chunk_id=chunk.chunk_id, horizons=('common', 'short'),
                                      markets=('KR',), review_status='approved', created_at=observed,
                                      reviewed_at=observed, tagging_policy_version='integration-fixture-v1'))
        class FixtureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return observed.astimezone(tz)
        with patch('bullbear.rag.index.datetime', FixtureClock):
            generation = GenerationIndex(store).publish(observed)
    return replace(settings, rag_enabled=True, rag_generation_id=generation)


def main():
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=18000)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--rag', action='store_true')
    p.add_argument('--clock-file', type=Path, help='test-only explicit simulated market clock')
    args = p.parse_args()
    settings = replace(load_settings(), data_dir=args.data, rag_enabled=False)
    if args.rag:
        settings = prepare_rag(settings)
    def now():
        return datetime.fromisoformat(args.clock_file.read_text(encoding='utf-8').strip()) if args.clock_file else NOW
    app = create_app(settings=settings, market=fixture_market(settings, now=now, source=ScoringSource()),
                     runner_factory=lambda: TestRunner(settings, require_context=args.rag), token='integration-test-token')
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()

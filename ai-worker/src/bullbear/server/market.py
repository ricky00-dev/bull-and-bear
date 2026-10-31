"""Confirmed-close market views shared by HTTP quotes and debate snapshots."""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..data.base import DataUnavailable
from ..data.naver_news import NaverNewsSource
from ..data.krx_openapi import KrxOpenApiSource
from ..data.universe import UNIVERSE
from ..snapshot import KST, PRICE_LOOKBACK_DAYS, build_snapshot, confirmed_date
from .errors import ApiError

CHOSEONG = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'


def initial(text):
    return ''.join(CHOSEONG[(ord(c) - 0xAC00) // 588] if 0xAC00 <= ord(c) <= 0xD7A3 else c for c in text)


@dataclass
class Quote:
    ticker: str
    name: str
    market: str | None
    bars: list
    reasons: list[str]

    def detail(self):
        last, previous = self.bars[-1], self.bars[-2]
        return dict(ticker=self.ticker, name=self.name, market=self.market,
                    close=last.close, change_pct=round((last.close / previous.close - 1) * 100, 2),
                    as_of=last.date.isoformat(), eligible=not self.reasons, reasons=self.reasons,
                    sparkline=[b.close for b in self.bars[-60:]])


class FrozenPrices:
    """Delegate fundamentals, but never re-fetch prices after the quote is selected."""
    def __init__(self, source, bars):
        self.source, self.bars, self.name = source, bars, source.name

    def get_daily_prices(self, ticker, start, end):
        return [b for b in self.bars if start <= b.date <= end]

    def __getattr__(self, name):
        return getattr(self.source, name)


class Market:
    def __init__(self, settings, *, source=None, news=None, catalog=None, index_loader=None, now=None,
                 quote_wait_seconds=1.0):
        self.settings = settings
        self.source = source or KrxOpenApiSource(settings.krx_api_key, settings.dart_api_key, settings.cache_dir)
        self.now = now or (lambda: datetime.now(KST))
        self.news = news
        if source is None:
            try:
                self.news = NaverNewsSource(settings.naver_client_id, settings.naver_client_secret)
            except DataUnavailable:
                pass
        # The approved debate universe is explicit. Other securities remain searchable but blocked.
        self.catalog = catalog or {k: (v, 'KOSPI') for k, v in UNIVERSE.items()}
        self.catalog = {**self.catalog}
        if catalog is None:
            self.catalog.update({'005935': ('삼성전자우', 'KOSPI'), '069500': ('KODEX 200', 'KOSPI')})
        self.catalog_loaded = catalog is not None
        self.index_loader = index_loader or self._source_index
        self.cache = {}
        self.lock = threading.RLock()
        self.quote_wait_seconds = quote_wait_seconds
        self.quote_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='market-quote')
        self.quote_jobs = {}
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
        close_source = getattr(self.source, 'close', None)
        if close_source is not None:
            close_source()
        self.quote_pool.shutdown(wait=True, cancel_futures=True)

    def load_catalog(self):
        # OpenDART has company names/codes but no market classification; do not invent it.
        with self.lock:
            if self.catalog_loaded:
                return
            dart = getattr(self.source, '_dart', None)
            if dart is not None:
                for ticker, name in dart.listed_companies().items():
                    self.catalog.setdefault(ticker, (name, None))
            self.catalog_loaded = True

    def quote(self, ticker):
        if ticker not in self.catalog:
            self.load_catalog()
        if ticker not in self.catalog:
            raise ApiError(404, 'NOT_FOUND', '종목을 찾을 수 없습니다')
        cutoff = confirmed_date(self.now())
        key = (ticker, cutoff)
        with self.lock:
            if self.closed:
                raise DataUnavailable('시세 조회가 종료되었습니다')
            self.cache = {k: v for k, v in self.cache.items() if time.monotonic() - v[0] < 60}
            self.quote_jobs = {k: v for k, v in self.quote_jobs.items() if not v.done()}
            cached = self.cache.get(key)
            if cached:
                return cached[1]
            job = self.quote_jobs.get(key)
            if job is None:
                # Bound queued work as well as active provider requests.
                if len(self.quote_jobs) >= 32:
                    raise DataUnavailable('시세 데이터를 준비 중입니다. 잠시 후 다시 시도하세요')
                job = self.quote_pool.submit(self._load_quote, ticker, cutoff)
                self.quote_jobs[key] = job
        try:
            return job.result(timeout=self.quote_wait_seconds)
        except TimeoutError:
            if job.done():
                return job.result()
            # The shared task continues; subsequent requests reuse its full result.
            raise DataUnavailable('시세 데이터를 준비 중입니다. 잠시 후 다시 시도하세요') from None
        finally:
            if job.done():
                with self.lock:
                    if self.quote_jobs.get(key) is job:
                        del self.quote_jobs[key]

    def _load_quote(self, ticker, cutoff):
        # Freeze the request's cutoff even when loading spans the market close.
        bars = self.source.get_daily_prices(ticker, cutoff - timedelta(days=PRICE_LOOKBACK_DAYS), cutoff)
        bars = sorted({b.date: b for b in bars if b.date <= cutoff and math.isfinite(b.close) and b.close > 0}.values(), key=lambda b: b.date)
        if len(bars) < 2:
            raise DataUnavailable('확정 종가가 2거래일 이상 필요합니다')
        name, market = self.catalog[ticker]
        reasons = [] if ticker in UNIVERSE else ['현재 토론 대상 대형주 30종목에 포함되지 않습니다']
        if ticker == '005935':
            reasons = ['우선주는 토론하지 않습니다']
        if ticker == '069500':
            reasons = ['ETF는 토론하지 않습니다']
        quote = Quote(ticker, name, market, bars, reasons)
        with self.lock:
            self.cache[(ticker, cutoff)] = (time.monotonic(), quote)
        return quote

    def search(self, query, limit):
        self.load_catalog()
        q = query.strip().casefold()
        matches = [(ticker, info) for ticker, info in self.catalog.items()
                   if q in info[0].casefold() or ticker.startswith(q) or q in initial(info[0]).casefold()]
        matches.sort(key=lambda item: (item[0] not in UNIVERSE, item[0]))
        def item(match):
            ticker, (name, market) = match
            try:
                quote = self.quote(ticker)
                detail = quote.detail()
                return dict(ticker=ticker, name=name, market=market, featured=ticker in UNIVERSE,
                                  close=detail['close'], change_pct=detail['change_pct'], eligible=not quote.reasons,
                                  block_reason='; '.join(quote.reasons) or None)
            except DataUnavailable:
                return dict(ticker=ticker, name=name, market=market, featured=ticker in UNIVERSE,
                            close=0, change_pct=0, eligible=False, block_reason='시세 조회 불가')
        with ThreadPoolExecutor(max_workers=min(limit, 20)) as pool:
            items = list(pool.map(item, matches[:limit]))
        return {'items': items}

    def snapshot(self, quote):
        snap = build_snapshot(FrozenPrices(self.source, quote.bars), quote.ticker, quote.name,
                              news=self.news, now=self.now(), index_loader=self.index_loader)
        snap.warnings.extend(getattr(self.source, 'warnings', []))
        snap.save(self.settings.snapshot_dir)
        return snap

    def daily(self, symbol, start, end, *, index=False):
        if start > end:
            raise ApiError(400, 'INVALID_REQUEST', 'from은 to보다 늦을 수 없습니다')
        end = min(end, confirmed_date(self.now()))
        if start > end:
            return {'items': []}
        if index:
            if symbol not in ('KOSPI', 'KOSDAQ'):
                raise ApiError(404, 'NOT_FOUND', '지원하지 않는 지수입니다')
            rows = self.index_loader(symbol, start, end)
        else:
            if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
                raise ApiError(400, 'INVALID_REQUEST', '종목코드는 숫자 6자리입니다')
            rows = [(bar.date, bar.close) for bar in self.source.get_daily_prices(symbol, start, end)]
        values = {d: float(v) for d, v in rows if start <= d <= end and math.isfinite(v) and v > 0}
        return {'items': [{'date': d.isoformat(), 'close': v} for d, v in sorted(values.items())]}

    def _source_index(self, code, start, end):
        loader = getattr(self.source, 'get_index_prices', None)
        if loader is None:
            raise DataUnavailable('지수 공급자가 설정되지 않았습니다')
        return loader(code, start, end)

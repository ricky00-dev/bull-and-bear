import threading
import time
from datetime import timedelta

import pytest

from bullbear.data import DataUnavailable
from .fakes import AS_OF, NOW
from .http_fixture import fixture_market
from bullbear.config import load_settings


def test_failed_quote_can_be_retried():
    market = fixture_market(load_settings())
    original = market.source.get_daily_prices
    calls = []

    def flaky(ticker, start, end):
        calls.append(end)
        if len(calls) == 1:
            raise DataUnavailable('temporary failure')
        return original(ticker, start, end)

    market.source.get_daily_prices = flaky
    try:
        with pytest.raises(DataUnavailable, match='temporary failure'):
            market.quote('005930')
        assert market.quote('005930').bars[-1].date == AS_OF
        assert len(calls) == 2
    finally:
        market.close()


def test_previous_cutoff_finishing_later_preserves_current_quote():
    current = [NOW.replace(hour=10)]
    market = fixture_market(load_settings(), now=lambda: current[0])
    market.quote_wait_seconds = 0.01
    original = market.source.get_daily_prices
    gate = threading.Event()
    calls = []

    def prices(ticker, start, end):
        calls.append(end)
        if end == AS_OF - timedelta(days=1):
            assert gate.wait(5)
        return original(ticker, start, end)

    market.source.get_daily_prices = prices
    try:
        with pytest.raises(DataUnavailable):
            market.quote('005930')
        current[0] = NOW
        market.quote_wait_seconds = 1
        assert market.quote('005930').bars[-1].date == AS_OF
        gate.set()
        current[0] = NOW.replace(hour=10)
        assert market.quote('005930').bars[-1].date == AS_OF - timedelta(days=1)
        current[0] = NOW
        assert market.quote('005930').bars[-1].date == AS_OF
        assert len(calls) == 2
    finally:
        gate.set()
        market.close()


def test_completed_preload_does_not_bypass_expired_quote_cache():
    market = fixture_market(load_settings())
    market.quote_wait_seconds = 0.01
    original = market.source.get_daily_prices
    gate = threading.Event()
    calls = []

    def prices(ticker, start, end):
        calls.append(end)
        assert gate.wait(5)
        return original(ticker, start, end)

    market.source.get_daily_prices = prices
    try:
        with pytest.raises(DataUnavailable):
            market.quote('005930')
        gate.set()
        key = ('005930', AS_OF)
        quote = market.quote_jobs[key].result(timeout=2)
        market.cache[key] = (time.monotonic() - 61, quote)
        market.quote_wait_seconds = 1
        assert market.quote('005930').bars[-1].date == AS_OF
        assert len(calls) == 2
    finally:
        gate.set()
        market.close()

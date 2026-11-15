from datetime import date

import httpx
import pytest

from bullbear.data.base import DataUnavailable
from bullbear.data.naver_chart import HttpMarketSource, chart_rows
from bullbear.server.market import Market
from .http_fixture import fixture_market
from bullbear.config import load_settings


def test_chart_stock_transport_filters_nontrading_days(monkeypatch, tmp_path):
    xml = '<protocol><item data="20261015|0|0|0|100|0"/><item data="20261016|100|102|99|101|500"/></protocol>'
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, content=xml.encode('euc-kr'), request=httpx.Request('GET', url))
    monkeypatch.setattr('bullbear.data.naver_chart.httpx.get', get)
    source = HttpMarketSource(None, tmp_path)
    rows = source.get_daily_prices('005930', date(2026, 10, 15), date(2026, 10, 16))
    assert len(rows) == 1 and rows[0].close == 101
    assert calls[0][0].startswith('https://') and calls[0][1]['timeout'] == 6


def test_invalid_chart_is_data_unavailable(monkeypatch):
    monkeypatch.setattr('bullbear.data.naver_chart.httpx.get', lambda url, **kw:
                        httpx.Response(200, content=b'<html/>', request=httpx.Request('GET', url)))
    with pytest.raises(DataUnavailable):
        chart_rows('KOSPI', 10)


def test_index_sorted_deduplicated_and_date_bounded():
    market = fixture_market(load_settings())
    market.index_loader = lambda *args: [(date(2026, 10, 16), 100), (date(2026, 10, 15), 99),
                                        (date(2026, 10, 16), 101), (date(2026, 10, 17), 102)]
    result = market.daily('KOSDAQ', date(2026, 10, 15), date(2026, 10, 17), index=True)
    assert result['items'] == [{'date': '2026-10-15', 'close': 99}, {'date': '2026-10-16', 'close': 101}]

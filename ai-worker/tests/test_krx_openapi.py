from datetime import date
from dataclasses import replace
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from bullbear.config import load_settings
from bullbear.data.base import DataUnavailable
from bullbear.data.krx_openapi import KrxOpenApiSource
from bullbear.data.naver_news import NaverNewsSource
from bullbear.server.market import Market


def row(ticker="005930", day="20261016", **values):
    return {"BAS_DD": day, "ISU_CD": ticker, "TDD_OPNPRC": "100", "TDD_HGPRC": "102",
            "TDD_LWPRC": "99", "TDD_CLSPRC": "101", "ACC_TRDVOL": "1,000", **values}


def transport(monkeypatch, body, status=200):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        data = body(kwargs["params"]["basDd"]) if callable(body) else body
        return httpx.Response(status, json=data, request=httpx.Request("GET", url))
    monkeypatch.setattr("bullbear.data.krx_openapi.httpx.get", get)
    monkeypatch.setattr("bullbear.data.krx_openapi.time.sleep", lambda *_: None)
    return calls


def test_cache_shared_between_tickers_and_source_instances(tmp_path, monkeypatch):
    calls = transport(monkeypatch, {"OutBlock_1": [row(), row("000660")]})
    source = KrxOpenApiSource("test-key", None, tmp_path)
    first = source.get_daily_prices("005930", date(2026, 10, 16), date(2026, 10, 18))
    second = KrxOpenApiSource(None, None, tmp_path).get_daily_prices("000660", date(2026, 10, 16), date(2026, 10, 16))
    assert len(first) == len(second) == 1
    assert first[0].volume == 1000 and first[0].close == 101
    assert len(calls) == 1
    assert calls[0][0] == "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
    assert calls[0][1]["headers"] == {"AUTH_KEY": "test-key"}


@pytest.mark.parametrize("body,status", [({"error": "not approved"}, 200), ({}, 403),
                                       ({"OutBlock_1": [row(day="20261015")]}, 200),
                                       ({"OutBlock_1": [row(TDD_CLSPRC="NaN")]}, 200)])
def test_bad_data_and_auth_do_not_fall_back(tmp_path, monkeypatch, body, status):
    calls = transport(monkeypatch, body, status)
    with pytest.raises(DataUnavailable):
        KrxOpenApiSource("test-key", None, tmp_path).get_daily_prices("005930", date(2026, 10, 16), date(2026, 10, 16))
    assert len(calls) == 1 and "krx.co.kr" in calls[0][0]


def test_missing_key_does_not_make_network_request(tmp_path, monkeypatch):
    calls = transport(monkeypatch, {})
    with pytest.raises(DataUnavailable, match="KRX_API_KEY"):
        KrxOpenApiSource(None, None, tmp_path).get_daily_prices("005930", date(2026, 10, 16), date(2026, 10, 16))
    assert not calls


def test_close_stops_cold_history_before_next_provider_request(tmp_path, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    calls = []

    def get(url, **kwargs):
        day = kwargs['params']['basDd']
        calls.append(day)
        entered.set()
        assert gate.wait(5)
        return httpx.Response(200, json={'OutBlock_1': [row(day=day)]}, request=httpx.Request('GET', url))

    monkeypatch.setattr('bullbear.data.krx_openapi.httpx.get', get)
    source = KrxOpenApiSource('test-key', None, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(source.get_daily_prices, '005930', date(2026, 10, 15), date(2026, 10, 16))
        try:
            assert entered.wait(2)
            source.close()
        finally:
            gate.set()
        with pytest.raises(DataUnavailable, match='종료'):
            pending.result(timeout=2)
    assert calls == ['20261015']


def test_closed_market_day_and_suspended_stock_are_excluded(tmp_path, monkeypatch):
    transport(monkeypatch, lambda day: {"OutBlock_1": [] if day == "20261015" else [row(TDD_OPNPRC="0", ACC_TRDVOL="0")]})
    assert KrxOpenApiSource("test-key", None, tmp_path).get_daily_prices("005930", date(2026, 10, 15), date(2026, 10, 16)) == []


def test_index_selects_benchmark_not_first_subindex(tmp_path, monkeypatch):
    transport(monkeypatch, {"OutBlock_1": [
        {"BAS_DD": "20261016", "IDX_NM": "코스피 200", "CLSPRC_IDX": "300"},
        {"BAS_DD": "20261016", "IDX_NM": "코스피", "CLSPRC_IDX": "2,500.25"}]})
    source = KrxOpenApiSource("test-key", None, tmp_path)
    assert source.get_index_prices("KOSPI", date(2026, 10, 16), date(2026, 10, 16)) == [(date(2026, 10, 16), 2500.25)]


def test_default_routes_use_krx_dart_and_naver_news(tmp_path):
    settings = replace(load_settings(), data_dir=tmp_path, krx_api_key="test-key",
                       naver_client_id="test-id", naver_client_secret="test-secret")
    market = Market(settings)
    assert isinstance(market.source, KrxOpenApiSource)
    assert isinstance(market.news, NaverNewsSource)
    assert market.index_loader.__name__ == "_source_index"

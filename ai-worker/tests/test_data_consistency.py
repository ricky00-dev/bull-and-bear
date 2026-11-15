from datetime import date, timedelta
from dataclasses import replace
import gzip
import json
import os

import pytest

from bullbear.data.base import DataUnavailable
from bullbear.data.krx_openapi import KrxOpenApiSource
from bullbear.snapshot import build_snapshot
from .fakes import AS_OF, NOW, FakeSource
from .test_krx_openapi import row, transport


def test_snapshot_excludes_intraday_and_out_of_range_provider_rows():
    class Unbounded(FakeSource):
        def get_daily_prices(self, *args):
            return super().get_daily_prices('', AS_OF - timedelta(days=400), AS_OF)
    snap = build_snapshot(Unbounded(), '005930', '삼성전자', now=NOW.replace(hour=10))
    assert snap.as_of == AS_OF - timedelta(days=1)
    assert snap.facts['PX.CLOSE'].value == 398


def test_share_fact_preserves_disclosure_date():
    snap = build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW)
    assert snap.facts['VAL.SHARES'].as_of == date(2026, 8, 14)
    assert snap.facts['VAL.MKTCAP'].as_of == AS_OF


def test_naive_observation_time_is_rejected():
    with pytest.raises(ValueError, match='timezone'):
        build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW.replace(tzinfo=None))


def test_invalid_cached_stock_response_is_refetched(tmp_path, monkeypatch):
    path = tmp_path / 'krx-openapi/sto/stk_bydd_trd/20261016.json.gz'
    path.parent.mkdir(parents=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump([row(TDD_CLSPRC='NaN')], f)
    calls = transport(monkeypatch, {'OutBlock_1': [row()]})
    bars = KrxOpenApiSource('test', None, tmp_path).get_daily_prices('005930', AS_OF, AS_OF)
    assert bars[0].close == 101 and len(calls) == 1


def test_preclose_cache_is_not_used_as_confirmed_close(tmp_path, monkeypatch):
    path = tmp_path / 'krx-openapi/sto/stk_bydd_trd/20261016.json.gz'
    path.parent.mkdir(parents=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump([row(TDD_CLSPRC='90')], f)
    stamp = NOW.replace(hour=14).timestamp()
    os.utime(path, (stamp, stamp))
    calls = transport(monkeypatch, {'OutBlock_1': [row()]})
    bars = KrxOpenApiSource('test', None, tmp_path).get_daily_prices('005930', AS_OF, AS_OF)
    assert bars[0].close == 101 and len(calls) == 1


def test_empty_cache_retries_after_one_minute(tmp_path, monkeypatch):
    # 최근(일주일 안) 날의 빈 응답은 아직 안 올라온 것일 수 있어 1분 뒤 다시 받는다.
    # 일주일 지난 빈 날은 휴장일로 보고 다시 받지 않는다 (test_old_empty_day_is_not_refetched)
    import time
    from datetime import datetime
    from bullbear.snapshot import KST
    day = datetime.now(KST).date() - timedelta(days=1)
    path = tmp_path / f'krx-openapi/sto/stk_bydd_trd/{day:%Y%m%d}.json.gz'
    path.parent.mkdir(parents=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump([], f)
    stamp = time.time() - 61
    os.utime(path, (stamp, stamp))
    calls = transport(monkeypatch, {'OutBlock_1': [row(day=f'{day:%Y%m%d}')]})
    assert KrxOpenApiSource('test', None, tmp_path)._day('sto/stk_bydd_trd', day)[0]['TDD_CLSPRC'] == '101'
    assert len(calls) == 1


def test_bad_provider_response_never_becomes_persistent_cache(tmp_path, monkeypatch):
    transport(monkeypatch, {'OutBlock_1': [row(TDD_CLSPRC='NaN')]})
    with pytest.raises(DataUnavailable):
        KrxOpenApiSource('test', None, tmp_path).get_daily_prices('005930', AS_OF, AS_OF)
    assert not list(tmp_path.rglob('*.json.gz'))


def test_cached_subindex_without_benchmark_is_refetched(tmp_path, monkeypatch):
    path = tmp_path / 'krx-openapi/idx/kospi_dd_trd/20261016.json.gz'
    path.parent.mkdir(parents=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump([{'BAS_DD': '20261016', 'IDX_NM': '코스피 200', 'CLSPRC_IDX': '300'}], f)
    calls = transport(monkeypatch, {'OutBlock_1': [
        {'BAS_DD': '20261016', 'IDX_NM': '코스피', 'CLSPRC_IDX': '2500'}]})
    rows = KrxOpenApiSource('test', None, tmp_path).get_index_prices('KOSPI', AS_OF, AS_OF)
    assert rows == [(AS_OF, 2500)] and len(calls) == 1


def benchmark(code, start, end):
    assert code == 'KOSPI'
    return [(b.date, 1000 + b.close) for b in FakeSource().get_daily_prices('', start, end)]


def test_benchmark_comparison_uses_identical_dates_and_unrounded_returns():
    calls = []
    def loader(code, start, end):
        calls.append((start, end))
        return benchmark(code, start, end)
    snap = build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW, index_loader=loader)
    assert calls == [(date(2026, 8, 10), AS_OF)]
    for n in (3, 7, 21):
        stock_ret = (399 / (399 - n) - 1) * 100
        index_ret = (1399 / (1399 - n) - 1) * 100
        fact = snap.facts[f'PX.EXCESS_KOSPI_{n}D']
        assert fact.value == round(stock_ret - index_ret, 2)
        assert fact.inputs == [f'PX.RET_{n}D', f'MKT.KOSPI_RET_{n}D']
        assert fact.as_of == AS_OF


def test_missing_benchmark_date_is_not_forward_filled():
    def loader(code, start, end):
        return [(d, v) for d, v in benchmark(code, start, end) if d != end - timedelta(days=7)]
    snap = build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW, index_loader=loader)
    assert 'PX.EXCESS_KOSPI_3D' in snap.facts
    assert 'PX.EXCESS_KOSPI_7D' not in snap.facts
    assert any('7거래일 양 끝 날짜 지수 없음' in w for w in snap.warnings)


@pytest.mark.parametrize('failure', ['missing-end', 'conflict', 'nan', 'provider'])
def test_bad_or_missing_index_does_not_fabricate_comparison(failure):
    def loader(code, start, end):
        if failure == 'provider':
            raise DataUnavailable('PRIVATE provider details')
        rows = benchmark(code, start, end)
        if failure == 'missing-end':
            return rows[:-1]
        return rows + [(end, float('nan') if failure == 'nan' else 1)]
    snap = build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW, index_loader=loader)
    assert snap.facts['PX.CLOSE'].value == 399
    assert not any(k.startswith('PX.EXCESS') for k in snap.facts)
    assert any('코스피 비교 입력' in w for w in snap.warnings)
    assert 'PRIVATE' not in ' '.join(snap.warnings)


def test_http_snapshot_keeps_frozen_quote_and_matches_daily_index(tmp_path):
    from bullbear.config import load_settings
    from .http_fixture import fixture_market
    market = fixture_market(replace(load_settings(), data_dir=tmp_path))
    try:
        quote = market.quote('005930')
        snap = market.snapshot(quote)
        rows = market.daily('KOSPI', AS_OF - timedelta(days=3), AS_OF, index=True)['items']
        assert snap.as_of.isoformat() == quote.detail()['as_of'] == rows[-1]['date']
        assert snap.facts['PX.CLOSE'].value == quote.detail()['close']
        assert snap.facts['MKT.KOSPI_RET_3D'].value == round((rows[-1]['close'] / rows[0]['close'] - 1) * 100, 2)
    finally:
        market.close()

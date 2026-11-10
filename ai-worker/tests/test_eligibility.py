import pytest

from bullbear.server.market import block_reasons


@pytest.mark.parametrize('ticker, name, market', [
    ('005930', '삼성전자', 'KOSPI'),          # 대형주 30종목
    ('042700', '한미반도체', 'KOSPI'),        # 30종목 밖 보통주
    ('247540', '에코프로비엠', None),         # DART 목록은 시장 구분이 없다 (코스피 여부는 Market이 KRX 목록으로 거른다)
])
def test_common_stocks_are_open(ticker, name, market):
    assert block_reasons(ticker, name, market) == []


@pytest.mark.parametrize('ticker, name, market, reason', [
    ('005935', '삼성전자우', 'KOSPI', '우선주'),
    ('00680K', '미래에셋증권2우B', 'KOSPI', '우선주'),
    ('069500', 'KODEX 200', 'KOSPI', 'ETF'),
    ('102110', 'TIGER 200', 'ETF', 'ETF'),
    ('442310', '하나29호스팩', None, '스팩'),
    ('365340', '성일하이텍', 'KOSDAQ', '코스피'),
])
def test_preferred_etf_and_spac_are_blocked(ticker, name, market, reason):
    reasons = block_reasons(ticker, name, market)
    assert len(reasons) == 1 and reason in reasons[0]


def test_market_blocks_tickers_outside_kospi_list(tmp_path):
    """KRX 코스피 목록에 없는 종목(코스닥 등)은 검색에서 막고 시세도 받지 않는다."""
    from dataclasses import replace

    from bullbear.config import load_settings
    from bullbear.server.errors import ApiError
    from bullbear.server.market import KOSPI_ONLY

    from .fakes import FakeSource
    from .http_fixture import fixture_market

    class KospiSource(FakeSource):
        price_calls = []

        def kospi_tickers(self, end):
            return {'005930', '000660'}

        def get_daily_prices(self, ticker, start, end):
            self.price_calls.append(ticker)
            return super().get_daily_prices(ticker, start, end)

    source = KospiSource()
    market = fixture_market(replace(load_settings(), data_dir=tmp_path), source=source)
    market.catalog['365340'] = ('성일하이텍', None)
    market.catalog_loaded = True

    items = {i['ticker']: i for i in market.search('', 10)['items']}
    assert items['365340']['eligible'] is False and items['365340']['block_reason'] == KOSPI_ONLY
    assert items['000660']['eligible'] is True and items['000660']['market'] == 'KOSPI'
    with pytest.raises(ApiError) as e:
        market.quote('365340')
    assert e.value.status == 422 and e.value.reasons == [KOSPI_ONLY]
    assert '365340' not in source.price_calls

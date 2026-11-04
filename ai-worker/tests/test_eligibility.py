import pytest

from bullbear.server.market import block_reasons


@pytest.mark.parametrize('ticker, name, market', [
    ('005930', '삼성전자', 'KOSPI'),          # 대형주 30종목
    ('042700', '한미반도체', 'KOSPI'),        # 30종목 밖 보통주
    ('365340', '성일하이텍', 'KOSDAQ'),
    ('247540', '에코프로비엠', None),         # DART 목록은 시장 구분이 없다
])
def test_common_stocks_are_open(ticker, name, market):
    assert block_reasons(ticker, name, market) == []


@pytest.mark.parametrize('ticker, name, market, reason', [
    ('005935', '삼성전자우', 'KOSPI', '우선주'),
    ('00680K', '미래에셋증권2우B', 'KOSPI', '우선주'),
    ('069500', 'KODEX 200', 'KOSPI', 'ETF'),
    ('102110', 'TIGER 200', 'ETF', 'ETF'),
    ('442310', '하나29호스팩', 'KOSDAQ', '스팩'),
])
def test_preferred_etf_and_spac_are_blocked(ticker, name, market, reason):
    reasons = block_reasons(ticker, name, market)
    assert len(reasons) == 1 and reason in reasons[0]

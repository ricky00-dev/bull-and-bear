"""한국투자증권 Open API 구현체 (미구현).

실시간 시세가 필요해지면 여기를 채운다. 착수 전에 확인할 것:
- 약관상 시세 재배포 제한 (전시 화면 송출이 재배포에 해당하는지)
- 모의투자 도메인(openapivts) / 실전 도메인 구분, 토큰 발급 주기
"""

from __future__ import annotations

from datetime import date

from .base import Disclosure, FinancialReport, MarketDataSource, PriceBar, ShareCount


class KisSource(MarketDataSource):
    name = "kis"

    def __init__(self, app_key: str, app_secret: str, *, paper: bool = True):
        self._app_key = app_key
        self._app_secret = app_secret
        self._paper = paper

    def get_daily_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        raise NotImplementedError("KIS 시세 조회 미구현")

    def get_financial_reports(self, ticker: str, as_of: date) -> list[FinancialReport]:
        raise NotImplementedError("KIS 재무 조회 미구현")

    def get_share_count(self, ticker: str, as_of: date) -> ShareCount | None:
        raise NotImplementedError("KIS 주식수 조회 미구현")

    def get_disclosures(self, ticker: str, start: date, end: date) -> list[Disclosure]:
        raise NotImplementedError("KIS 공시 조회 미구현")

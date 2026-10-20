"""시장 데이터 소스 인터페이스.

토론 파이프라인은 이 인터페이스만 안다. pykrx/OpenDART, KIS 등 실제 공급자는
구현체로 갈아끼운다. 모든 조회는 `as_of` 기준 시점 이전 데이터만 돌려줘야 한다
(그 시점에 알 수 없었던 데이터가 섞이면 채점이 오염된다).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ReportType = Literal["Q1", "H1", "Q3", "FY"]

# 공급자와 무관한 표준 계정 키
ACCOUNT_KEYS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
)
INCOME_ACCOUNTS = frozenset({"revenue", "operating_income", "net_income"})


class DataUnavailable(Exception):
    """공급자가 요청한 데이터를 줄 수 없을 때 (키 없음, 미지원, 응답 없음)."""


@dataclass(frozen=True)
class PriceBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class AccountValue:
    """한 계정의 금액(원).

    current: 해당 기간 값. 손익계정이면 분기(3개월) 또는 연간, 재무상태표 계정이면 기말 잔액.
    ytd: 손익계정의 당해 누적값. 연간 보고서면 current와 같다.
    prior_ytd: 전년 동기 누적값 (TTM 계산용). 없으면 None.
    """

    current: float | None
    ytd: float | None = None
    prior_ytd: float | None = None


@dataclass(frozen=True)
class FinancialReport:
    fiscal_year: int
    report_type: ReportType
    filed_on: date
    consolidated: bool
    source_ref: str  # 공급자 문서 번호 (DART 접수번호 등)
    accounts: dict[str, AccountValue] = field(default_factory=dict)

    @property
    def period(self) -> str:
        return f"{self.fiscal_year}{self.report_type}"


@dataclass(frozen=True)
class ShareCount:
    common_shares: int
    as_of: date
    source_ref: str


@dataclass(frozen=True)
class Disclosure:
    source_ref: str
    filed_on: date
    title: str
    filer: str
    url: str


class MarketDataSource(ABC):
    """시세·재무·공시 조회 인터페이스."""

    name: str = "abstract"

    @abstractmethod
    def get_daily_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        """[start, end] 구간 일봉, 날짜 오름차순."""

    @abstractmethod
    def get_financial_reports(self, ticker: str, as_of: date) -> list[FinancialReport]:
        """as_of 이전에 제출된 보고서 중 최신 보고서와 최근 사업보고서 2개.

        최신순 정렬. 최신 보고서가 사업보고서면 중복 없이 반환한다.
        """

    @abstractmethod
    def get_share_count(self, ticker: str, as_of: date) -> ShareCount | None:
        """as_of 시점에 공시된 보통주 발행주식수."""

    @abstractmethod
    def get_disclosures(self, ticker: str, start: date, end: date) -> list[Disclosure]:
        """[start, end] 구간 공시 목록, 최신순."""

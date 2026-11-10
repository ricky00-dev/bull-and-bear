"""pykrx(시세) + OpenDART(재무·발행주식수·공시) 구현체.

pykrx의 KRX 정보데이터시스템 API(PER/PBR, 시가총액)는 현재 빈 응답을 준다.
그래서 밸류에이션은 공급자에서 받지 않고 스냅샷 빌더가 시세와 재무로 계산한다.
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from .base import (
    AccountValue,
    DataUnavailable,
    Disclosure,
    FinancialReport,
    INCOME_ACCOUNTS,
    MarketDataSource,
    PriceBar,
    ReportType,
    ShareCount,
)
from .opendart import REPORT_CODES, OpenDartClient, parse_amount

with warnings.catch_warnings():
    warnings.simplefilter("ignore")  # pykrx가 pkg_resources 경고를 낸다
    from pykrx import stock as krx

# 최신 보고서를 찾을 때 확인하는 순서 (같은 해 안에서 늦게 나오는 보고서부터)
_REPORT_ORDER: tuple[ReportType, ...] = ("FY", "Q3", "H1", "Q1")

# DART 계정명 → 표준 키. 업종마다 이름이 조금씩 달라 후보를 여러 개 둔다.
_ACCOUNT_NAMES = {
    "revenue": ("매출액", "수익(매출액)", "영업수익", "매출"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity": ("자본총계",),
}


class PykrxDartSource(MarketDataSource):
    name = "pykrx+opendart"

    def __init__(self, dart_api_key: str | None, cache_dir: Path):
        self._dart: OpenDartClient | None = None
        self._dart_error: str | None = None
        try:
            self._dart = OpenDartClient(dart_api_key or "", cache_dir / "opendart")
        except DataUnavailable as e:
            self._dart_error = str(e)

    # ---- 시세 (pykrx) ----

    def get_daily_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        df = krx.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
        if df is None or df.empty:
            raise DataUnavailable(f"pykrx 시세 없음: {ticker}")
        bars = []
        for idx, row in df.iterrows():
            if int(row["거래량"]) == 0 and float(row["시가"]) == 0:
                continue  # 거래정지일
            bars.append(
                PriceBar(
                    date=idx.date(),
                    open=float(row["시가"]),
                    high=float(row["고가"]),
                    low=float(row["저가"]),
                    close=float(row["종가"]),
                    volume=int(row["거래량"]),
                )
            )
        return bars

    # ---- 재무 (OpenDART) ----

    def _require_dart(self) -> OpenDartClient:
        if self._dart is None:
            raise DataUnavailable(self._dart_error or "OpenDART 미설정")
        return self._dart

    def get_financial_reports(self, ticker: str, as_of: date) -> list[FinancialReport]:
        dart = self._require_dart()
        corp = dart.corp_code(ticker)

        latest: FinancialReport | None = None
        annuals: list[FinancialReport] = []
        for year in range(as_of.year, as_of.year - 4, -1):
            for rtype in _REPORT_ORDER:
                if latest is not None and rtype != "FY":
                    continue
                report = self._fetch_report(dart, corp, year, rtype)
                if report is None or report.filed_on > as_of:
                    continue
                if latest is None:
                    latest = report
                if rtype == "FY":
                    annuals.append(report)
            if len(annuals) >= 2:
                break

        if latest is None:
            return []
        cash_flow = self._operating_cash_flow(dart, corp, latest)
        earlier = [r for r in annuals[:2] if r is not latest]
        if cash_flow is not None:
            latest = replace(latest, accounts={**latest.accounts, "operating_cash_flow": AccountValue(cash_flow)})
        return [latest, *earlier]

    def _operating_cash_flow(self, dart: OpenDartClient, corp: str, report: FinancialReport) -> float | None:
        try:
            body = dart.get("fnlttSinglAcntAll", corp_code=corp, bsns_year=str(report.fiscal_year),
                            reprt_code=REPORT_CODES[report.report_type],
                            fs_div="CFS" if report.consolidated else "OFS")
        except DataUnavailable:
            return None
        rows = (body or {}).get("list", [])
        values = set()
        for row in rows:
            if row.get("sj_div") != "CF" or f"DART:{row.get('rcept_no')}" != report.source_ref:
                continue
            if row.get("currency") != "KRW":
                continue
            account = str(row.get("account_nm", "")).replace(" ", "")
            if (row.get("account_id") in ("ifrs-full_CashFlowsFromUsedInOperatingActivities",
                                         "ifrs_CashFlowsFromUsedInOperatingActivities")
                    or account in ("영업활동현금흐름", "영업활동으로인한현금흐름")):
                value = parse_amount(row.get("thstrm_amount"))
                if value is not None:
                    values.add(value)
        return next(iter(values)) if len(values) == 1 else None

    def _fetch_report(self, dart: OpenDartClient, corp: str, year: int, rtype: ReportType) -> FinancialReport | None:
        body = dart.get(
            "fnlttSinglAcnt",
            corp_code=corp,
            bsns_year=str(year),
            reprt_code=REPORT_CODES[rtype],
        )
        if body is None:
            return None
        rows = body.get("list", [])
        consolidated = any(r.get("fs_div") == "CFS" for r in rows)
        rows = [r for r in rows if r.get("fs_div") == ("CFS" if consolidated else "OFS")]
        if not rows:
            return None

        accounts: dict[str, AccountValue] = {}
        for key, names in _ACCOUNT_NAMES.items():
            row = next((r for n in names for r in rows if r.get("account_nm", "").strip() == n), None)
            if row is None:
                continue
            current = parse_amount(row.get("thstrm_amount"))
            if key in ("total_assets", "total_liabilities", "total_equity") or rtype == "FY":
                prior = parse_amount(row.get("frmtrm_amount")) if key in INCOME_ACCOUNTS else None
                accounts[key] = AccountValue(current=current, ytd=current, prior_ytd=prior)
            else:
                ytd = parse_amount(row.get("thstrm_add_amount"))
                accounts[key] = AccountValue(
                    current=current,
                    # 1분기 보고서는 누적값 칸이 비어 있을 수 있다 (3개월 = 누적)
                    ytd=ytd if ytd is not None else (current if rtype == "Q1" else None),
                    prior_ytd=parse_amount(row.get("frmtrm_add_amount"))
                    or (parse_amount(row.get("frmtrm_amount")) if rtype == "Q1" else None),
                )

        rcept_no = max(row["rcept_no"] for row in rows)
        return FinancialReport(
            fiscal_year=year,
            report_type=rtype,
            filed_on=datetime.strptime(rcept_no[:8], "%Y%m%d").date(),
            consolidated=consolidated,
            source_ref=f"DART:{rcept_no}",
            accounts=accounts,
        )

    def get_share_count(self, ticker: str, as_of: date) -> ShareCount | None:
        dart = self._require_dart()
        corp = dart.corp_code(ticker)
        for year in range(as_of.year, as_of.year - 2, -1):
            for rtype in _REPORT_ORDER:
                body = dart.get("stockTotqySttus", corp_code=corp, bsns_year=str(year), reprt_code=REPORT_CODES[rtype])
                if body is None:
                    continue
                row = next((r for r in body.get("list", []) if r.get("se", "").strip() == "보통주"), None)
                if row is None:
                    continue
                filed_on = datetime.strptime(row["rcept_no"][:8], "%Y%m%d").date()
                if filed_on > as_of:
                    continue
                shares = parse_amount(row.get("istc_totqy"))
                if shares:
                    return ShareCount(int(shares), filed_on, f"DART:{row['rcept_no']}")
        return None

    def get_disclosures(self, ticker: str, start: date, end: date) -> list[Disclosure]:
        dart = self._require_dart()
        body = dart.get(
            "list",
            # 기간이 끝나지 않은 조회는 결과가 바뀌므로 캐시하지 않는다
            cache=end < date.today(),
            corp_code=dart.corp_code(ticker),
            bgn_de=start.strftime("%Y%m%d"),
            end_de=end.strftime("%Y%m%d"),
            page_count="100",
        )
        if body is None:
            return []
        return [
            Disclosure(
                source_ref=f"DART:{r['rcept_no']}",
                filed_on=datetime.strptime(r["rcept_dt"], "%Y%m%d").date(),
                title=r["report_nm"].strip(),
                filer=r.get("flr_nm", "").strip(),
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
            )
            for r in body.get("list", [])
        ]

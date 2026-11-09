"""판단 시점 스냅샷.

토론 시작 시 데이터 소스에서 한 번 받아온 뒤 고정한다. 에이전트, 검증기, 중재자는
모두 이 스냅샷만 본다. 모든 수치는 `Fact`로 저장되고 고유 ID(예: VAL.PER_TTM)를 가진다.
에이전트는 근거를 낼 때 이 ID를 인용하고, 검증기는 ID로 원본 값을 찾아 대조한다.

스냅샷 ID는 내용 해시로 만든다. 같은 데이터면 같은 ID가 나오므로 토론 재사용 캐시의 키로 쓴다.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .data import DataUnavailable, FinancialReport, MarketDataSource, NewsSource, PriceBar
from .data.base import INCOME_ACCOUNTS

Category = Literal["price", "financials", "valuation", "disclosure", "news"]

ACCOUNT_LABELS = {
    "revenue": "매출액",
    "operating_income": "영업이익",
    "net_income": "당기순이익",
    "total_assets": "자산총계",
    "total_liabilities": "부채총계",
    "total_equity": "자본총계",
}
REPORT_LABELS = {"Q1": "1분기", "H1": "반기", "Q3": "3분기", "FY": "연간"}

PRICE_LOOKBACK_DAYS = 400  # 1년 수익률 + 120일 이동평균에 충분한 달력일
DISCLOSURE_LOOKBACK_DAYS = 90
MAX_DISCLOSURES = 30
NEWS_LOOKBACK_DAYS = 7
MAX_NEWS = 30
KST = timezone(timedelta(hours=9))
MARKET_CLOSE = time(15, 40)  # 종가 확정 여유 포함
NEWS_CLOSE = time(15, 30)  # 기준일 정규장 마감. 그 뒤 기사는 채점 구간(기준일 종가 이후) 정보다


def confirmed_date(now: datetime) -> date:
    if now.utcoffset() is None:
        raise ValueError("Observation time must include a timezone")
    local = now.astimezone(KST)
    return local.date() - timedelta(days=local.time() < MARKET_CLOSE)


class Fact(BaseModel):
    id: str
    category: Category
    label: str
    value: float | None  # 공시처럼 수치가 없는 근거는 None
    unit: Literal["KRW", "KRW/share", "%", "x", "shares", "count", "text"]
    as_of: date
    source: str  # 원천 (pykrx, DART:접수번호, derived)
    inputs: list[str] = Field(default_factory=list)  # 계산값이면 입력 Fact ID
    note: str | None = None
    url: str | None = None
    published_at: datetime | None = None  # 뉴스처럼 시각이 중요한 근거


class Snapshot(BaseModel):
    snapshot_id: str
    ticker: str
    name: str
    as_of: date  # 마지막 일봉 날짜
    created_at: datetime  # 조회 시작 시 고정한 정보 cutoff; 개별 공급자의 실제 관측 시각은 아님
    provider: str
    facts: dict[str, Fact]
    warnings: list[str] = Field(default_factory=list)

    def by_category(self, category: Category) -> list[Fact]:
        return [f for f in self.facts.values() if f.category == category]

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.snapshot_id}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path, snapshot_id: str) -> Snapshot:
        return cls.model_validate_json((directory / f"{snapshot_id}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 빌더


def build_snapshot(
    source: MarketDataSource,
    ticker: str,
    name: str,
    *,
    news: NewsSource | None = None,
    now: datetime | None = None,
    index_loader=None,
) -> Snapshot:
    now = now or datetime.now(KST)
    cutoff = confirmed_date(now)
    warnings: list[str] = []
    facts: dict[str, Fact] = {}

    start = cutoff - timedelta(days=PRICE_LOOKBACK_DAYS)
    bars = source.get_daily_prices(ticker, start, cutoff)
    bars = sorted({b.date: b for b in bars if start <= b.date <= cutoff}.values(), key=lambda b: b.date)
    if len(bars) < 2:
        raise DataUnavailable(f"시세가 부족합니다: {ticker}")
    if any(not all(math.isfinite(v) and v > 0 for v in (b.open, b.high, b.low, b.close))
           or b.low > min(b.open, b.close) or b.high < max(b.open, b.close)
           or not math.isfinite(b.volume) or b.volume < 0 for b in bars):
        raise DataUnavailable("스냅샷 일봉 형식 오류")
    as_of = bars[-1].date
    _add(facts, price_facts(bars, provider=source.name.split("+")[0]))
    # Optional comparison evidence, bounded to 22 stock sessions (not 400 calendar days).
    loader = index_loader or getattr(source, 'get_index_prices', None)
    if loader is None:
        warnings.append("코스피 비교 입력 없음: 지수 공급자 미설정")
    else:
        try:
            comparison, missing = benchmark_facts(bars, loader, source.name.split("+")[0])
            _add(facts, comparison)
            if missing:
                warnings.append("코스피 비교 입력 부족: " + ', '.join(missing))
        except DataUnavailable:
            warnings.append("코스피 비교 입력 없음: 지수 조회 실패")

    reports: list[FinancialReport] = []
    try:
        reports = [r for r in source.get_financial_reports(ticker, as_of) if r.filed_on <= as_of]
        _add(facts, financial_facts(reports))
    except DataUnavailable as e:
        warnings.append(f"재무 데이터 없음: {e}")

    shares = None
    try:
        shares = source.get_share_count(ticker, as_of)
    except DataUnavailable as e:
        warnings.append(f"발행주식수 없음: {e}")
    if shares is not None:
        if shares.as_of > as_of or shares.common_shares <= 0:
            warnings.append("발행주식수 기준일 또는 수량 오류로 밸류에이션을 계산하지 않았습니다")
        else:
            _add(facts, valuation_facts(bars[-1], reports, shares.common_shares, shares.source_ref, as_of,
                                       shares_as_of=shares.as_of))
    else:
        warnings.append("발행주식수가 없어 밸류에이션을 계산하지 않았습니다")

    try:
        disclosures = source.get_disclosures(ticker, as_of - timedelta(days=DISCLOSURE_LOOKBACK_DAYS), as_of)
        for d in [d for d in disclosures if as_of - timedelta(days=DISCLOSURE_LOOKBACK_DAYS) <= d.filed_on <= as_of][:MAX_DISCLOSURES]:
            fid = f"DISC.{d.source_ref.split(':')[-1]}"
            facts[fid] = Fact(
                id=fid, category="disclosure", label=d.title, value=None, unit="text",
                as_of=d.filed_on, source=d.source_ref, note=f"제출인 {d.filer}", url=d.url,
            )
    except DataUnavailable as e:
        warnings.append(f"공시 없음: {e}")

    if news is None:
        warnings.append("뉴스 소스 미설정")
    else:
        try:
            # 기준일(마지막 일봉) 장 마감까지만. 시세가 늦게 올라와 기준일이 며칠 전이어도
            # 그 사이 기사는 채점 구간의 정보라 넣지 않는다 (재무·공시도 as_of로 자른다)
            news_end = min(now, datetime.combine(as_of, NEWS_CLOSE, tzinfo=KST))
            news_start = news_end - timedelta(days=NEWS_LOOKBACK_DAYS)
            articles = news.search(ticker, name, news_start, news_end)
            articles = [a for a in articles if a.published_at.utcoffset() is not None
                        and news_start <= a.published_at <= news_end]
            _add(facts, news_facts(articles[:MAX_NEWS]))
        except DataUnavailable as e:
            warnings.append(f"뉴스 없음: {e}")

    digest = hashlib.sha256(
        json.dumps({k: v.model_dump(mode="json") for k, v in sorted(facts.items())}, sort_keys=True).encode()
    ).hexdigest()[:10]
    return Snapshot(
        snapshot_id=f"{ticker}-{as_of:%Y%m%d}-{digest}",
        ticker=ticker,
        name=name,
        as_of=as_of,
        created_at=now,
        provider=source.name + (f"+{news.name}" if news else ""),
        facts=facts,
        warnings=warnings,
    )


def _add(facts: dict[str, Fact], new: list[Fact]) -> None:
    for f in new:
        facts[f.id] = f


def benchmark_facts(bars: list[PriceBar], loader, provider: str) -> tuple[list[Fact], list[str]]:
    """Trailing comparisons on identical dates; never forward-fill a missing index close.

    These are historical evidence, not the future 3/7-session scoring outcome.
    Percent units keep the existing Fact/API vocabulary unchanged.
    """
    last = bars[-1]
    start = bars[max(0, len(bars) - 22)].date
    try:
        rows = loader('KOSPI', start, last.date)
        index = {}
        for day, value in rows:
            if not start <= day <= last.date:
                continue
            value = float(value)
            if not math.isfinite(value) or value <= 0 or (day in index and index[day] != value):
                raise ValueError('Invalid benchmark close')
            index[day] = value
    except (ValueError, TypeError):
        raise DataUnavailable('코스피 비교 입력 형식 오류') from None
    facts, missing = [], []
    for n in (3, 7, 21):
        if len(bars) <= n:
            missing.append(f'{n}거래일 주가 부족')
            continue
        base = bars[-n - 1]
        if base.date not in index or last.date not in index:
            missing.append(f'{n}거래일 양 끝 날짜 지수 없음')
            continue
        stock_return = (last.close / base.close - 1) * 100
        index_return = (index[last.date] / index[base.date] - 1) * 100
        note = (f'{base.date} → {last.date}, 종목 종가 {base.close:g} → {last.close:g}원, '
                f'코스피 {index[base.date]:g} → {index[last.date]:g}포인트. '
                '동일 날짜 종가 기준 과거 수익률이며 미래 채점 결과가 아님. 종목 기업행사 미보정.')
        for fid, label, value, source, inputs in (
            (f'PX.RET_{n}D', f'최근 {n}종목 거래일 수익률', stock_return, provider, []),
            (f'MKT.KOSPI_RET_{n}D', f'동일 기간 코스피 수익률({n}종목 거래일)', index_return, provider, []),
            (f'PX.EXCESS_KOSPI_{n}D', f'동일 기간 코스피 대비 초과수익률({n}종목 거래일, %p)',
             stock_return - index_return, 'derived', [f'PX.RET_{n}D', f'MKT.KOSPI_RET_{n}D']),
        ):
            facts.append(Fact(id=fid, category='price', label=label, value=round(value, 2), unit='%',
                              as_of=last.date, source=source, inputs=inputs, note=note))
    return facts, missing


def _round(x: float, unit: str) -> float:
    if unit in ("%", "x"):
        return round(x, 2)
    return float(round(x))


# ---- 시세 지표 ----

_RETURN_WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}
_MA_WINDOWS = (20, 60, 120)


def price_facts(bars: list[PriceBar], *, provider: str = "pykrx") -> list[Fact]:
    last = bars[-1]
    as_of = last.date
    closes = [b.close for b in bars]
    out: list[Fact] = []

    def fact(fid: str, label: str, value: float, unit: str, note: str | None = None) -> None:
        out.append(Fact(id=fid, category="price", label=label, value=_round(value, unit), unit=unit,
                        as_of=as_of, source=provider, note=note))

    fact("PX.CLOSE", "종가", last.close, "KRW/share")
    fact("PX.CHG_1D", "전일 대비 등락률", (last.close / bars[-2].close - 1) * 100, "%")

    for label, n in _RETURN_WINDOWS.items():
        if len(closes) > n:
            fact(f"PX.RET_{label}", f"{label} 수익률", (closes[-1] / closes[-1 - n] - 1) * 100, "%",
                 note=f"{n}거래일 전 종가 대비")

    year = bars[-252:]
    hi = max(b.high for b in year)
    lo = min(b.low for b in year)
    span = f"최근 {len(year)}거래일"
    fact("PX.HIGH_52W", "52주 최고가", hi, "KRW/share", note=span)
    fact("PX.LOW_52W", "52주 최저가", lo, "KRW/share", note=span)
    fact("PX.FROM_HIGH_52W", "52주 최고가 대비", (last.close / hi - 1) * 100, "%")
    fact("PX.FROM_LOW_52W", "52주 최저가 대비", (last.close / lo - 1) * 100, "%")

    for n in _MA_WINDOWS:
        if len(closes) >= n:
            ma = sum(closes[-n:]) / n
            fact(f"PX.MA{n}", f"{n}일 이동평균", ma, "KRW/share")
            fact(f"PX.VS_MA{n}", f"{n}일 이동평균 대비", (last.close / ma - 1) * 100, "%")

    if len(closes) > 20:
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 20, len(closes))]
        mean = sum(rets) / len(rets)
        std = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        fact("PX.VOL_20D", "최근 20거래일 일간 수익률의 연율화 변동성", std * math.sqrt(252) * 100, "%",
             note="최근 21개 종가로 구한 20개 일간 로그수익률의 표본표준편차 × √252 × 100. 20일 누적 등락률이나 예상 하락폭이 아님. 원시 종가 기준으로 기업행사 미보정.")

    if len(bars) >= 21:
        avg = sum(b.volume for b in bars[-21:-1]) / 20
        fact("PX.AVG_VOLUME_20D", "20일 평균 거래량", avg, "shares", note="당일 제외")
        if avg > 0:
            fact("PX.VOLUME_RATIO", "거래량 / 20일 평균", last.volume / avg, "x")
    return out


# ---- 재무 ----


def financial_facts(reports: list[FinancialReport]) -> list[Fact]:
    out: list[Fact] = []
    for r in reports:
        basis = "연결" if r.consolidated else "별도"
        period_label = f"{r.fiscal_year}년 {REPORT_LABELS[r.report_type]}"
        for key, acc in r.accounts.items():
            label = ACCOUNT_LABELS[key]
            if key in INCOME_ACCOUNTS and r.report_type != "FY":
                if acc.ytd is not None:
                    out.append(Fact(
                        id=f"FIN.{r.period}.{key.upper()}_YTD", category="financials",
                        label=f"{period_label} 누적 {label}", value=acc.ytd, unit="KRW",
                        as_of=r.filed_on, source=r.source_ref, note=basis,
                    ))
                if acc.ytd and acc.prior_ytd:
                    out.append(Fact(
                        id=f"FIN.{r.period}.{key.upper()}_YOY", category="financials",
                        label=f"{period_label} 누적 {label} 전년 동기 대비", value=round((acc.ytd / acc.prior_ytd - 1) * 100, 2)
                        if acc.prior_ytd > 0 else None,
                        unit="%", as_of=r.filed_on, source="derived", inputs=[f"FIN.{r.period}.{key.upper()}_YTD"],
                        note=f"{basis}, 전년 동기 누적 {acc.prior_ytd:,.0f}원" + ("" if acc.prior_ytd > 0 else ", 전년 적자로 증감률 미산출"),
                    ))
            elif acc.current is not None:
                out.append(Fact(
                    id=f"FIN.{r.period}.{key.upper()}", category="financials",
                    label=f"{period_label} {label}", value=acc.current, unit="KRW",
                    as_of=r.filed_on, source=r.source_ref, note=basis,
                ))
    return [f for f in out if f.value is not None or f.unit == "text"]


def ttm(reports: list[FinancialReport], key: str) -> tuple[float, list[str]] | None:
    """최근 4개 분기 합계와 계산에 쓴 Fact ID."""
    if not reports:
        return None
    latest = reports[0]
    if latest.report_type == "FY":
        acc = latest.accounts.get(key)
        return (acc.current, [f"FIN.{latest.period}.{key.upper()}"]) if acc and acc.current is not None else None
    prev_fy = next((r for r in reports if r.report_type == "FY" and r.fiscal_year == latest.fiscal_year - 1), None)
    acc = latest.accounts.get(key)
    prev = prev_fy.accounts.get(key) if prev_fy else None
    if not (acc and acc.ytd is not None and acc.prior_ytd is not None and prev and prev.current is not None):
        return None
    return (
        prev.current + acc.ytd - acc.prior_ytd,
        [f"FIN.{prev_fy.period}.{key.upper()}", f"FIN.{latest.period}.{key.upper()}_YTD"],
    )


def valuation_facts(last: PriceBar, reports: list[FinancialReport], shares: int, shares_ref: str, as_of: date,
                    *, shares_as_of: date | None = None) -> list[Fact]:
    out: list[Fact] = [
        Fact(id="VAL.SHARES", category="valuation", label="보통주 발행주식수", value=float(shares),
             unit="shares", as_of=shares_as_of or as_of, source=shares_ref,
             note="공시된 보통주 수량. 공시 이후 변동 반영은 보장하지 않음"),
    ]
    mktcap = last.close * shares
    out.append(Fact(id="VAL.MKTCAP", category="valuation", label="시가총액(보통주)", value=float(round(mktcap)),
                    unit="KRW", as_of=as_of, source="derived", inputs=["PX.CLOSE", "VAL.SHARES"],
                    note="종가 × 보통주 발행주식수. 우선주 제외"))
    if not reports:
        return out

    def derived(fid: str, label: str, value: float, unit: str, inputs: list[str], note: str) -> None:
        out.append(Fact(id=fid, category="valuation", label=label, value=_round(value, unit), unit=unit,
                        as_of=as_of, source="derived", inputs=inputs, note=note))

    latest = reports[0]
    equity = latest.accounts.get("total_equity")
    liabilities = latest.accounts.get("total_liabilities")
    eq_id = f"FIN.{latest.period}.TOTAL_EQUITY"

    for key, label in (("revenue", "매출액"), ("operating_income", "영업이익"), ("net_income", "당기순이익")):
        t = ttm(reports, key)
        if t:
            derived(f"VAL.{key.upper()}_TTM", f"최근 4분기 {label}", t[0], "KRW", t[1], "직전 사업연도 + 당해 누적 - 전년 동기 누적")

    ni = ttm(reports, "net_income")
    op = ttm(reports, "operating_income")
    rev = ttm(reports, "revenue")
    if ni and ni[0] > 0:
        derived("VAL.PER_TTM", "PER(최근 4분기)", mktcap / ni[0], "x", ["VAL.MKTCAP", "VAL.NET_INCOME_TTM"],
                "시가총액 / 최근 4분기 당기순이익. 지배주주 순이익이 아니라 증권사 PER과 다를 수 있음")
    elif ni:
        out.append(Fact(id="VAL.PER_TTM", category="valuation", label="PER(최근 4분기)", value=None, unit="text",
                        as_of=as_of, source="derived", inputs=["VAL.NET_INCOME_TTM"], note="최근 4분기 순손실로 PER 산출 불가"))
    if equity and equity.current and equity.current > 0:
        derived("VAL.PBR", "PBR", mktcap / equity.current, "x", ["VAL.MKTCAP", eq_id], f"{latest.period} 자본총계 기준")
        if ni:
            derived("VAL.ROE_TTM", "ROE(최근 4분기)", ni[0] / equity.current * 100, "%", ["VAL.NET_INCOME_TTM", eq_id],
                    "기말 자본 기준 단순 계산")
        if liabilities and liabilities.current is not None:
            derived("VAL.DEBT_RATIO", "부채비율", liabilities.current / equity.current * 100, "%",
                    [f"FIN.{latest.period}.TOTAL_LIABILITIES", eq_id], "부채총계 / 자본총계")
    if op and rev and rev[0] > 0:
        derived("VAL.OP_MARGIN_TTM", "영업이익률(최근 4분기)", op[0] / rev[0] * 100, "%",
                ["VAL.OPERATING_INCOME_TTM", "VAL.REVENUE_TTM"], "연결/별도는 입력 보고서 기준. 최근 4개 분기 영업이익 합계 / 매출액 합계 × 100. 최신 분기 단독 이익률이 아님.")
    return out


# ---- 뉴스 ----


def news_facts(articles) -> list[Fact]:
    out = []
    for a in articles:
        fid = f"NEWS.{hashlib.sha1(a.source_ref.encode()).hexdigest()[:8]}"
        out.append(Fact(
            id=fid, category="news", label=a.title, value=None, unit="text",
            as_of=a.published_at.astimezone(KST).date(), published_at=a.published_at,
            source=a.source_ref, note=a.summary or None, url=a.url,
        ))
    return out

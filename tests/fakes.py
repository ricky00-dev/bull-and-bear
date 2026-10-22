"""테스트용 가짜 데이터 소스와 에이전트."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from bullbear.agents import Attempt
from bullbear.data import (
    AccountValue, Disclosure, FinancialReport, MarketDataSource, NewsArticle, NewsSource, PriceBar, ShareCount,
)
from bullbear.schemas import Decision, ModeratorDecision, SideScore, Statement
from bullbear.snapshot import KST

AS_OF = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 18, 0, tzinfo=KST)  # 장 마감 후


class FakeSource(MarketDataSource):
    """300거래일 동안 종가가 100원에서 매일 1원씩 오르는 종목."""

    name = "fake"

    def get_daily_prices(self, ticker, start, end):
        bars = []
        d = AS_OF - timedelta(days=299)
        for i in range(300):
            close = 100.0 + i
            bars.append(PriceBar(d + timedelta(days=i), close, close + 1, close - 1, close, 1000 + i))
        return [b for b in bars if start <= b.date <= end]

    def get_financial_reports(self, ticker, as_of):
        h1 = FinancialReport(
            fiscal_year=2026, report_type="H1", filed_on=date(2026, 8, 14), consolidated=True, source_ref="DART:20260814000001",
            accounts={
                "revenue": AccountValue(current=300, ytd=600, prior_ytd=500),
                "operating_income": AccountValue(current=30, ytd=60, prior_ytd=40),
                "net_income": AccountValue(current=20, ytd=40, prior_ytd=30),
                "total_equity": AccountValue(current=2000),
                "total_liabilities": AccountValue(current=1000),
            },
        )
        fy25 = FinancialReport(
            fiscal_year=2025, report_type="FY", filed_on=date(2026, 3, 10), consolidated=True, source_ref="DART:20260310000001",
            accounts={
                "revenue": AccountValue(current=1100, ytd=1100),
                "operating_income": AccountValue(current=90, ytd=90),
                "net_income": AccountValue(current=70, ytd=70),
            },
        )
        return [h1, fy25]

    def get_share_count(self, ticker, as_of):
        return ShareCount(10, date(2026, 8, 14), "DART:20260814000001")

    def get_disclosures(self, ticker, start, end):
        return [Disclosure("DART:20261001000123", date(2026, 10, 1), "주요사항보고서(자기주식취득결정)", "가짜전자", "https://example")]


class FakeNews(NewsSource):
    name = "fake-news"

    def search(self, ticker, name, start, end):
        articles = [
            NewsArticle("https://news/1", datetime(2026, 10, 16, 9, 30, tzinfo=KST), "가짜전자, 자사주 1조 매입 결정", "요약", "https://news/1"),
            NewsArticle("https://news/2", datetime(2026, 10, 16, 19, 0, tzinfo=KST), "장 마감 뒤 기사", "요약", "https://news/2"),
        ]
        return [a for a in articles if start <= a.published_at <= end]


def statement(*evidence: tuple[str, str, float | None], argument: str | None = None) -> Statement:
    refs = " ".join(f"[{ref}]" for ref, _, _ in evidence)
    return Statement.model_validate({
        "claim": "테스트 주장",
        "argument": argument if argument is not None else f"근거는 {refs}이다.",
        "evidence": [{"ref": r, "source_id": s, "value": v, "interpretation": "설명"} for r, s, v in evidence],
    })


class ScriptedDebater:
    """정해진 발언을 순서대로 낸다. 첫 발언만 한 번 반려되게 할 수 있다."""

    def __init__(self, good: Statement, bad_first: Statement | None = None):
        self.good = good
        self.bad_first = bad_first
        self.calls = []

    def speak(self, side, round_kind, transcript, *, verify, question=None, on_event=None):
        self.calls.append((side, round_kind, len(transcript), question))
        attempts = []
        if self.bad_first is not None and len(self.calls) == 1:
            attempts.append(Attempt(self.bad_first, verify(self.bad_first)))
        attempts.append(Attempt(self.good, verify(self.good)))
        return attempts


class ScriptedModerator:
    def __init__(self, actions: list[str]):
        self.actions = list(actions)
        self.calls = []

    def evaluate(self, transcript, stats, *, extra_allowed):
        self.calls.append((len(transcript), stats, extra_allowed))
        action = self.actions.pop(0) if self.actions else "verdict"
        score = SideScore(relevance=3, materiality=3, rebuttal=3, risk_awareness=3, comment="")
        return ModeratorDecision(
            action=action, extra_question="자사주 매입 규모는?" if action == "extra_round" else None,
            bull=score, bear=score, decision=Decision.HOLD, confidence=0.5, reasoning="비슷함", decisive_evidence=[],
        )

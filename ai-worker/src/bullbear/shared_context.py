"""Projection of the frozen snapshot supplied identically to both debaters."""
from itertools import groupby

from .chart_data import csv_rows
from .snapshot import PUSH_MA_WINDOWS, Fact, Snapshot, chart_window_start, week_start

PRICE_IDS = (
    "PX.CLOSE", "PX.CHG_1D", "PX.VOL_20D", "MKT.KOSPI_CLOSE", "MKT.KOSPI_VOL_20D",
    *(f"PX.MA{n}" for n in PUSH_MA_WINDOWS),
    *(f"{prefix}{n}D" for n in (3, 7, 21)
      for prefix in ("PX.RET_", "MKT.KOSPI_RET_", "PX.EXCESS_KOSPI_")),
)
VALUATION_IDS = ("VAL.MKTCAP", "VAL.PER_TTM", "VAL.PBR", "VAL.ROE_TTM", "VAL.DEBT_RATIO")


def _observation(fact: Fact) -> dict:
    return {
        "source_id": fact.id, "value": fact.value, "unit": fact.unit,
        "label": fact.label, "as_of": fact.as_of.isoformat(), "source": fact.source,
        **fact.model_dump(mode="json", exclude_none=True,
            include={"note", "status", "report_period", "report_basis", "available_at", "vintage_date"}),
        **({"inputs": fact.inputs} if fact.inputs else {}),
    }


def fact_for_model(fact: Fact, *, exclude_none: bool = False) -> dict:
    data = fact.model_dump(mode="json", exclude_none=exclude_none)
    if fact.category == "news":
        data.pop("url", None)
        if fact.source.startswith(("https://", "http://")) or fact.source == fact.url:
            data["source"] = fact.publisher or "news"
    return data


def build_news_context(snapshot: Snapshot) -> dict:
    news = {"market": [], "company": []}
    for fact in snapshot.by_category("news"):
        news[fact.news_scope or "company"].append({
            "source_id": fact.id,
            "title": fact.label,
            "publisher": fact.publisher,
            "published_at": fact.published_at.isoformat() if fact.published_at else None,
            **({"summary": fact.note} if fact.note else {}),
            **({"event_id": fact.event_id} if fact.event_id else {}),
        })
    return {"market_news": news["market"], "stock_news": news["company"]}


def weekly_ohlcv(snapshot: Snapshot) -> list[dict]:
    start = chart_window_start(snapshot.as_of)
    bars = sorted((bar for bar in snapshot.series.stock_ohlcv if start <= bar.date <= snapshot.as_of),
                  key=lambda bar: bar.date)
    weekly = []
    for monday, rows in groupby(bars, key=lambda bar: week_start(bar.date)):
        week = list(rows)
        weekly.append({
            "week_start": monday.isoformat(), "last_trade_date": week[-1].date.isoformat(),
            "open": week[0].open, "high": max(bar.high for bar in week),
            "low": min(bar.low for bar in week), "close": week[-1].close,
            "volume": sum(bar.volume for bar in week),
        })
    return weekly


def build_shared_push(snapshot: Snapshot) -> dict:
    facts = snapshot.facts
    weekly_columns = ("week_start", "last_trade_date", "open", "high", "low", "close", "volume")
    financials = snapshot.by_category("financials")
    latest = next((f for f in financials if f.source != "derived"), None)
    latest_financials = [f for f in financials if latest is not None and f.as_of == latest.as_of
                         and f.report_period == latest.report_period and f.report_basis == latest.report_basis
                         and (f.source == latest.source or f.source == "derived")]
    return {
        "snapshot_id": snapshot.snapshot_id,
        "instrument": {"ticker": snapshot.ticker, "name": snapshot.name, "as_of": str(snapshot.as_of)},
        "time_context": {"decision_at": snapshot.decision_at.isoformat(),
                         "information_cutoff": snapshot.information_cutoff.isoformat()},
        "forecast_target": "판단 시점의 자료를 바탕으로 종목에 대한 BUY/HOLD/SELL 의견의 근거를 평가한다.",
        "chart_data": {
            "price_basis": snapshot.series.price_basis,
            "weekly_ohlcv_csv": csv_rows(weekly_columns, (
                (week[key] for key in weekly_columns) for week in weekly_ohlcv(snapshot)
            )),
            "metrics": [_observation(facts[key]) for key in PRICE_IDS if key in facts],
        },
        "market_data": [_observation(f) for f in snapshot.by_category("macro")],
        **build_news_context(snapshot),
        "financial_data": {
            "report_period": latest.report_period if latest else None,
            "report_basis": latest.report_basis if latest else None,
            "publication_date": latest.as_of.isoformat() if latest else None,
            "published_at": latest.published_at.isoformat() if latest and latest.published_at else None,
            "metrics": [_observation(f) for f in latest_financials]
                       + [_observation(facts[key]) for key in VALUATION_IDS if key in facts],
        },
        "data_status": snapshot.data_status,
        "warnings": snapshot.warnings,
    }

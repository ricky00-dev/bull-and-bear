"""Fixture data, real snapshot/graph code and deterministic model doubles."""
from base64 import b64decode
import csv
from dataclasses import replace
from datetime import date, datetime, timedelta
from io import StringIO
import json
import math
from types import SimpleNamespace

import pytest

from bullbear.data import Disclosure, NewsArticle, PriceBar, ShareCount
from bullbear.data.macro import MacroReading
from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.shared_context import build_shared_push
from bullbear.snapshot import KST, Snapshot, build_snapshot
from bullbear.server.store import Store
from bullbear.tools import DEBATE_TOOL_DEFINITIONS, SnapshotTools

from .prompt_helpers import initial_payload
from .fakes import AS_OF, NOW, FakeNews, FakeSource
from .graph_fakes import GraphLLM


def index_loader(code, start, end):
    assert code == "KOSPI"
    return [(b.date, b.close + 1000) for b in FakeSource().get_daily_prices("", start, end)]


class WindowSource(FakeSource):
    def __init__(self, sessions):
        self.sessions = sessions

    def get_daily_prices(self, ticker, start, end):
        return super().get_daily_prices(ticker, start, end)[-self.sessions:]


@pytest.mark.parametrize("sessions,missing", [(229, 0), (228, 1), (199, 30)])
def test_ohlcv_dates_moving_average_windows_and_kospi_volatility(sessions, missing):
    snap = build_snapshot(WindowSource(sessions), "000000", "가짜전자", now=NOW, index_loader=index_loader)
    series = snap.series.model_dump(mode="json")
    expected_dates = [str(AS_OF - timedelta(days=i)) for i in reversed(range(30))]
    assert series["stock_ohlcv"][-30:] == [
        {"date": day, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 900 + p}
        for day, p in zip(expected_dates, range(370, 400), strict=True)
    ]
    assert series["kospi_close"][-30:] == [
        {"date": day, "close": p} for day, p in zip(expected_dates, range(1370, 1400), strict=True)
    ]
    for n in (7, 11, 24, 25, 200):
        key = f"PX.MA{n}"
        all_points = series["moving_averages"][key]
        assert [p["date"] for p in all_points] == [bar["date"] for bar in series["stock_ohlcv"]]
        points = all_points[-30:]
        assert [p["date"] for p in points] == expected_dates
        expected = [p - (n - 1) / 2 for p in range(370, 400)]
        if n == 200:
            expected[:missing] = [None] * missing
        assert [p["value"] for p in points] == expected
        if expected[-1] is not None:
            assert snap.facts[key].value == expected[-1]
        else:
            assert key not in snap.facts
    returns = [math.log(n / (n - 1)) for n in range(1380, 1400)]
    variance = sum((r - sum(returns) / 20) ** 2 for r in returns) / 19
    assert snap.facts["MKT.KOSPI_VOL_20D"].value == round(math.sqrt(variance * 252) * 100, 2)
    assert {"PX.MA20", "PX.MA60", "PX.MA120", "PX.VOL_20D", "PX.EXCESS_KOSPI_7D"} <= snap.facts.keys()
    assert snap.data_status["moving_averages"] == "EMPTY"  # fewer than 325 bars for the full chart


def test_unadjusted_price_split_warning_keeps_raw_values():
    class Unadjusted(FakeSource):
        price_basis = "unadjusted"

        def get_daily_prices(self, ticker, start, end):
            bars = super().get_daily_prices(ticker, start, end)
            last = bars[-1]
            return bars[:-1] + [replace(last, open=200, high=201, low=199, close=200)]

    snap = build_snapshot(Unadjusted(), "000000", "가짜전자", now=NOW)
    assert snap.series.price_basis == "unadjusted"
    assert snap.series.stock_ohlcv[-1].close == snap.facts["PX.CLOSE"].value == 200
    assert any("30% 초과 단절" in warning for warning in snap.warnings)


def test_snapshot_hash_includes_series_and_sqlite_keeps_first_creation(tmp_path):
    class RevisedCandle(FakeSource):
        def get_daily_prices(self, ticker, start, end):
            bars = super().get_daily_prices(ticker, start, end)
            bars[-30] = replace(bars[-30], volume=99999)
            return bars

    base = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    revised = build_snapshot(RevisedCandle(), "000000", "가짜전자", now=NOW)
    assert base.facts == revised.facts and base.snapshot_id != revised.snapshot_id
    later = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW + timedelta(minutes=1))
    assert later.snapshot_id == base.snapshot_id
    store = Store(tmp_path)
    try:
        row, _ = store.create("first", "first", base.ticker, str(base.as_of), 2)
        store.save_snapshot(row["id"], base)
        store.save_snapshot(row["id"], later)
        assert Snapshot.model_validate(store.snapshot(base.snapshot_id)) == base
    finally:
        store.close()


def test_legacy_snapshot_reads_without_v2_fields(tmp_path):
    legacy = {"snapshot_id": "old", "ticker": "000000", "name": "가짜전자", "as_of": str(AS_OF),
              "created_at": NOW.isoformat(), "provider": "legacy", "facts": {
                  "PX.CLOSE": {"id": "PX.CLOSE", "category": "price", "label": "종가", "value": 399,
                               "unit": "KRW/share", "as_of": str(AS_OF), "source": "legacy"}
              }, "warnings": []}
    store = Store(tmp_path)
    try:
        with store.transaction() as db:
            db.execute("INSERT INTO snapshots VALUES (?, ?)", ("old", json.dumps(legacy)))
        assert store.snapshot("old") == legacy
        snap = Snapshot.model_validate(store.snapshot("old"))
    finally:
        store.close()
    assert snap.schema_version == 1 and snap.time_context is None
    assert snap.decision_at == snap.information_cutoff == NOW
    assert list(csv.DictReader(StringIO(build_shared_push(snap)["chart_data"]["weekly_ohlcv_csv"]))) == []
    assert json.loads(SnapshotTools(snap)("get_price_metrics", {}))["items"][0]["id"] == "PX.CLOSE"


def test_future_availability_and_same_day_dart_cannot_enter_snapshot():
    class LateDart(FakeSource):
        def get_financial_reports(self, ticker, as_of):
            assert as_of == AS_OF - timedelta(days=1)
            return [replace(super().get_financial_reports(ticker, as_of)[0], filed_on=AS_OF)]

        def get_share_count(self, ticker, as_of):
            return ShareCount(10, AS_OF, "late-share-count")

        def get_disclosures(self, ticker, start, end):
            return [Disclosure("late", AS_OF, "늦은 공시", "발행사", "https://example.com")]

    late_macro = MacroReading("MACRO.VIX", "VIX", "index_points", "FRED:VIXCLS", "OK", 20,
                              AS_OF - timedelta(days=1), NOW)
    snap = build_snapshot(LateDart(), "000000", "가짜전자", now=NOW, news=FakeNews(),
                          macro=SimpleNamespace(collect=lambda cutoff: [late_macro]))
    assert snap.time_context.information_cutoff == datetime(2026, 10, 16, 15, 30, tzinfo=KST)
    assert snap.decision_at == snap.time_context.information_cutoff
    assert not any(snap.by_category(c) for c in ("financials", "valuation", "disclosure", "macro"))
    assert snap.data_status["financials"] == snap.data_status["valuation"] == "AVAILABILITY_UNVERIFIED"
    assert snap.data_status["MACRO.VIX"] == "AVAILABILITY_UNVERIFIED"
    assert len(snap.by_category("news")) == 1


class HeadlineSource(FakeNews):
    def search_market(self, start, end):
        def article(key, title, hours=10):
            return NewsArticle(f"https://example.com/{key}", datetime(2026, 10, 16, hours, tzinfo=KST),
                title, "PRIVATE_MARKET_SNIPPET", f"https://example.com/{key}", "example.com")
        return [
            article("repost", "[속보] 가짜전자, 자사주 1조 매입 결정"),
            article("low", "고용 동향"),
            article("market", "한국은행 금통위 기준금리 발표에 코스피 변동"),
            article("late", "한국은행과 환율 장 마감 이후", 16),
        ]


def test_graph_bull_bear_get_identical_push_and_cite_without_tool_calls(tmp_path):
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, index_loader=index_loader,
                          news=HeadlineSource(), market_news_limit=1)
    market_fact = next(fact for fact in snap.by_category("news") if fact.news_scope == "market")

    class NewsDebater(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if self.count == 1:
                raw["argument"] = "시황 기사 요약을 근거로 보되 전망은 여전히 불확실해요 [E1]."
                raw["evidence"][0].update(source_id=market_fact.id, value=None)
            return raw

    bull = NewsDebater(snap)
    bear, moderator, reviewer = (GraphLLM(snap) for _ in range(3))
    events = []
    run = GraphRuntime(snap, debate_id="shared-push", bull=bull, bear=bear, moderator=moderator,
                       statement_reviewers={"bull": reviewer},
                       log=EventLog(tmp_path / "events.jsonl"), emit=lambda name, data: events.append((name, data)))
    assert run.run()["verdict"]["decisive_evidence"] == ["PX.CLOSE"]
    assert all(name != "tool_call" for name, _ in events)
    left = initial_payload(bull.calls[0][0])
    right = initial_payload(bear.calls[0][0])
    assert left["assigned_outlook"] != right["assigned_outlook"] and left["history"] == right["history"] == []
    push = left["shared_push"]
    assert push == right["shared_push"] == build_shared_push(snap)
    assert push["snapshot_id"] == snap.snapshot_id
    chart = push["chart_data"]
    assert set(chart) == {"price_basis", "weekly_ohlcv_csv", "metrics"}
    assert len(list(csv.DictReader(StringIO(chart["weekly_ohlcv_csv"])))) == 10
    prefix = bull.calls[0][0].messages[0]
    block, = prefix['content']
    assert block['cache_control'] == {'type': 'ephemeral', 'ttl': '5m'}
    fixed = json.loads(block['text'])
    assert set(fixed) == {'ticker', 'name', 'price_as_of', 'shared_push',
                          'return_context', 'source_context', 'decision_at'}
    for client in (bull, bear):
        assert len(client.calls) == 3
        for round_index, (conv, _) in enumerate(client.calls):
            assert conv.messages[0] == prefix
            assert all(message['role'] == 'user' for message in conv.messages[:-1])
            assert conv.messages[-1]['role'] == 'system'
            request = json.loads(conv.messages[1]['content'])
            assert not fixed.keys() & request.keys()
            assert 'task' in request and len(request['history']) == 2 * round_index
    bull_system, bear_system, mediator_system = (client.calls[0][0].system for client in (bull, bear, moderator))
    assert bull_system == bear_system == mediator_system
    left_image, = bull.calls[0][0].messages[2]["content"]
    right_image, = bear.calls[0][0].messages[2]["content"]
    assert left_image == right_image and left_image["type"] == "image"
    assert left_image["source"]["media_type"] == "image/png"
    png = b64decode(left_image["source"]["data"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert tuple(int.from_bytes(png[i:i + 4], "big") for i in (16, 20)) == (840, 560)
    assert all(len(conv.messages) == 3 for side in (bull, bear) for conv, _ in side.calls[1:])
    market, = push["market_news"]
    stock, = push["stock_news"]
    assert market["publisher"] == "example.com" and market["title"].startswith("한국은행")
    assert stock["title"].startswith("가짜전자")
    assert set(stock) == set(market) == {"source_id", "title", "publisher", "published_at", "summary", "event_id"}
    assert market["summary"] == "PRIVATE_MARKET_SNIPPET"
    assert snap.facts[market["source_id"]].event_id.startswith("EVT.")
    assert all(a["source_id"] in snap.facts for a in (stock, market))
    assert push["financial_data"]["report_basis"] == "consolidated"
    assert push["financial_data"]["published_at"] is None
    assert "FIN.2026H1.REVENUE_YOY" in {f["source_id"] for f in push["financial_data"]["metrics"]}
    mod = initial_payload(moderator.calls[0][0])
    assert mod["snapshot_id"] == snap.snapshot_id and mod["facts"]["PX.CLOSE"]["value"] == 399
    assert mod["facts"][market_fact.id]["note"] == market_fact.note
    assert "shared_push" not in mod and "stock_ohlcv" not in mod
    assert initial_payload(reviewer.calls[0][0])["facts"][market_fact.id]["note"] == market_fact.note
    for client in (bull, bear, moderator, reviewer):
        for conv, _ in client.calls:
            assert all(fact.url not in json.dumps(initial_payload(conv)) for fact in snap.by_category("news"))
    opening = next(payload["statement"] for name, payload in events
                   if name == "statement_accepted" and payload["round"] == "opening" and payload["side"] == "bull")
    assert opening.evidence[0].observation.url == market_fact.url


def test_get_new_url_only_returns_the_requested_snapshot_news_link():
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, news=HeadlineSource())
    market = next(fact for fact in snap.by_category("news") if fact.news_scope == "market")
    definitions = {tool["name"]: tool for tool in DEBATE_TOOL_DEFINITIONS}
    assert "get_news" not in definitions
    assert definitions["get_new_url"]["input_schema"]["required"] == ["source_id"]
    tools = SnapshotTools(snap)
    assert json.loads(tools("get_new_url", {"source_id": market.id})) == {
        "source_id": market.id, "url": market.url,
    }
    for arguments in ({}, {"source_id": "NEWS.missing"}, {"source_id": "PX.CLOSE"},
                      {"source_id": market.id, "url": "https://example.com/untrusted"}):
        with pytest.raises(ValueError):
            tools("get_new_url", arguments)
    market.url = None
    assert json.loads(tools("get_new_url", {"source_id": market.id})) == {
        "source_id": market.id, "note": "저장된 원문 URL이 없습니다",
    }


@pytest.mark.parametrize("availability", ["matching", "revised", "failed"])
def test_dart_cash_flow_requires_same_report_and_currency(tmp_path, availability):
    from bullbear.data import DataUnavailable
    from bullbear.data.pykrx_dart import PykrxDartSource

    class Dart:
        def corp_code(self, ticker):
            return "test-corp"

        def get(self, endpoint, **params):
            if endpoint == "fnlttSinglAcntAll":
                assert params["fs_div"] == "CFS" and params["reprt_code"] == "11012"
                if availability == "failed":
                    raise DataUnavailable("optional endpoint unavailable")
                receipt = "20261101000001" if availability == "revised" else "20260814000001"
                return {"list": [
                    {"sj_div": "CF", "rcept_no": receipt, "currency": "KRW", "account_nm": "영업활동현금흐름",
                     "thstrm_amount": "4,200"},
                    {"sj_div": "CF", "rcept_no": receipt, "currency": "USD", "account_nm": "영업활동현금흐름",
                     "thstrm_amount": "999"},
                ]}
            assert endpoint == "fnlttSinglAcnt"
            if params["bsns_year"] == "2026" and params["reprt_code"] == "11012":
                return {"list": [{"fs_div": "CFS", "account_nm": "매출액", "thstrm_add_amount": "600",
                                  "rcept_no": "20260814000001"}]}
            return None

    class Source(PykrxDartSource):
        def get_daily_prices(self, *args):
            return FakeSource().get_daily_prices(*args)

        def get_share_count(self, *args):
            return None

        def get_disclosures(self, *args):
            return []

    source = Source(None, tmp_path)
    source._dart = Dart()
    snap = build_snapshot(source, "000000", "가짜전자", now=NOW)
    assert "FIN.2026H1.REVENUE_YTD" in snap.facts
    key = "FIN.2026H1.OPERATING_CASH_FLOW"
    if availability == "matching":
        assert snap.facts[key].value == 4200 and snap.facts[key].report_basis == "consolidated"
        assert any(item["source_id"] == key for item in build_shared_push(snap)["financial_data"]["metrics"])
    else:
        assert key not in snap.facts


def test_weekly_push_aggregates_calendar_weeks_and_stops_at_partial_week():
    class Weekdays(FakeSource):
        def get_daily_prices(self, ticker, start, end):
            return [b for b in super().get_daily_prices(ticker, start, end) if b.date.weekday() < 5]

    now = NOW - timedelta(days=2)  # Wednesday, before the fixture's last available candle.
    snap = build_snapshot(Weekdays(), "000000", "가짜전자", now=now)
    weekly = list(csv.DictReader(StringIO(build_shared_push(snap)["chart_data"]["weekly_ohlcv_csv"])))
    assert len(weekly) == 10
    assert weekly[0]["week_start"] == "2026-08-10"
    assert weekly[-2] == {
        "week_start": "2026-10-05", "last_trade_date": "2026-10-09",
        "open": "388", "high": "393", "low": "387", "close": "392", "volume": "6450",
    }
    assert weekly[-1] == {
        "week_start": "2026-10-12", "last_trade_date": "2026-10-14",
        "open": "395", "high": "398", "low": "394", "close": "397", "volume": "3888",
    }


def test_bull_bear_can_query_daily_chart_from_same_frozen_snapshot(tmp_path):
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, index_loader=index_loader)
    day = AS_OF - timedelta(days=60)
    observed = []

    class DailyChartLLM(GraphLLM):
        def structured(self, conv, *, schema, **kwargs):
            assert any(tool["name"] == "get_daily_chart" for tool in kwargs["tools"])
            if initial_payload(conv)["round"] == "opening":
                data = kwargs["tool_handler"]("get_daily_chart", {"start_date": str(day), "end_date": str(day)})
                observed.append(json.loads(data))
            return super().structured(conv, schema=schema, **kwargs)

    GraphRuntime(snap, debate_id="daily-query", bull=DailyChartLLM(snap), bear=DailyChartLLM(snap),
                 moderator=GraphLLM(snap), log=EventLog(tmp_path / "daily.jsonl")).run()
    left, right = observed
    assert left == right
    assert left["snapshot_id"] == snap.snapshot_id
    assert left["coverage_start"] == str(AS_OF - timedelta(days=125))
    assert list(csv.DictReader(StringIO(left["daily_ohlcv_csv"]))) == [{
        "date": str(day), "open": "339", "high": "340", "low": "338", "close": "339", "volume": "1239",
        "ma7": "336", "ma11": "334", "ma25": "327", "ma200": "239.5", "kospi_close": "1339",
    }]


@pytest.mark.parametrize("start,end", [
    ("2026-10-16", "2026-10-17"), ("2026-10-02", "2026-10-16"),
    ("2026-10-16", "2026-10-15"), ("20261016", "2026-10-16"), ("bad", "2026-10-16"),
])
def test_daily_chart_rejects_future_oversize_and_invalid_ranges(start, end):
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    with pytest.raises(ValueError):
        SnapshotTools(snap)("get_daily_chart", {"start_date": start, "end_date": end})


def test_old_snapshot_daily_range_returns_only_available_rows():
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    old = snap.model_copy(update={"series": snap.series.model_copy(update={
        "stock_ohlcv": snap.series.stock_ohlcv[-30:],
        "moving_averages": {key: points[-30:] for key, points in snap.series.moving_averages.items()
                            if key != "PX.MA25"},
    })})
    chart = build_shared_push(old)["chart_data"]
    assert 0 < len(list(csv.DictReader(StringIO(chart["weekly_ohlcv_csv"])))) < 10
    items = json.loads(SnapshotTools(old)("get_daily_chart", {
        "start_date": "2026-08-10", "end_date": "2026-08-11"}))
    assert list(csv.DictReader(StringIO(items["daily_ohlcv_csv"]))) == []
    assert items["coverage_start"] == "2026-09-17"
    saved = json.loads(SnapshotTools(old)("get_daily_chart", {
        "start_date": "2026-10-16", "end_date": "2026-10-16"}))
    row, = list(csv.DictReader(StringIO(saved["daily_ohlcv_csv"])))
    assert row["ma25"] == "387"


@pytest.mark.parametrize("sessions,first_ma200", [(324, None), (325, 199.5)])
def test_half_year_image_uses_126_sessions_and_ma200_needs_325_bars(monkeypatch, sessions, first_ma200):
    from bullbear import chart_image

    class TradingHistory(FakeSource):
        def get_daily_prices(self, ticker, start, end):
            days = [end - timedelta(days=i) for i in reversed(range((end - start).days + 1))]
            sessions_in_range = [day for day in days if day.weekday() < 5][-sessions:]
            return [PriceBar(day, close, close + 1, close - 1, close, 1000)
                    for close, day in enumerate(sessions_in_range, start=100)]

    snap = build_snapshot(TradingHistory(), "000000", "가짜전자", now=NOW)
    assert len(snap.series.stock_ohlcv) == 126
    ma200 = snap.series.moving_averages["PX.MA200"]
    assert len(ma200) == 126 and ma200[0].value == first_ma200
    assert (snap.data_status["moving_averages"] == "OK") == (first_ma200 is not None)
    captured = []

    def render(_, bars):
        captured.extend(bars)
        return b"fixture png"

    monkeypatch.setattr(chart_image, "_render_png", render)
    assert chart_image.daily_chart_image(snap) is not None
    assert captured == snap.series.stock_ohlcv
    assert captured[-1].date == AS_OF
    assert len(list(csv.DictReader(StringIO(build_shared_push(snap)["chart_data"]["weekly_ohlcv_csv"])))) == 10

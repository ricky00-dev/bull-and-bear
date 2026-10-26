"""HTTP 서버: 계약(docs/worker-api.md) 형식, 멱등, 이어 받기, 재시작, 대기열 상한. LLM·외부 API 없이 가짜로."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from bullbear.config import Settings
from bullbear.llm import Usage
from bullbear.server.app import create_app
from bullbear.server.debate_runner import Agents, run_debate
from bullbear.server.market import Market, choseong
from bullbear.snapshot import KST, build_snapshot, confirmed_bars

from .fakes import NOW, FakeNews, FakeSource, ScriptedDebater, ScriptedModerator, statement

TOKEN = {"X-Worker-Token": "t"}


class FakeIndex:
    def get_daily_closes(self, code, start, end):
        rows = [(date(2026, 10, d), 2500.0 + d) for d in (14, 15, 16)]
        return [r for r in rows if start <= r[0] <= end]


def settings(tmp_path, **kw) -> Settings:
    base = Settings(model="fake", dart_api_key=None, naver_client_id=None, naver_client_secret=None,
                    data_dir=tmp_path, debater_effort="low", moderator_effort="low", worker_token="t")
    return replace(base, **kw)


def fake_runner(s: Settings, *, gate: threading.Event | None = None):
    def runner(run):
        if gate is not None:
            gate.wait(5)
        good = statement(("E1", "PX.CLOSE", 399))
        bad = statement(("E1", "PX.CLOSE", 1.0))
        run_debate(run, s, snapshot=lambda t, n: build_snapshot(FakeSource(), t, n, news=FakeNews(), now=NOW),
                   agents=lambda snap: Agents(ScriptedDebater(good, bad), ScriptedModerator([]),
                                              lambda: [("claude-haiku-5-5", Usage(100, 20, 50, 10, 6))]))
    return runner


def make_client(tmp_path, gate=None, **kw) -> TestClient:
    s = settings(tmp_path, **kw)
    market = Market(FakeSource(), index=FakeIndex(), now=lambda: NOW)
    return TestClient(create_app(s, market=market, runner=fake_runner(s, gate=gate)))


def read_events(client, debate_id, last_event_id=None) -> list[tuple[int, str, dict]]:
    headers = dict(TOKEN)
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    out, seq, kind = [], None, None
    with client.stream("GET", f"/debates/{debate_id}/events", headers=headers) as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        for line in res.iter_lines():
            if line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                out.append((seq, kind, json.loads(line[6:])))
    return out


def start(client, request_id="req-1", ticker="005930"):
    res = client.post("/debates", json={"ticker": ticker, "request_id": request_id, "max_extra_rounds": 1}, headers=TOKEN)
    assert res.status_code == 202, res.text
    return res.json()


def test_token_required(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/stocks/005930").status_code == 401
    assert client.get("/stocks/005930", headers={"X-Worker-Token": "wrong"}).json()["error"]["code"] == "UNAUTHORIZED"


def test_search_by_choseong_and_stock_detail(tmp_path):
    client = make_client(tmp_path)
    assert choseong("삼성전자") == "ㅅㅅㅈㅈ"
    items = client.get("/stocks/search", params={"q": "ㅅㅅㅈㅈ"}, headers=TOKEN).json()["items"]
    assert items[0]["ticker"] == "005930" and items[0]["close"] == 399 and items[0]["eligible"]

    detail = client.get("/stocks/005930", headers=TOKEN).json()
    assert detail["as_of"] == "2026-10-16" and len(detail["sparkline"]) == 60
    assert client.get("/stocks/999999", headers=TOKEN).json()["error"]["code"] == "NOT_FOUND"


def test_debate_events_follow_contract(tmp_path):
    client = make_client(tmp_path)
    started = start(client)
    assert started["status"] in ("queued", "running") and started["reused"] is False
    # 같은 멱등 키 → 같은 토론
    assert start(client)["debate_id"] == started["debate_id"]

    events = read_events(client, started["debate_id"])
    kinds = [k for _, k, _ in events]
    assert kinds[0] == "snapshot_created" and kinds[-1] == "debate_completed"
    assert [s for s, _, _ in events] == list(range(1, len(events) + 1))
    assert kinds.count("statement_accepted") == 6 and kinds.count("statement_rejected") == 1
    assert "token" not in kinds

    snap = events[0][2]
    assert snap["as_of"] == "2026-10-16" and snap["close"] == 399
    rejected = next(d for _, k, d in events if k == "statement_rejected")
    assert rejected["side"] == "bull" and rejected["issues"][0]["code"] == "value_mismatch"
    accepted = next(d for _, k, d in events if k == "statement_accepted")
    assert accepted["attempts"] == 2 and accepted["statement"]["evidence"][0]["source_id"] == "PX.CLOSE"
    done = events[-1][2]
    assert done["verdict"]["decision"] == "HOLD" and set(done["verdict"]["scores"]) == {"bull", "bear"}
    assert done["usage"]["calls"][0] == {"model": "claude-haiku-5-5", "input_tokens": 100, "output_tokens": 20,
                                         "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10}

    # 끊겼다 다시 붙으면 Last-Event-ID 뒤부터
    resumed = read_events(client, started["debate_id"], last_event_id=3)
    assert resumed[0][0] == 4 and len(resumed) == len(events) - 3

    detail = client.get(f"/debates/{started['debate_id']}", headers=TOKEN).json()
    assert detail["status"] == "completed" and len(detail["statements"]) == 6 and detail["verdict"]["decision"] == "HOLD"
    assert client.get(f"/snapshots/{snap['snapshot_id']}", headers=TOKEN).json()["facts"]["PX.CLOSE"]["value"] == 399


def test_unfinished_debate_fails_after_restart(tmp_path):
    gate = threading.Event()
    first = make_client(tmp_path, gate=gate)
    debate_id = start(first)["debate_id"]
    # 워커가 죽었다고 치고, 같은 데이터 폴더로 새 서버를 띄운다
    second = make_client(tmp_path)
    events = read_events(second, debate_id)
    assert events[-1][1] == "debate_failed" and events[-1][2]["error"]["code"] == "WORKER_RESTARTED"
    gate.set()


def test_busy_when_queue_full(tmp_path):
    gate = threading.Event()
    client = make_client(tmp_path, gate=gate, max_concurrent_debates=1, max_queued_debates=1)
    start(client, "a")
    res = client.post("/debates", json={"ticker": "000660", "request_id": "b"}, headers=TOKEN)
    assert res.status_code == 429 and res.json()["error"]["code"] == "BUSY" and res.headers["Retry-After"]
    gate.set()


def test_scoring_prices_use_confirmed_closes(tmp_path):
    client = make_client(tmp_path)
    prices = client.get("/prices/daily", params={"ticker": "005930", "from": "2026-10-14", "to": "2026-10-16"},
                        headers=TOKEN).json()["items"]
    assert [p["date"] for p in prices] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    index = client.get("/indices/daily", params={"code": "KOSPI", "from": "2026-10-15", "to": "2026-10-20"},
                       headers=TOKEN).json()["items"]
    assert index == [{"date": "2026-10-15", "close": 2515.0}, {"date": "2026-10-16", "close": 2516.0}]


def test_intraday_bar_is_not_used():
    bars = FakeSource().get_daily_prices("x", date(2026, 10, 10), date(2026, 10, 16))
    during = datetime(2026, 10, 16, 11, 0, tzinfo=KST)
    assert confirmed_bars(bars, during)[-1].date == date(2026, 10, 15)
    assert confirmed_bars(bars, NOW)[-1].date == date(2026, 10, 16)
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=during)
    assert snap.as_of == date(2026, 10, 15)

"""에이전트용 데이터 조회 도구.

도구는 스냅샷에 묶여 있다. 모델은 스냅샷 ID를 고를 수 없고, 토론 시작 시 고정된
스냅샷의 데이터만 받는다. 근거 Fact에는 인용할 id가 붙는다.
"""

from __future__ import annotations

import json
from datetime import date

from .chart_data import chart_averages, csv_rows
from .snapshot import Category, Snapshot

_NO_INPUT = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

TOOL_CATEGORIES: dict[str, Category] = {
    "get_price_metrics": "price",
    "get_financials": "financials",
    "get_valuation": "valuation",
    "get_disclosures": "disclosure",
}

TOOL_DEFINITIONS = [
    {
        "name": "get_price_metrics",
        "description": "종가, 기간 수익률, 코스피 수익률과 종목 초과수익률(3·7·21거래일, 자료가 있는 경우), 52주 최고·최저, 이동평균, 변동성, 거래량 지표를 조회한다. 모두 과거 관측값이며 미래 예측값이 아니다.",
        "input_schema": _NO_INPUT,
    },
    {
        "name": "get_financials",
        "description": "DART 정기보고서의 매출액·영업이익·순이익·자산·부채·자본을 조회한다. 최신 보고서와 최근 사업보고서 2개.",
        "input_schema": _NO_INPUT,
    },
    {
        "name": "get_valuation",
        "description": "시가총액, PER, PBR, ROE, 부채비율, 영업이익률 등 계산 지표와 계산식을 조회한다.",
        "input_schema": _NO_INPUT,
    },
    {
        "name": "get_disclosures",
        "description": "최근 90일 DART 공시 제목 목록을 조회한다. 본문은 없다.",
        "input_schema": _NO_INPUT,
    },
    {
        "name": "get_new_url",
        "description": "출처 주소가 필요할 때 제공된 뉴스 Fact ID 하나의 원문 URL을 조회한다. 스냅샷에 저장된 주소만 반환하며 링크를 열지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"source_id": {"type": "string", "description": "제공된 뉴스 Fact의 source_id"}},
            "required": ["source_id"],
            "additionalProperties": False,
        },
    },
]


_DAILY_CHART_MAX_DAYS = 14
DEBATE_TOOL_DEFINITIONS = [
    *TOOL_DEFINITIONS,
    {
        "name": "get_daily_chart",
        "description": (
            "스냅샷에 보관된 지정 구간의 일봉 OHLCV, 일별 MA7/11/25/200, 코스피 종가를 CSV로 조회한다. "
            "시작일·종료일을 포함해 최대 14달력일이며 종료일은 종목 기준일을 넘을 수 없다. "
            "하루만 조회할 때는 두 날짜를 같게 입력한다. 반환된 일별 행은 차트 자료다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "시작일 (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "종료일 (YYYY-MM-DD)"},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
    },
]


class SnapshotTools:
    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot

    def __call__(self, name: str, _input: dict) -> str:
        if name == "get_daily_chart":
            return self._daily_chart(_input)
        if name == "get_new_url":
            return self._news_url(_input)
        category = TOOL_CATEGORIES.get(name)
        if category is None:
            raise ValueError(f"알 수 없는 도구: {name}")
        facts = self.snapshot.by_category(category)
        if not facts:
            return json.dumps({"snapshot_id": self.snapshot.snapshot_id, "items": [], "note": "데이터 없음"}, ensure_ascii=False)
        items = [
            {
                k: v
                for k, v in {
                    "id": f.id,
                    "label": f.label,
                    "value": f.value,
                    "display": f"약 {f.value / 1e12:,.2f}조 원" if f.unit == "KRW" and f.value is not None and abs(f.value) >= 1e12 else None,
                    "unit": f.unit,
                    "as_of": f.as_of.isoformat(),
                    "published_at": f.published_at.isoformat() if f.published_at else None,
                    "inputs": f.inputs or None,
                    "note": f.note or None,
                    "report_period": f.report_period,
                    "report_basis": f.report_basis,
                    "scope": f.news_scope,
                    "publisher": f.publisher,
                    "event_id": f.event_id,
                    "url": f.url,
                }.items()
                if v is not None or k == "value"
            }
            for f in facts
        ]
        return json.dumps({"snapshot_id": self.snapshot.snapshot_id, "items": items}, ensure_ascii=False)

    def _news_url(self, arguments: dict) -> str:
        source_id = arguments.get("source_id")
        if set(arguments) != {"source_id"} or not isinstance(source_id, str):
            raise ValueError("source_id에 제공된 뉴스 Fact ID 하나를 입력하세요")
        fact = self.snapshot.facts.get(source_id)
        if fact is None or fact.category != "news":
            raise ValueError("스냅샷에 해당 뉴스 Fact가 없습니다")
        address = {"url": fact.url} if fact.url else {"note": "저장된 원문 URL이 없습니다"}
        return json.dumps({"source_id": fact.id, **address}, ensure_ascii=False)

    def _daily_chart(self, arguments: dict) -> str:
        try:
            if set(arguments) != {"start_date", "end_date"}:
                raise ValueError
            start, end = (date.fromisoformat(arguments[key]) for key in ("start_date", "end_date"))
            if start.isoformat() != arguments["start_date"] or end.isoformat() != arguments["end_date"]:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("start_date와 end_date는 YYYY-MM-DD 날짜여야 합니다") from None
        if start > end or (end - start).days >= _DAILY_CHART_MAX_DAYS:
            raise ValueError("시작일부터 종료일까지 1~14달력일을 선택하세요")
        if end > self.snapshot.as_of:
            raise ValueError("종료일이 스냅샷 기준일 이후입니다")

        series = self.snapshot.series
        averages = chart_averages(self.snapshot)
        kospi = {p.date: p.close for p in series.kospi_close}
        columns = ("date", "open", "high", "low", "close", "volume",
                   *(key.removeprefix("PX.").lower() for key in averages), "kospi_close")
        rows = ((bar.date.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume,
                 *(points.get(bar.date) for points in averages.values()), kospi.get(bar.date))
                for bar in series.stock_ohlcv if start <= bar.date <= end)
        return json.dumps({
            "snapshot_id": self.snapshot.snapshot_id, "price_basis": series.price_basis,
            "coverage_start": min((bar.date.isoformat() for bar in series.stock_ohlcv), default=None),
            "coverage_end": max((bar.date.isoformat() for bar in series.stock_ohlcv), default=None),
            "daily_ohlcv_csv": csv_rows(columns, rows),
        }, ensure_ascii=False)

"""에이전트용 데이터 조회 도구.

도구는 스냅샷에 묶여 있다. 모델은 스냅샷 ID를 고를 수 없고, 토론 시작 시 고정된
스냅샷의 데이터만 받는다. 근거 Fact에는 인용할 id가 붙는다.
"""

from __future__ import annotations

import json
import re
from datetime import date

from .chart_data import chart_averages, csv_rows
from .shared_context import fact_table_csv, ordered_news
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
_FACT_BATCH_SIZE = 8
_FACT_TABLE_MAX_CHARS = 8000
_CATALOG_PAGE_SIZE = 20
_NEWS_PAGE_SIZE = 5
DEBATE_TOOL_DEFINITIONS = [
    {
        "name": "read_snapshot",
        "description": (
            "Read frozen data. args: facts=[id,...] (1-8); "
            "catalog=[category,offset] (20 ids/page; price|financials|valuation|disclosure|news|macro); "
            "news=[company|market,offset] (5/page); chart=[start,end] (YYYY-MM-DD,1-14 days). "
            "Offset is a string, initially '0'; use next_offset for later pages."
        ),
        "input_schema": {
            "type": "object", "properties": {
                "kind": {"type": "string", "enum": ["facts", "catalog", "news", "chart"]},
                "args": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": _FACT_BATCH_SIZE},
            }, "required": ["kind", "args"], "additionalProperties": False,
        },
    },
    {
        "name": "get_news_body",
        "description": "read_snapshot으로 요약을 읽은 뒤 필요한 정보가 없을 때 기사 source_id로 본문을 조회한다. 먼저 호출하면 요약을 반환한다.",
        "input_schema": {
            "type": "object", "properties": {"source_id": {"type": "string", "description": "제공된 뉴스 Fact ID"}},
            "required": ["source_id"], "additionalProperties": False,
        },
    },
]


class SnapshotTools:
    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot

    def __call__(self, name: str, _input: dict) -> str:
        if name == "read_snapshot":
            return self._read_snapshot(_input)
        if name == "get_facts":
            return self._facts(_input)
        if name == "get_fact_catalog":
            return self._catalog(_input)
        if name == "get_daily_chart":
            return self._daily_chart(_input)
        if name == "get_new_url":
            return self._news_url(_input)
        if name == "get_snapshot_news":
            return self._snapshot_news(_input)
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

    def _read_snapshot(self, arguments: dict) -> str:
        """Small model-facing schema; legacy handlers retain their full validation."""
        if not isinstance(arguments, dict) or set(arguments) != {"kind", "args"}:
            raise ValueError("read_snapshot에는 kind와 args만 입력하세요")
        kind, args = arguments["kind"], arguments["args"]
        if (not isinstance(kind, str) or kind not in {"facts", "catalog", "news", "chart"}
                or not isinstance(args, list) or not 1 <= len(args) <= _FACT_BATCH_SIZE
                or any(not isinstance(value, str) or not value.strip() for value in args)):
            raise ValueError("kind는 facts/catalog/news/chart, args는 비어 있지 않은 문자열 1~8개여야 합니다")
        if kind == "facts":
            return self._facts({"source_ids": args})
        if len(args) != 2:
            raise ValueError("catalog/news/chart의 args는 정확히 두 문자열이어야 합니다")
        if kind == "chart":
            return self._daily_chart({"start_date": args[0], "end_date": args[1]})
        if not re.fullmatch(r"0|[1-9][0-9]*", args[1]):
            raise ValueError("offset은 '0' 또는 양의 정수 문자열이어야 합니다")
        if kind == "catalog":
            return self._catalog({"category": args[0], "offset": int(args[1])})
        return self._snapshot_news({"scope": args[0], "offset": int(args[1])})

    def _fact_page(self, facts):
        """Never cut a fact's text mid-sentence or silently lose a queued fact."""
        selected, oversized = [], []
        for index, fact in enumerate(facts):
            if len(fact_table_csv([fact])) > _FACT_TABLE_MAX_CHARS:
                oversized.append(fact.id)
                continue
            if len(fact_table_csv([*selected, fact])) > _FACT_TABLE_MAX_CHARS:
                return selected, oversized, index
            selected.append(fact)
        return selected, oversized, len(facts)

    def _facts(self, arguments: dict) -> str:
        ids = arguments.get("source_ids")
        if (set(arguments) != {"source_ids"} or not isinstance(ids, list)
                or not 1 <= len(ids) <= _FACT_BATCH_SIZE
                or any(not isinstance(key, str) or not key for key in ids)):
            raise ValueError("source_ids에 Fact ID 1~8개를 입력하세요")
        ids = list(dict.fromkeys(ids))
        found = [self.snapshot.facts[key] for key in ids if key in self.snapshot.facts]
        selected, oversized, consumed = self._fact_page(found)
        return json.dumps({
            "facts_csv": fact_table_csv(selected),
            "missing_source_ids": [key for key in ids if key not in self.snapshot.facts],
            "remaining_source_ids": [f.id for f in found[consumed:]],
            "oversized_source_ids": oversized,
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _offset(arguments):
        offset = arguments.get("offset", 0)
        if type(offset) is not int or offset < 0:
            raise ValueError("offset은 0 이상의 정수여야 합니다")
        return offset

    def _catalog(self, arguments: dict) -> str:
        category = arguments.get("category")
        if (set(arguments) - {"category", "offset"} or not isinstance(category, str)
                or category not in {"price", "financials", "valuation", "disclosure", "news", "macro"}):
            raise ValueError("유효한 category와 offset을 입력하세요")
        offset = self._offset(arguments)
        facts = sorted(self.snapshot.by_category(category), key=lambda f: (f.as_of, f.id), reverse=True)
        page = facts[offset:offset + _CATALOG_PAGE_SIZE]
        end = offset + len(page)
        return json.dumps({
            "catalog_csv": csv_rows(("source_id", "label", "as_of"),
                                    ((f.id, f.label[:160], str(f.as_of)) for f in page)),
            "labels_truncated": [f.id for f in page if len(f.label) > 160],
            "next_offset": end if end < len(facts) else None,
        }, ensure_ascii=False, separators=(",", ":"))

    def _snapshot_news(self, arguments: dict) -> str:
        scope = arguments.get("scope")
        if set(arguments) - {"scope", "offset"} or scope not in ("company", "market"):
            raise ValueError("scope는 company 또는 market이어야 합니다")
        offset = self._offset(arguments)
        facts = ordered_news(self.snapshot, scope)
        page, oversized, consumed = self._fact_page(facts[offset:offset + _NEWS_PAGE_SIZE])
        end = offset + consumed
        return json.dumps({
            "snapshot_id": self.snapshot.snapshot_id,
            "scope": scope,
            "facts_csv": fact_table_csv(page),
            "next_offset": end if end < len(facts) else None,
            "oversized_source_ids": oversized,
        }, ensure_ascii=False, separators=(",", ":"))

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

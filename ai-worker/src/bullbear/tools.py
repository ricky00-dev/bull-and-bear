"""에이전트용 데이터 조회 도구.

도구는 스냅샷에 묶여 있다. 모델은 스냅샷 ID를 고를 수 없고, 토론 시작 시 고정된
스냅샷의 데이터만 받는다. 모든 결과 항목에는 근거로 인용할 id가 붙는다.
"""

from __future__ import annotations

import json

from .snapshot import Category, Snapshot

_NO_INPUT = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

TOOL_CATEGORIES: dict[str, Category] = {
    "get_price_metrics": "price",
    "get_financials": "financials",
    "get_valuation": "valuation",
    "get_disclosures": "disclosure",
    "get_news": "news",
}

TOOL_DEFINITIONS = [
    {
        "name": "get_price_metrics",
        "description": "종가, 기간 수익률, 52주 최고·최저, 이동평균, 변동성, 거래량 지표를 조회한다.",
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
        "name": "get_news",
        "description": "최근 7일 종목 관련 뉴스의 제목, 요약, 발행 시각을 조회한다. 본문은 없다.",
        "input_schema": _NO_INPUT,
    },
]


class SnapshotTools:
    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot

    def __call__(self, name: str, _input: dict) -> str:
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
                }.items()
                if v is not None or k == "value"
            }
            for f in facts
        ]
        return json.dumps({"snapshot_id": self.snapshot.snapshot_id, "items": items}, ensure_ascii=False)

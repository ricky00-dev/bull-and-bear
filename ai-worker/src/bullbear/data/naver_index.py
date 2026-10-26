"""지수 일별 종가. 네이버 차트 엔드포인트 (비공식).

pykrx 지수 API가 동작하지 않아 임시로 쓴다. KIS 연동 시 교체한다.
"""

from __future__ import annotations

import re
from datetime import date

import httpx

from .base import DataUnavailable

_URL = "https://fchart.stock.naver.com/sise.nhn"
_ITEM = re.compile(r'<item data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|([\d.]+)\|')
SYMBOLS = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}


class NaverIndexSource:
    name = "naver-chart"

    def __init__(self, client: httpx.Client | None = None):
        self.http = client or httpx.Client(timeout=10)

    def get_daily_closes(self, code: str, start: date, end: date) -> list[tuple[date, float]]:
        if code not in SYMBOLS:
            raise ValueError(f"지원하지 않는 지수: {code}")
        # 넉넉히 받아 구간으로 자른다 (count는 오늘부터 거꾸로 센 거래일 수)
        count = max(10, (date.today() - start).days + 10)
        try:
            res = self.http.get(_URL, params={"symbol": SYMBOLS[code], "timeframe": "day", "count": count, "requestType": 0})
            res.raise_for_status()
        except httpx.HTTPError as e:
            raise DataUnavailable(f"지수 조회 실패: {code} {e}") from e
        text = res.content.decode("euc-kr", errors="replace")
        out = []
        for ymd, close in _ITEM.findall(text):
            d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
            if start <= d <= end:
                out.append((d, round(float(close), 2)))
        return out

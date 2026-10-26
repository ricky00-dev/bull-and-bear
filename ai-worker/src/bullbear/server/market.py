"""종목 검색·상세·토론 가능 여부·채점용 시세.

시세 조회(pykrx)는 느리므로 종목별로 잠깐 캐시한다. 모든 값은 **확정 종가**만 쓴다 (장중 일봉 제외).
그래서 `GET /stocks/{ticker}`의 as_of는 지금 토론을 시작하면 스냅샷이 쓸 날짜와 같다 (계약 v0.4).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from ..data import DataUnavailable, MarketDataSource, PriceBar
from ..data.naver_index import NaverIndexSource
from ..data.universe import UNIVERSE
from ..snapshot import MARKET_CLOSE, KST, confirmed_bars

_CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
CACHE_SECONDS = 300
SPARKLINE_DAYS = 60


class NotFound(LookupError):
    pass


def choseong(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        out.append(_CHOSEONG[code // 588] if 0 <= code < 11172 else ch)
    return "".join(out)


def block_reason(name: str) -> str | None:
    """토론하지 않는 종목 유형. 지금 대상 목록(UNIVERSE)은 보통주뿐이라 전체 종목 검색을 붙일 때 쓰인다."""
    if name.endswith(("우", "우B", "우C")) or name[-2:-1] == "우":
        return "우선주는 토론하지 않아요"
    if name.startswith(("KODEX", "TIGER", "KBSTAR", "ACE", "SOL", "ARIRANG", "HANARO", "KOSEF", "RISE")):
        return "ETF는 토론하지 않아요"
    return None


class Market:
    def __init__(self, source: MarketDataSource, index: NaverIndexSource | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(KST)):
        self.source = source
        self.index = index or NaverIndexSource()
        self.now = now
        self._cache: dict[str, tuple[float, list[PriceBar]]] = {}
        self._lock = threading.Lock()
        self._io = ThreadPoolExecutor(max_workers=8, thread_name_prefix="price")

    # 종목 ----------------------------------------------------------------

    def search(self, query: str, limit: int) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        q_cho = choseong(q)
        hits = [(code, name) for code, name in UNIVERSE.items()
                if q in name or code.startswith(q) or (q == q_cho and q in choseong(name))]
        # 이름(또는 초성)이 검색어로 시작하는 종목을 먼저
        hits.sort(key=lambda h: (not (h[1].startswith(q) or choseong(h[1]).startswith(q)), h[1]))
        # 종목마다 시세를 받아야 해서 병렬로 (첫 검색 기준 10건 × 약 0.3초 → 약 0.3초)
        return list(self._io.map(lambda h: self._item(*h), hits[:limit]))

    def _item(self, ticker: str, name: str) -> dict:
        close, change = self._last_close(ticker)
        reason = block_reason(name)
        return {"ticker": ticker, "name": name, "market": "KOSPI", "featured": False,
                "close": close, "change_pct": change, "eligible": reason is None, "block_reason": reason}

    def detail(self, ticker: str) -> dict:
        name = self._name(ticker)
        bars = self._bars(ticker)
        close, change = _close_change(bars)
        reason = block_reason(name)
        return {"ticker": ticker, "name": name, "market": "KOSPI", "close": close, "change_pct": change,
                "as_of": bars[-1].date.isoformat(), "eligible": reason is None, "reasons": [reason] if reason else [],
                "sparkline": [round(b.close) for b in bars[-SPARKLINE_DAYS:]]}

    def eligibility(self, ticker: str) -> dict:
        reason = block_reason(self._name(ticker))
        return {"ticker": ticker, "eligible": reason is None, "reasons": [reason] if reason else []}

    # 채점용 시세 -----------------------------------------------------------

    def daily_closes(self, ticker: str, start: date, end: date) -> list[dict]:
        self._name(ticker)
        bars = confirmed_bars(self.source.get_daily_prices(ticker, start, end), self.now())
        return [{"date": b.date.isoformat(), "close": round(b.close)} for b in bars if start <= b.date <= end]

    def index_closes(self, code: str, start: date, end: date) -> list[dict]:
        now = self.now().astimezone(KST)
        rows = self.index.get_daily_closes(code, start, end)
        if rows and rows[-1][0] == now.date() and now.time() < MARKET_CLOSE:
            rows = rows[:-1]  # 장중 값은 확정 전
        return [{"date": d.isoformat(), "close": c} for d, c in rows]

    # 내부 ----------------------------------------------------------------

    def _name(self, ticker: str) -> str:
        if ticker not in UNIVERSE:
            raise NotFound(f"대상 종목이 아닙니다: {ticker}")
        return UNIVERSE[ticker]

    def _bars(self, ticker: str) -> list[PriceBar]:
        """최근 약 90거래일 확정 일봉. 5분 캐시."""
        with self._lock:
            hit = self._cache.get(ticker)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
        today = self.now().astimezone(KST).date()
        bars = confirmed_bars(self.source.get_daily_prices(ticker, today - timedelta(days=130), today), self.now())
        if len(bars) < 2:
            raise DataUnavailable(f"시세가 부족합니다: {ticker}")
        with self._lock:
            self._cache[ticker] = (time.monotonic(), bars)
        return bars

    def _last_close(self, ticker: str) -> tuple[int | None, float | None]:
        try:
            return _close_change(self._bars(ticker))
        except DataUnavailable:
            return None, None  # 검색 목록은 시세 없이도 보여 준다


def _close_change(bars: list[PriceBar]) -> tuple[int, float]:
    last, prev = bars[-1], bars[-2]
    return round(last.close), round((last.close / prev.close - 1) * 100, 2)

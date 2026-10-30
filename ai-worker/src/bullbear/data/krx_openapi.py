"""KRX official daily prices/indices + OpenDART. No Naver price fallback.

Daily whole-market responses share a cache across tickers. Bars are unadjusted.
"""
from __future__ import annotations

import gzip
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from .base import DataUnavailable, PriceBar
from .pykrx_dart import PykrxDartSource

KST = timezone(timedelta(hours=9))
BASE = "https://data-dbg.krx.co.kr/svc/apis"


class KrxOpenApiSource(PykrxDartSource):
    name = "krx-openapi+opendart"
    warnings = ["KRX 일봉은 수정주가가 아닙니다. 액면분할 등 기업행사에 따른 수익률·지표 보정은 미구현입니다."]

    def __init__(self, krx_api_key, dart_api_key, cache_dir):
        super().__init__(dart_api_key, cache_dir)
        self._krx_key = krx_api_key
        self._cache = cache_dir / "krx-openapi"
        self._lock = threading.RLock()
        self._last_request = 0.0
        self._markets = {}
        self._closed = threading.Event()

    def close(self):
        # Stop a cold-history preload between requests during server shutdown.
        self._closed.set()

    def _day(self, endpoint, day):
        path = self._cache / endpoint / f"{day:%Y%m%d}.json.gz"
        with self._lock:
            if self._closed.is_set():
                raise DataUnavailable("KRX 시세 조회가 종료되었습니다")
            if path.exists():
                try:
                    with gzip.open(path, "rt", encoding="utf-8") as f:
                        rows = json.load(f)
                    self._validate_rows(rows, day)
                    age = time.time() - path.stat().st_mtime
                    old = day < datetime.now(KST).date() - timedelta(days=7)
                    if (old and rows) or age < 3600:
                        return rows
                except (OSError, ValueError, TypeError):
                    pass
            if not self._krx_key:
                raise DataUnavailable("KRX_API_KEY 및 주식·지수 API 활용 승인이 필요합니다")
            time.sleep(max(0, 0.25 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                r = httpx.get(f"{BASE}/{endpoint}", params={"basDd": day.strftime("%Y%m%d")},
                              headers={"AUTH_KEY": self._krx_key}, timeout=15)
                if r.status_code in (401, 403):
                    raise DataUnavailable("KRX 인증키 또는 해당 API 활용 승인을 확인하세요")
                r.raise_for_status()
                rows = r.json()["OutBlock_1"]
                self._validate_rows(rows, day)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise DataUnavailable("KRX 일별 데이터 응답을 읽을 수 없습니다") from None
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid4().hex}.tmp")
            with gzip.open(temporary, "wt", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            temporary.replace(path)
            return rows

    @staticmethod
    def _validate_rows(rows, day):
        if not isinstance(rows, list) or any(not isinstance(r, dict) or r.get("BAS_DD") != day.strftime("%Y%m%d") for r in rows):
            raise ValueError("Invalid dated response")

    @staticmethod
    def _days(start, end):
        if (end - start).days > 800:
            raise DataUnavailable("KRX 조회는 한 번에 800일 이내로 제한합니다")
        day = start
        while day <= end:
            if day.weekday() < 5:
                yield day
            day += timedelta(days=1)

    @staticmethod
    def _number(value):
        number = float(str(value).replace(",", ""))
        if not math.isfinite(number):
            raise ValueError("Non-finite value")
        return number

    def _stock_endpoint(self, ticker, end):
        key = (ticker, end)
        with self._lock:
            if key in self._markets:
                return self._markets[key]
            from .universe import UNIVERSE
            if ticker in UNIVERSE or ticker == "005935":
                return "sto/stk_bydd_trd"
            for day in reversed(list(self._days(end - timedelta(days=10), end))):
                for endpoint in ("sto/stk_bydd_trd", "sto/ksq_bydd_trd"):
                    if any(r.get("ISU_CD") == ticker for r in self._day(endpoint, day)):
                        self._markets[key] = endpoint
                        return endpoint
            raise DataUnavailable("KRX 주식 일별 데이터에서 종목을 찾을 수 없습니다")

    def get_daily_prices(self, ticker, start, end):
        if start > end:
            return []
        endpoint = self._stock_endpoint(ticker, end)
        bars = []
        try:
            for day in self._days(start, end):
                row = next((r for r in self._day(endpoint, day) if r.get("ISU_CD") == ticker), None)
                if row is None:
                    continue
                o, h, low, close, volume = [self._number(row[k]) for k in
                                           ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL")]
                if o == 0 and volume == 0:
                    continue
                if min(o, h, low, close) <= 0 or volume < 0 or not volume.is_integer():
                    raise ValueError("Invalid price")
                bars.append(PriceBar(day, o, h, low, close, int(volume)))
        except (ValueError, KeyError, TypeError):
            raise DataUnavailable("KRX 주식 일봉 형식 오류") from None
        return bars

    def get_index_prices(self, code, start, end):
        endpoints = {"KOSPI": ("idx/kospi_dd_trd", "코스피"), "KOSDAQ": ("idx/kosdaq_dd_trd", "코스닥")}
        if code not in endpoints:
            raise DataUnavailable("지원하지 않는 KRX 지수입니다")
        endpoint, name = endpoints[code]
        result = []
        try:
            for day in self._days(start, end):
                rows = self._day(endpoint, day)
                if not rows:
                    continue
                row = next((r for r in rows if r.get("IDX_NM") in (code, name)), None)
                if row is None:
                    raise ValueError("Benchmark missing")
                close = self._number(row["CLSPRC_IDX"])
                if close <= 0:
                    raise ValueError("Invalid index")
                result.append((day, close))
        except (ValueError, KeyError, TypeError):
            raise DataUnavailable("KRX 기준 지수 형식 오류") from None
        return result

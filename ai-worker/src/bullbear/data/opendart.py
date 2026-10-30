"""OpenDART REST 클라이언트 (https://opendart.fss.or.kr).

성공한 응답 원문은 디스크에 캐시한다. 아직 발표되지 않은 보고서의 자료 없음
응답은 캐시하지 않아 다음 조회에서 새 보고서를 확인할 수 있게 한다.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import httpx

from .base import DataUnavailable

BASE_URL = "https://opendart.fss.or.kr/api"

REPORT_CODES = {"Q1": "11013", "H1": "11012", "Q3": "11014", "FY": "11011"}

STATUS_OK = "000"
STATUS_NO_DATA = "013"


class OpenDartClient:
    def __init__(self, api_key: str, cache_dir: Path, timeout: float = 20.0):
        if not api_key:
            raise DataUnavailable("OPENDART_API_KEY가 없습니다")
        self._key = api_key
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._corp_codes: dict[str, str] | None = None

    def corp_code(self, ticker: str) -> str:
        if self._corp_codes is None:
            self._corp_codes = self._load_corp_codes()
        try:
            return self._corp_codes[ticker]
        except KeyError:
            raise DataUnavailable(f"DART 고유번호를 찾을 수 없음: {ticker}") from None

    def get(self, endpoint: str, *, cache: bool = True, **params: str) -> dict | None:
        """JSON 엔드포인트 호출. 데이터 없음(013)이면 None."""
        cache_path = self._cache_dir / endpoint / ("_".join(f"{k}={v}" for k, v in sorted(params.items())) + ".json")
        body = self._read_cache(cache_path) if cache else None
        # Older versions cached 013 forever. Ignore these entries without requiring
        # operators to clear their existing data directory.
        if body is None or body.get("status") != STATUS_OK or not self._valid_payload(body):
            try:
                resp = self._http.get(f"/{endpoint}.json", params={"crtfc_key": self._key, **params})
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError):
                # Exception strings and response bodies can echo crtfc_key.
                raise DataUnavailable("OpenDART 응답을 읽을 수 없습니다") from None
            if not isinstance(body, dict) or not self._valid_payload(body):
                raise DataUnavailable("OpenDART 응답 형식이 올바르지 않습니다")
            if cache and body.get("status") == STATUS_OK:
                self._write_cache(cache_path, body)
        status = body.get("status")
        if status == STATUS_NO_DATA:
            return None
        if status != STATUS_OK:
            raise DataUnavailable("OpenDART API가 요청을 처리하지 못했습니다")
        return body

    @staticmethod
    def _valid_payload(body: dict) -> bool:
        return "list" not in body or (isinstance(body["list"], list) and all(isinstance(row, dict) for row in body["list"]))

    @staticmethod
    def _read_cache(path: Path) -> dict | None:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    @staticmethod
    def _write_cache(path: Path, body: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        except OSError:
            raise DataUnavailable("OpenDART 캐시를 저장할 수 없습니다") from None

    def _download_companies(self, *, timeout: float | None = None) -> tuple[dict[str, str], dict[str, str]]:
        try:
            options = {} if timeout is None else {"timeout": timeout}
            resp = self._http.get("/corpCode.xml", params={"crtfc_key": self._key}, **options)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
                filename = next((name for name in archive.namelist() if Path(name).name.casefold() == "corpcode.xml"), None)
                if filename is None:
                    raise ValueError("Company XML missing")
                root = ElementTree.fromstring(archive.read(filename))
        except (httpx.HTTPError, zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError):
            raise DataUnavailable("OpenDART 종목 목록을 읽을 수 없습니다") from None
        codes = {}
        names = {}
        for item in root.iter("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            if stock_code:
                corp_code = (item.findtext("corp_code") or "").strip()
                if not corp_code:
                    raise DataUnavailable("OpenDART 종목 목록 형식이 올바르지 않습니다")
                codes[stock_code] = corp_code
                names[stock_code] = (item.findtext("corp_name") or stock_code).strip()
        if not codes:
            raise DataUnavailable("OpenDART 종목 목록이 비어 있습니다")
        return codes, names

    def _company_cache(self, path: Path) -> dict[str, str] | None:
        body = self._read_cache(path)
        if body and all(isinstance(k, str) and isinstance(v, str) and v for k, v in body.items()):
            return body
        return None

    def _load_corp_codes(self) -> dict[str, str]:
        path = self._cache_dir / "corp_codes.json"
        cached = self._company_cache(path)
        if cached is not None:
            return cached
        codes, names = self._download_companies()
        self._write_cache(path, codes)
        self._write_cache(self._cache_dir / "listed_companies.json", names)
        return codes

    def listed_companies(self) -> dict[str, str]:
        path = self._cache_dir / "listed_companies.json"
        cached = self._company_cache(path)
        if cached is not None:
            return cached
        codes, names = self._download_companies(timeout=5)
        self._write_cache(path, names)
        self._write_cache(self._cache_dir / "corp_codes.json", codes)
        self._corp_codes = codes
        return names


def parse_amount(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.replace(",", "").strip()
    if raw in ("", "-"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None

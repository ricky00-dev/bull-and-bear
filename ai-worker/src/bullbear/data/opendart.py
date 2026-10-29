"""OpenDART REST 클라이언트 (https://opendart.fss.or.kr).

응답 원문은 디스크에 캐시한다. 같은 보고서를 반복 조회하지 않고, 스냅샷을 다시
만들 때도 같은 원문을 쓰게 하기 위해서다.
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
        if cache and cache_path.exists():
            body = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            resp = self._http.get(f"/{endpoint}.json", params={"crtfc_key": self._key, **params})
            resp.raise_for_status()
            body = resp.json()
            if cache and body.get("status") in (STATUS_OK, STATUS_NO_DATA):
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        status = body.get("status")
        if status == STATUS_NO_DATA:
            return None
        if status != STATUS_OK:
            raise DataUnavailable(f"OpenDART {endpoint} 오류 {status}: {body.get('message')}")
        return body

    def _load_corp_codes(self) -> dict[str, str]:
        path = self._cache_dir / "corp_codes.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        resp = self._http.get("/corpCode.xml", params={"crtfc_key": self._key})
        resp.raise_for_status()
        try:
            archive = zipfile.ZipFile(io.BytesIO(resp.content))
        except zipfile.BadZipFile:
            raise DataUnavailable(f"corpCode.xml 다운로드 실패: {resp.text[:200]}") from None
        root = ElementTree.fromstring(archive.read(archive.namelist()[0]))
        codes = {}
        names = {}
        for item in root.iter("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            if stock_code:
                codes[stock_code] = item.findtext("corp_code").strip()
                names[stock_code] = (item.findtext("corp_name") or stock_code).strip()
        path.write_text(json.dumps(codes), encoding="utf-8")
        (self._cache_dir / "listed_companies.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        return codes

    def listed_companies(self) -> dict[str, str]:
        path = self._cache_dir / "listed_companies.json"
        if not path.exists():
            # Old corp_codes caches contain only identifiers; download names as well.
            resp = self._http.get("/corpCode.xml", params={"crtfc_key": self._key}, timeout=5)
            resp.raise_for_status()
            try:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
                    root = ElementTree.fromstring(archive.read("CORPCODE.xml"))
                names = {(item.findtext("stock_code") or "").strip(): (item.findtext("corp_name") or "").strip()
                         for item in root.iter("list") if (item.findtext("stock_code") or "").strip()}
            except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
                raise DataUnavailable("OpenDART 종목 목록 다운로드 실패") from exc
            path.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8"))


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

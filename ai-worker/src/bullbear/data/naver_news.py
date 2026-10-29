"""네이버 검색 API(뉴스) 구현체.

https://api.ncloud-docs.com/docs/naver-api-hub-search-news
제목·요약·링크·발행 시각만 준다. 본문은 가져오지 않는다 (저작권·약관).

종목명으로 검색하면 관련 없는 기사가 많이 섞인다. 제목에 종목명이 들어간 기사만 남기고,
비슷한 제목(통신사 기사 재전송 등)은 하나만 남긴다.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from .base import DataUnavailable, NewsArticle, NewsSource

API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
PAGE_SIZE = 100
MAX_PAGES = 3

# 이름이 짧거나 흔한 단어라 검색어를 보강해야 하는 종목
QUERY_OVERRIDES = {
    "003550": "LG 지주회사",
    "034730": "SK 지주회사",
    "000270": "기아 주가",
}

_TAG = re.compile(r"<[^>]+>")
_NON_WORD = re.compile(r"[\W_]+")
_BRACKET_TAG = re.compile(r"^\s*[\[【(][^\]】)]{1,10}[\]】)]\s*")  # [속보], 【단독】 등


def clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text)).strip()


def _title_key(title: str) -> str:
    return _NON_WORD.sub("", _BRACKET_TAG.sub("", title))[:30]


class NaverNewsSource(NewsSource):
    name = "naver-news"

    def __init__(self, client_id: str | None, client_secret: str | None, timeout: float = 10.0):
        if not (client_id and client_secret):
            raise DataUnavailable("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 없습니다")
        self._http = httpx.Client(
            timeout=timeout,
            headers={"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": client_secret},
        )

    def search(self, ticker: str, name: str, start: datetime, end: datetime) -> list[NewsArticle]:
        query = QUERY_OVERRIDES.get(ticker, name)
        raw: list[dict] = []
        for page in range(MAX_PAGES):
            resp = self._http.get(API_URL, params={"query": query, "display": PAGE_SIZE,
                                                   "start": page * PAGE_SIZE + 1, "sort": "date", "format": "json"})
            if resp.status_code != 200:
                raise DataUnavailable(f"네이버 API HUB 뉴스 오류 HTTP {resp.status_code}")
            items = resp.json().get("items", [])
            raw.extend(items)
            if len(items) < PAGE_SIZE or parsedate_to_datetime(items[-1]["pubDate"]) < start:
                break
        return filter_articles(raw, name, start, end)


def filter_articles(items: list[dict], name: str, start: datetime, end: datetime) -> list[NewsArticle]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out = []
    for item in items:
        published = parsedate_to_datetime(item["pubDate"])
        if not (start <= published <= end):
            continue
        title = clean(item["title"])
        if name not in title:
            continue
        url = item.get("originallink") or item["link"]
        key = _title_key(title)
        if url in seen_urls or key in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(key)
        out.append(NewsArticle(
            source_ref=url,
            published_at=published,
            title=title,
            summary=clean(item.get("description", "")),
            url=url,
        ))
    out.sort(key=lambda a: a.published_at, reverse=True)
    return out

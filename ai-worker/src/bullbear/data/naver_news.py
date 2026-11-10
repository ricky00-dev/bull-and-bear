"""네이버 검색 API(뉴스) 구현체.

https://api.ncloud-docs.com/docs/naver-api-hub-search-news
제목·요약·링크·발행 시각만 준다. 본문은 가져오지 않는다 (저작권·약관).

종목명으로 검색하면 관련 없는 기사가 많이 섞인다. 제목에 종목명이 들어간 기사만 남기고,
비슷한 제목(통신사 기사 재전송 등)은 하나만 남긴다.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from urllib.parse import urlsplit

import httpx

from .base import DataUnavailable, NewsArticle, NewsSource

API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
PAGE_SIZE = 100
MAX_PAGES = 3
_KST = timezone(timedelta(hours=9))
MARKET_TOPICS = (
    ("한국 증시", ("코스피", "코스닥", "증시", "주식시장")),
    ("한국은행 통화정책", ("한국은행", "금통위", "기준금리", "통화정책")),
    ("원달러 환율", ("환율", "원달러", "원·달러", "달러원")),
    ("한국 경제 산업", ("수출", "물가", "성장률", "산업생산", "무역", "고용", "경기")),
)

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
        items = self._search(query, start)
        if items and all(_published_at(item["pubDate"]) > end for item in items):
            # The API has no publication-date filter. Find candidates near the price cutoff.
            day = end.astimezone(_KST).date()
            dated_query = f"{query} {day.month}월 {day.day}일"
            items = self._search(dated_query, start, max_pages=1, sort="sim")
        return filter_articles(items, name, start, end)

    def search_market(self, start: datetime, end: datetime) -> list[NewsArticle]:
        articles = []
        for query, aliases in MARKET_TOPICS:
            items = filter_articles(self._search(query, start, max_pages=1), None, start, end)
            articles.extend(a for a in items if any(alias in a.title for alias in aliases))
        return articles

    def close(self):
        self._http.close()

    def _search(self, query, start, *, max_pages=MAX_PAGES, sort="date"):
        raw: list[dict] = []
        try:
            for page in range(max_pages):
                resp = self._http.get(API_URL, params={"query": query, "display": PAGE_SIZE,
                                                       "start": page * PAGE_SIZE + 1, "sort": sort, "format": "json"})
                if resp.status_code != 200:
                    raise DataUnavailable(f"네이버 API HUB 뉴스 오류 HTTP {resp.status_code}")
                body = resp.json()
                items = body.get("items") if isinstance(body, dict) else None
                _validate_items(items)
                raw.extend(items)
                if len(items) < PAGE_SIZE or (sort == "date" and _published_at(items[-1]["pubDate"]) < start):
                    break
            return raw
        except httpx.HTTPError:
            # Provider exceptions can include request details; only expose a safe summary.
            raise DataUnavailable("네이버 API HUB 뉴스 요청에 실패했습니다") from None
        except (ValueError, OverflowError):
            raise DataUnavailable("네이버 API HUB 뉴스 응답 형식이 올바르지 않습니다") from None


def _published_at(raw: str) -> datetime:
    published = parsedate_to_datetime(raw)
    if published.tzinfo is None or published.utcoffset() is None:
        raise ValueError("News publication time must include a timezone")
    return published


def _validate_items(items) -> None:
    # A 200 error payload without items is not a successful empty news search.
    if not isinstance(items, list):
        raise ValueError("News items must be an array")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("News item must be an object")
        if not all(isinstance(item.get(key), str) for key in ("title", "pubDate")):
            raise ValueError("News item is missing text fields")
        url = item.get("originallink") or item.get("link")
        if not isinstance(url, str) or not url.strip() or not isinstance(item.get("description", ""), str):
            raise ValueError("News item has invalid link or description")
        _published_at(item["pubDate"])


def filter_articles(items: list[dict], name: str | None, start: datetime, end: datetime) -> list[NewsArticle]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out = []
    for item in items:
        published = _published_at(item["pubDate"])
        if not (start <= published <= end):
            continue
        title = clean(item["title"])
        if name is not None and name not in title:
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
            publisher=_publisher(item.get("originallink")),
        ))
    out.sort(key=lambda a: a.published_at, reverse=True)
    return out


def _publisher(original_url):
    # The API has no publisher-name field. Preserve the original host only.
    if not isinstance(original_url, str):
        return None
    try:
        host = urlsplit(original_url).hostname
    except ValueError:
        return None
    if host is None or host == "naver.com" or host.endswith(".naver.com"):
        return None
    return host.removeprefix("www.")

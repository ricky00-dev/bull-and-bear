from datetime import datetime

import httpx
import pytest

from bullbear.data.base import DataUnavailable
from bullbear.data.naver_news import PAGE_SIZE, NaverNewsSource, filter_articles
from bullbear.snapshot import KST

START = datetime(2026, 10, 10, tzinfo=KST)
END = datetime(2026, 10, 17, tzinfo=KST)


def item(title, url, pub="Thu, 16 Oct 2026 10:00:00 +0900", desc="요약"):
    return {"title": title, "originallink": url, "link": url, "description": desc, "pubDate": pub}


def test_cleans_html_and_filters_by_name():
    items = [
        item("<b>삼성전자</b>, 3분기 &quot;어닝 서프라이즈&quot;", "u1"),
        item("코스피 마감 시황", "u2"),
    ]
    out = filter_articles(items, "삼성전자", START, END)
    assert [a.title for a in out] == ['삼성전자, 3분기 "어닝 서프라이즈"']


def test_dedupes_reposted_titles_and_urls():
    items = [
        item("삼성전자 3분기 영업이익 12조", "u1"),
        item("[속보] 삼성전자 3분기 영업이익 12조", "u2"),
        item("삼성전자 3분기 영업이익 12조…", "u3"),
        item("삼성전자 다른 기사", "u1"),
    ]
    out = filter_articles(items, "삼성전자", START, END)
    assert [a.url for a in out] == ["u1"]  # [속보]·말줄임 재전송과 같은 URL 제외


def test_time_window_and_sorting():
    items = [
        item("삼성전자 오래된 기사", "u1", pub="Mon, 06 Oct 2026 10:00:00 +0900"),
        item("삼성전자 아침 기사", "u2", pub="Thu, 16 Oct 2026 08:00:00 +0900"),
        item("삼성전자 오후 기사", "u3", pub="Thu, 16 Oct 2026 15:00:00 +0900"),
    ]
    out = filter_articles(items, "삼성전자", START, END)
    assert [a.title for a in out] == ["삼성전자 오후 기사", "삼성전자 아침 기사"]


def test_hub_endpoint_headers_and_json_query(monkeypatch):
    import httpx
    from bullbear.data.naver_news import NaverNewsSource
    source = NaverNewsSource("test-id", "test-secret")
    headers = dict(source._http.headers)
    source._http.close()
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"items": [item("삼성전자 뉴스", "https://example.com/news")]})
    source._http = httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    try:
        assert len(source.search("005930", "삼성전자", START, END)) == 1
        assert len(calls) == 1
        assert str(calls[0].url).startswith("https://naverapihub.apigw.ntruss.com/search/v1/news?")
        assert calls[0].url.params["format"] == "json"
        assert calls[0].headers["X-NCP-APIGW-API-KEY-ID"] == "test-id"
        assert "X-Naver-Client-Id" not in calls[0].headers
    finally:
        source._http.close()


@pytest.fixture
def make_source():
    sources = []

    def create(handler):
        source = NaverNewsSource("test-id", "test-secret")
        source._http.close()
        source._http = httpx.Client(transport=httpx.MockTransport(handler))
        sources.append(source)
        return source

    yield create
    for source in sources:
        source._http.close()


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failure_is_safe_data_unavailable(make_source, error):
    def handle(request):
        raise error("PRIVATE request details: test-secret", request=request)

    source = make_source(handle)
    with pytest.raises(DataUnavailable) as caught:
        source.search("005930", "삼성전자", START, END)
    assert "뉴스 요청" in str(caught.value)
    assert "PRIVATE" not in str(caught.value) and "test-secret" not in str(caught.value)


def test_http_failure_does_not_expose_response_body(make_source):
    source = make_source(lambda request: httpx.Response(503, text="PRIVATE test-secret"))
    with pytest.raises(DataUnavailable, match="HTTP 503") as caught:
        source.search("005930", "삼성전자", START, END)
    assert "PRIVATE" not in str(caught.value) and "test-secret" not in str(caught.value)


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="PRIVATE invalid JSON"),
    httpx.Response(200, json={"errorMessage": "PRIVATE"}),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"items": None}),
    httpx.Response(200, json={"items": {}}),
    httpx.Response(200, json={"items": [None]}),
    httpx.Response(200, json={"items": [{"title": "삼성전자"}]}),
    httpx.Response(200, json={"items": [item("삼성전자", "u1", pub="PRIVATE invalid date")]}),
    httpx.Response(200, json={"items": [item("삼성전자", "u1", pub="16 Oct 2026 10:00:00")]}),
    httpx.Response(200, json={"items": [item("삼성전자", "", desc="내용")]}),
    httpx.Response(200, json={"items": [item("삼성전자", "u1", desc=None)]}),
], ids=["invalid-json", "api-error", "non-object", "null-items", "non-list-items",
        "non-object-item", "missing-fields", "invalid-date", "naive-date", "empty-link", "invalid-description"])
def test_malformed_provider_response_is_safe_data_unavailable(make_source, response):
    source = make_source(lambda request: response)
    with pytest.raises(DataUnavailable, match="응답 형식") as caught:
        source.search("005930", "삼성전자", START, END)
    assert "PRIVATE" not in str(caught.value)


def test_empty_items_is_a_successful_search(make_source):
    source = make_source(lambda request: httpx.Response(200, json={"items": []}))
    assert source.search("005930", "삼성전자", START, END) == []


def test_stock_search_uses_price_date_if_latest_pages_miss_cutoff(make_source):
    start = datetime(2026, 11, 2, 15, 30, tzinfo=KST)
    end = datetime(2026, 11, 9, 15, 30, tzinfo=KST)
    calls = []
    future = item("삼성전자 마감 이후 기사", "future", pub="Mon, 09 Nov 2026 16:00:00 +0900")
    eligible = item("삼성전자 장중 기사", "eligible", pub="Mon, 09 Nov 2026 14:00:00 +0900")

    def handle(request):
        params = request.url.params
        calls.append((params["query"], params["sort"], int(params["start"])))
        items = [future] * PAGE_SIZE if params["sort"] == "date" else [future, eligible]
        return httpx.Response(200, json={"items": items})

    articles = make_source(handle).search("005930", "삼성전자", start, end)
    assert calls == [("삼성전자", "date", i * PAGE_SIZE + 1) for i in range(3)] + [
        ("삼성전자 11월 9일", "sim", 1),
    ]
    assert [article.url for article in articles] == ["eligible"]


def test_market_news_uses_bounded_topic_search_and_original_publisher(make_source):
    queries = []
    relevant = {
        "한국 증시": "코스피 마감 시황",
        "한국은행 통화정책": "한국은행 금통위 발표",
        "원달러 환율": "원달러 환율 움직임",
        "한국 경제 산업": "국내 수출 경기 전망",
    }

    def handle(request):
        query = request.url.params["query"]
        queries.append(query)
        return httpx.Response(200, json={"items": [
            item(relevant[query], f"https://www.example.com/news/{len(queries)}"),
            item("연예계 소식", "https://example.com/entertainment"),
        ]})

    articles = make_source(handle).search_market(START, END)
    assert queries == list(relevant)
    assert [article.title for article in articles] == list(relevant.values())
    assert {article.publisher for article in articles} == {"example.com"}


def test_preserves_distinct_portal_link_alongside_publisher_url():
    original = "https://publisher.example/article"
    portal = "https://n.news.naver.com/mnews/article/001/123"
    row = {**item("삼성전자 뉴스", original), "link": portal}
    article, = filter_articles([row], "삼성전자", START, END)
    assert (article.source_ref, article.url, article.alternate_url) == (original, original, portal)
    from_portal, = filter_articles([{**row, "originallink": ""}], "삼성전자", START, END)
    assert from_portal.url == portal and from_portal.alternate_url is None

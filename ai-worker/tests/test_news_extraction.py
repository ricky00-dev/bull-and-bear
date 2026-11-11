from concurrent.futures import ThreadPoolExecutor
import socket
from threading import Event

import httpx
import pytest

from bullbear.news_extraction import ArticleExtractor, MAX_CONTENT_CHARS, USER_AGENT

URL = "https://publisher.example/article"
BODY = "외국인 투자자는 11월 2일부터 6일까지 국내 시장에서 2.2조 원을 순매도했다."
ARTICLE = f"""<!doctype html><html lang="ko"><head><title>국내 주식시장 주간 거래 동향</title></head>
<body><nav>전체 메뉴와 추천 링크</nav><main><article>
<h1>국내 주식시장 주간 거래 동향</h1>
<p>{BODY} 같은 기간 기관 투자자는 반도체와 자동차를 중심으로 매수 우위를 기록했고 지수는 전주보다 1.4% 하락했다.</p>
<p>거래소는 이번 주 유가증권시장 거래대금이 전달 평균보다 늘었다고 밝혔다. 원화 환율은 주초에 상승했지만 수요일부터 낮아졌다.</p>
<p>시장 참가자들은 다음 주 발표되는 기업 실적을 기다리고 있다. 일부에서는 수출 개선을 예상하지만 수급 변화가 이어질지는 불확실하다고 설명했다.</p>
</article></main><footer>무단 전재 금지</footer></body></html>"""


def html_response(html=ARTICLE):
    return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text=html)


@pytest.fixture
def public_dns(monkeypatch):
    ips = {"publisher.example": ["93.184.216.34"], "mirror.example": ["142.250.185.14"]}
    calls = []

    def resolve(host, port, **kwargs):
        calls.append(host)
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                 "", (ip, port)) for ip in ips.get(host, [host])]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return ips, calls


def make_extractor(handler):
    return ArticleExtractor(transport=httpx.MockTransport(handler))


def test_extracts_real_article_and_uses_pinned_host(public_dns):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "publisher.example"
        assert request.extensions["sni_hostname"] == "publisher.example"
        assert request.headers["user-agent"] == USER_AGENT
        return httpx.Response(404) if request.url.path == "/robots.txt" else html_response()

    extractor = make_extractor(handler)
    result = extractor.fetch(URL + "#section")
    assert result.status == "SUCCESS" and result.url == URL
    assert BODY in result.content and "추천 링크" not in result.content
    assert extractor.fetch(URL) is result
    assert calls == ["/robots.txt", "/article"]
    assert make_extractor(handler).fetch(URL) == result


@pytest.mark.parametrize("page,code", [
    ("<html><nav>메뉴</nav><p>짧은 페이지</p></html>", "NO_ARTICLE_BODY"),
    ('<html><title>페이지를 찾을 수 없습니다</title><article>' + ARTICLE + '</article></html>', "NO_ARTICLE_BODY"),
    ('<html><article><h1>구독자 전용 콘텐츠</h1><p>' + ('구독 후 읽을 수 있어요. ' * 25) + '</p></article></html>', "ACCESS_DENIED"),
    ('<html><main><p>' + ('Please sign in to continue. ' * 25) + '</p></main></html>', "ACCESS_DENIED"),
])
def test_no_body_and_gate_pages_are_not_success(public_dns, page, code):
    extractor = make_extractor(lambda request: httpx.Response(404) if request.url.path == "/robots.txt"
                               else html_response(page))
    result = extractor.fetch(URL)
    assert (result.status, result.error_code, result.content) == ("EXTRACTION_FAILED", code, None)


@pytest.mark.parametrize("status,code", [(403, "ACCESS_DENIED"), (404, "NOT_FOUND"), (429, "RATE_LIMITED"), (503, "HTTP_503")])
def test_classifies_and_caches_http_failure(public_dns, status, code):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(404 if request.url.path == "/robots.txt" else status, text="private response")

    extractor = make_extractor(handler)
    result = extractor.fetch(URL)
    assert (result.status, result.error_code, result.content) == ("FETCH_FAILED", code, None)
    assert extractor.fetch(URL) is result
    assert requests == ["/robots.txt", "/article"]


def test_timeout_is_structured(public_dns):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.extensions["timeout"]["read"] <= 5.0
        raise httpx.ReadTimeout("private details", request=request)

    result = make_extractor(handler).fetch(URL)
    assert (result.status, result.error_code) == ("FETCH_FAILED", "TIMEOUT")


@pytest.mark.parametrize("url,code", [
    ("file:///etc/passwd", "INVALID_URL"),
    ("https://", "INVALID_URL"),
    ("https://me:secret@publisher.example/article", "INVALID_URL"),
    ("http://publisher.example:8080/article", "INVALID_URL"),
    ("http://127.0.0.1/article", "BLOCKED_ADDRESS"),
    ("http://169.254.169.254/article", "BLOCKED_ADDRESS"),
    ("http://[::1]/article", "BLOCKED_ADDRESS"),
    ("http://[::ffff:127.0.0.1]/article", "BLOCKED_ADDRESS"),
    ("http://[64:ff9b::7f00:1]/article", "BLOCKED_ADDRESS"),
    ("http://publisher.example/article", "BLOCKED_ADDRESS"),
])
def test_rejects_invalid_private_and_mixed_dns_addresses(public_dns, url, code):
    ips, _ = public_dns
    ips["publisher.example"] += ["10.0.0.5"]
    result = make_extractor(lambda _: pytest.fail("blocked URL reached transport")).fetch(url)
    assert (result.status, result.error_code) == ("UNSUPPORTED", code)


@pytest.mark.parametrize("location,code", [
    ("https://127.0.0.1/private", "BLOCKED_ADDRESS"),
    ("https://blocked.example/article", "BLOCKED_ADDRESS"),
    ("https://me:secret@mirror.example/article", "INVALID_URL"),
    ("http://mirror.example/article", "INSECURE_REDIRECT"),
])
def test_redirect_rechecks_target(public_dns, location, code):
    ips, _ = public_dns
    ips["blocked.example"] = ["10.0.0.5"]

    def handler(request):
        assert request.headers["host"] == "publisher.example"
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": location})

    result = make_extractor(handler).fetch(URL)
    assert (result.status, result.error_code) == ("UNSUPPORTED", code)


def test_redirect_destination_checks_robots_policy(public_dns):
    requests = []

    def handler(request):
        host, path = request.headers["host"], request.url.path
        requests.append((host, path))
        if host == "publisher.example":
            if path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"Location": "https://mirror.example/news/story.html"})
        assert path == "/robots.txt"
        return httpx.Response(200, text="User-agent: BullBearWorker\nDisallow: /news/*.html$")

    result = make_extractor(handler).fetch(URL)
    assert (result.status, result.error_code) == ("FETCH_FAILED", "ROBOTS_DENIED")
    assert requests == [("publisher.example", "/robots.txt"), ("publisher.example", "/article"),
                        ("mirror.example", "/robots.txt")]


@pytest.mark.parametrize("status,code", [(403, "ROBOTS_DENIED"), (429, "ROBOTS_UNAVAILABLE"), (503, "ROBOTS_UNAVAILABLE")])
def test_unavailable_robots_fails_closed(public_dns, status, code):
    def handler(request):
        assert request.url.path == "/robots.txt"
        return httpx.Response(status)

    result = make_extractor(handler).fetch(URL)
    assert (result.status, result.error_code) == ("FETCH_FAILED", code)


def test_redirects_are_bounded(public_dns):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "/article"})

    assert make_extractor(handler).fetch(URL).error_code == "REDIRECT_LIMIT"
    assert calls == ["/robots.txt", *["/article"] * 4]


@pytest.mark.parametrize("headers,body,code", [
    ({"Content-Type": "application/pdf"}, b"%PDF", "UNSUPPORTED_CONTENT_TYPE"),
    ({"Content-Type": "text/html", "Content-Length": "9999999"}, b"", "RESPONSE_TOO_LARGE"),
    ({"Content-Type": "text/html"}, b"a" * (2 * 1024 * 1024 + 1), "RESPONSE_TOO_LARGE"),
])
def test_http_response_limit_and_type(public_dns, headers, body, code):
    extractor = make_extractor(lambda request: httpx.Response(404) if request.url.path == "/robots.txt"
                               else httpx.Response(200, headers=headers, content=body))
    result = extractor.fetch(URL)
    assert (result.status, result.error_code) == ("UNSUPPORTED", code)


def test_long_body_is_not_marked_as_full_text(public_dns, monkeypatch):
    monkeypatch.setattr("bullbear.news_extraction._extract_text", lambda *_: "가" * (MAX_CONTENT_CHARS + 1))
    extractor = make_extractor(lambda request: httpx.Response(404) if request.url.path == "/robots.txt" else html_response())
    result = extractor.fetch(URL)
    assert (result.status, result.error_code, result.content) == ("EXTRACTION_FAILED", "BODY_TOO_LONG", None)


def test_concurrent_requests_share_one_download(public_dns):
    started = Event()
    release = Event()
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        started.set()
        assert release.wait(5)
        return html_response()

    extractor = make_extractor(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(extractor.fetch, URL)
        assert started.wait(5)
        second = pool.submit(extractor.fetch, URL)
        release.set()
        assert first.result(5) is second.result(5)
    assert requests == ["/robots.txt", "/article"]

"""Bounded public HTTP downloads and Trafilatura article extraction."""
from concurrent.futures import Future
from dataclasses import dataclass
import ipaddress
import re
import socket
from threading import Lock
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from protego import Protego
import trafilatura

Status = Literal["SUCCESS", "FETCH_FAILED", "EXTRACTION_FAILED", "UNSUPPORTED"]
USER_AGENT = "BullBearWorker/1.0"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_CONTENT_CHARS = 8_000
MIN_CONTENT_CHARS = 150
MAX_REDIRECTS = 3
REQUEST_TIMEOUT = 5.0
FETCH_TIMEOUT = 15.0
_REDIRECTS = {301, 302, 303, 307, 308}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_ACCESS_GATE = re.compile(
    r"access denied|forbidden|verify (?:that )?you are human|just a moment"
    r"|(?:sign|log) in to (?:read|continue)|subscribe to (?:read|continue)"
    r"|접근.{0,8}(?:차단|제한|권한)"
    r"|(?:로그인|구독|결제|회원가입).{0,14}(?:필요|후.{0,8}(?:읽|열람|이용|확인|보실|볼 수))"
    r"|(?:구독자|유료 회원).{0,8}(?:전용|공개)",
    re.IGNORECASE,
)
_ERROR_PAGE = re.compile(r"page not found|페이지.{0,12}(?:찾을 수 없|존재하지 않)", re.IGNORECASE)
_IPV6_TRANSLATION = tuple(ipaddress.ip_network(prefix) for prefix in ("64:ff9b::/96", "64:ff9b:1::/48"))


@dataclass(frozen=True)
class Extraction:
    status: Status
    url: str | None = None
    content: str | None = None
    error_code: str | None = None


class FetchError(Exception):
    def __init__(self, code: str, status: Status = "FETCH_FAILED", url: str | None = None):
        super().__init__(code)
        self.code, self.status, self.url = code, status, url


def article_url(raw: str) -> httpx.URL:
    try:
        if len(raw) > 4096 or re.search(r"[\x00-\x20\x7f\\]", raw):
            raise ValueError
        parts = urlsplit(raw)
        url = httpx.URL(raw)
        if (url.scheme not in {"https", "http"} or not parts.hostname or not url.host
                or parts.username is not None or parts.password is not None or "%" in url.host
                or parts.port not in (None, 443 if url.scheme == "https" else 80)):
            raise ValueError
        return url.copy_with(fragment=None)
    except (ValueError, httpx.InvalidURL, UnicodeError):
        raise FetchError("INVALID_URL", "UNSUPPORTED") from None


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        return not (address.scope_id or address.is_site_local or address.ipv4_mapped
                    or address.sixtofour or address.teredo or any(address in net for net in _IPV6_TRANSLATION))
    return True


def _resolve_public(host: str, port: int) -> str:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise FetchError("DNS_FAILED") from None
    ips = [entry[4][0] for entry in addresses]
    if not ips or any(not _public_ip(ip) for ip in ips):
        raise FetchError("BLOCKED_ADDRESS", "UNSUPPORTED")
    return ips[0]


def _remaining(deadline: float) -> float:
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise FetchError("TIMEOUT")
    return seconds


def _http_error(status: int) -> str:
    if status in {401, 403, 407, 451}:
        return "ACCESS_DENIED"
    if status in {404, 410}:
        return "NOT_FOUND"
    if status == 429:
        return "RATE_LIMITED"
    return f"HTTP_{status}"


def _extract_text(data: bytes, url: str, encoding: str | None) -> str | None:
    # lxml/Trafilatura also detect declarations in the HTML when the header has no charset.
    if encoding:
        try:
            data = data.decode(encoding, errors="replace")
        except LookupError:
            pass
    tree = trafilatura.load_html(data)
    if tree is None:
        return None
    headings = tree.xpath("//title/text() | //h1//text()")
    if any(_ACCESS_GATE.search(heading) for heading in headings):
        raise FetchError("ACCESS_DENIED", "EXTRACTION_FAILED", url)
    if any(_ERROR_PAGE.search(heading) for heading in headings):
        return None
    extracted = trafilatura.extract(tree, url=url, favor_precision=True,
                                    include_comments=False, include_tables=False)
    if not extracted:
        return None
    lines = [" ".join(line.split()) for line in extracted.splitlines()]
    content = "\n".join(line for line in lines if line and not _ACCESS_GATE.search(line) and not _ERROR_PAGE.search(line))
    if sum(char.isalnum() for char in content) < MIN_CONTENT_CHARS:
        if any(_ACCESS_GATE.search(line) for line in lines):
            raise FetchError("ACCESS_DENIED", "EXTRACTION_FAILED", url)
        return None
    return content


class ArticleExtractor:
    """One instance per debate. Coalesce requests and reuse failures as well as successes."""
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._transport = transport
        self._lock = Lock()
        self._articles: dict[str, Future[Extraction]] = {}
        self._robots: dict[str, Future[Protego | None]] = {}

    def _once[T](self, cache: dict[str, Future[T]], key: str, load, deadline: float) -> T:
        with self._lock:
            pending = cache.get(key)
            if pending is None:
                cache[key] = pending = Future()
                owner = True
            else:
                owner = False
        if owner:
            try:
                pending.set_result(load())
            except BaseException as exc:
                pending.set_exception(exc)
        try:
            return pending.result(timeout=_remaining(deadline)) if not pending.done() else pending.result()
        except TimeoutError:
            raise FetchError("TIMEOUT") from None

    def fetch(self, raw: str, *, deadline: float | None = None) -> Extraction:
        deadline = monotonic() + FETCH_TIMEOUT if deadline is None else deadline
        try:
            url = article_url(raw)
            return self._once(self._articles, str(url), lambda: self._extract(url, deadline), deadline)
        except FetchError as exc:
            return Extraction(exc.status, exc.url, error_code=exc.code)

    def _extract(self, url: httpx.URL, deadline: float) -> Extraction:
        resolved = str(url)
        try:
            resolved, _, data, encoding = self._download(url, deadline, robots=False)
            _remaining(deadline)
            content = _extract_text(data, resolved, encoding)
            _remaining(deadline)
            if content is None:
                return Extraction("EXTRACTION_FAILED", resolved, error_code="NO_ARTICLE_BODY")
            # A cut-off article cannot be described as verified full text.
            if len(content) > MAX_CONTENT_CHARS:
                return Extraction("EXTRACTION_FAILED", resolved, error_code="BODY_TOO_LONG")
            return Extraction("SUCCESS", resolved, content)
        except FetchError as exc:
            return Extraction(exc.status, exc.url or resolved, error_code=exc.code)
        except Exception:
            # Parser errors can include downloaded markup. Return a stable error instead.
            return Extraction("EXTRACTION_FAILED", resolved, error_code="PARSER_ERROR")

    def _check_robots(self, url: httpx.URL, deadline: float) -> None:
        robots_url = url.copy_with(path="/robots.txt", query=None)
        try:
            rules = self._once(self._robots, str(robots_url), lambda: self._load_robots(robots_url, deadline), deadline)
        except FetchError as exc:
            code = "ROBOTS_DENIED" if exc.code == "ACCESS_DENIED" else "ROBOTS_UNAVAILABLE"
            raise FetchError(code) from None
        if rules is not None and not rules.can_fetch(str(url), USER_AGENT):
            raise FetchError("ROBOTS_DENIED")

    def _load_robots(self, url: httpx.URL, deadline: float) -> Protego | None:
        _, status, data, _ = self._download(url, deadline, robots=True)
        if status in {404, 410}:
            return None
        return Protego.parse(data.decode("utf-8-sig", errors="replace"))

    def _download(self, url: httpx.URL, deadline: float, *, robots: bool) -> tuple[str, int, bytes, str | None]:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                _remaining(deadline)
                ip = _resolve_public(url.host, url.port or (443 if url.scheme == "https" else 80))
                if not robots:
                    self._check_robots(url, deadline)
                status, data, encoding, location = self._request(url, ip, deadline, robots=robots)
                if status not in _REDIRECTS:
                    return str(url), status, data, encoding
                if hop == MAX_REDIRECTS or not location:
                    raise FetchError("REDIRECT_LIMIT" if location else "INVALID_REDIRECT")
                if re.search(r"[\x00-\x20\x7f\\]", location):
                    raise FetchError("INVALID_REDIRECT", "UNSUPPORTED")
                target = article_url(str(url.join(location)))
                if url.scheme == "https" and target.scheme != "https":
                    raise FetchError("INSECURE_REDIRECT", "UNSUPPORTED")
                url = target
            except httpx.InvalidURL:
                raise FetchError("INVALID_REDIRECT", "UNSUPPORTED", str(url)) from None
            except FetchError as exc:
                raise FetchError(exc.code, exc.status, str(url)) from None
        raise AssertionError("unreachable redirect loop")

    def _request(self, url: httpx.URL, ip: str, deadline: float, *, robots: bool):
        # Connect to the address we checked. Keep the publisher's Host and TLS identity.
        pinned_url = url.copy_with(host=ip)
        limit = MAX_ROBOTS_BYTES if robots else MAX_HTML_BYTES
        try:
            with httpx.Client(transport=self._transport, trust_env=False,
                              timeout=min(REQUEST_TIMEOUT, _remaining(deadline))) as client:
                with client.stream("GET", pinned_url, follow_redirects=False,
                                   headers={"Host": url.netloc.decode("ascii"), "User-Agent": USER_AGENT,
                                            "Accept-Encoding": "identity"},
                                   extensions={"sni_hostname": url.raw_host.decode("ascii")}) as response:
                    status = response.status_code
                    if status in _REDIRECTS:
                        return status, b"", None, response.headers.get("location")
                    if robots and status in {404, 410}:
                        return status, b"", None, None
                    if status != 200:
                        raise FetchError(_http_error(status))
                    media_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    if (not robots and media_type not in _HTML_TYPES) or (robots and media_type not in {"", "text/plain"}):
                        raise FetchError("UNSUPPORTED_CONTENT_TYPE", "UNSUPPORTED")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise FetchError("UNSUPPORTED_ENCODING", "UNSUPPORTED")
                    declared = response.headers.get("content-length", "")
                    if declared.isdecimal() and int(declared) > limit:
                        raise FetchError("RESPONSE_TOO_LARGE", "UNSUPPORTED")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        _remaining(deadline)
                        if len(data) + len(chunk) > limit:
                            raise FetchError("RESPONSE_TOO_LARGE", "UNSUPPORTED")
                        data.extend(chunk)
                    return status, bytes(data), response.charset_encoding, None
        except httpx.TimeoutException:
            raise FetchError("TIMEOUT") from None
        except httpx.HTTPError:
            raise FetchError("NETWORK_ERROR") from None

"""Read text from a public news URL already resolved from a snapshot article ID."""
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_address
import re
import socket
import ssl
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit


_TIMEOUT = 8.0
_MAX_BYTES = 1_048_576
_MAX_REDIRECTS = 2
_REDIRECTS = {301, 302, 303, 307, 308}
_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
              'meta', 'param', 'source', 'track', 'wbr'}
_SKIP_TAGS = {'aside', 'button', 'footer', 'form', 'nav', 'noscript', 'script', 'style', 'template'}
_PARAGRAPH_TAGS = {'article', 'br', 'div', 'h1', 'h2', 'li', 'main', 'p', 'section'}
_BODY_MARKERS = {'articlebody', 'articlebodycontents', 'articlebodycontent', 'articlecontent',
                 'articlecontents', 'articletext', 'articletxt', 'articleviewcontentdiv', 'dicarea',
                 'newsctarticle', 'newsbody', 'newscontent', 'viewcontent', 'viewbody'}


class ArticleUnavailable(Exception):
    """A stable, URL-free reason for falling back to a stored summary."""


class _ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int, bool]] = []
        self.regions: dict[int, list[str]] = {1: [], 2: []}

    def handle_starttag(self, tag, attrs):
        _, level, hidden = self.stack[-1] if self.stack else ('', 0, False)
        attributes = dict(attrs)
        markers = ' '.join(attributes.get(key) or '' for key in ('id', 'class', 'itemprop'))
        names = {re.sub(r'[^a-z0-9]', '', value.lower()) for value in markers.split()}
        if names & _BODY_MARKERS:
            level = 2
        elif tag == 'article':
            level = max(level, 1)
        hidden = hidden or tag in _SKIP_TAGS or 'hidden' in attributes or attributes.get('aria-hidden') == 'true'
        if level and not hidden and tag in _PARAGRAPH_TAGS:
            self.regions[level].append('\n')
        if tag not in _VOID_TAGS:
            self.stack.append((tag, level, hidden))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            entry, level, hidden = self.stack[index]
            if entry == tag:
                if level and not hidden and tag in _PARAGRAPH_TAGS:
                    self.regions[level].append('\n')
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack:
            _, level, hidden = self.stack[-1]
            if level and not hidden:
                self.regions[level].append(data)

    def body(self) -> str:
        for level in (2, 1):
            text = '\n'.join(' '.join(line.split()) for line in ''.join(self.regions[level]).splitlines()
                             if line.strip())
            if len(text) >= 80:
                return text
        raise ArticleUnavailable('body_unavailable')


def _public_ip(host: str, port: int) -> str:
    # Validate all resolved addresses and connect to one of those exact addresses.
    # Resolving the hostname again during connect would allow a DNS change to bypass this check.
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for _, _, _, _, address in addresses:
        ip = ip_address(address[0])
        ip = getattr(ip, 'ipv4_mapped', None) or ip
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ArticleUnavailable('address_not_public')
    if not addresses:
        raise ArticleUnavailable('address_unavailable')
    return min(addresses, key=lambda record: record[0] != socket.AF_INET)[4][0]


class _PinnedConnection(HTTPConnection):
    def __init__(self, host: str, port: int, ip: str, secure: bool, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self.ip, self.secure = ip, secure

    def connect(self):
        sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        if self.secure:
            try:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            except BaseException:
                sock.close()
                raise
        self.sock = sock


def _read_response(url: str, deadline: float):
    if any(char.isspace() or ord(char) < 32 for char in url):
        raise ArticleUnavailable('invalid_url')
    target = urlsplit(url)
    if (target.scheme not in {'http', 'https'} or not target.hostname
            or target.username is not None or target.password is not None):
        raise ArticleUnavailable('invalid_url')
    secure = target.scheme == 'https'
    port = 443 if secure else 80
    if target.port not in (None, port):
        raise ArticleUnavailable('invalid_port')
    host = target.hostname.encode('idna').decode('ascii')
    ip = _public_ip(host, port)
    timeout = deadline - monotonic()
    if timeout <= 0:
        raise ArticleUnavailable('request_timeout')
    path = quote(target.path or '/', safe="/%:@!$&'()*+,;=-._~")
    if target.query:
        path += '?' + quote(target.query, safe="%/?@:!$&'()*+,;=-._~")
    connection = _PinnedConnection(host, port, ip, secure, timeout)
    try:
        connection.request('GET', path, headers={'Accept': 'text/html, text/plain', 'Accept-Encoding': 'identity',
                                                 'User-Agent': 'BullBearArticleReader/1.0'})
        with connection.getresponse() as response:
            if response.status in _REDIRECTS:
                location = response.getheader('Location')
                if not location:
                    raise ArticleUnavailable('invalid_redirect')
                return urljoin(url, location), None, None, None
            if response.status != 200:
                raise ArticleUnavailable('http_error')
            media_type = response.headers.get_content_type()
            encoding = response.getheader('Content-Encoding', 'identity').strip().lower()
            if media_type not in {'text/html', 'application/xhtml+xml', 'text/plain'} or encoding != 'identity':
                raise ArticleUnavailable('unsupported_content')
            data = bytearray()
            while len(data) <= _MAX_BYTES:
                if monotonic() >= deadline:
                    raise ArticleUnavailable('request_timeout')
                chunk = response.read1(min(16_384, _MAX_BYTES + 1 - len(data)))
                if not chunk:
                    return None, data, media_type, response.headers.get_content_charset()
                data.extend(chunk)
            raise ArticleUnavailable('response_too_large')
    finally:
        connection.close()


def fetch_article_body(url: str) -> str:
    deadline = monotonic() + _TIMEOUT
    visited = set()
    for _ in range(_MAX_REDIRECTS + 1):
        if url in visited:
            raise ArticleUnavailable('redirect_loop')
        visited.add(url)
        try:
            redirect, data, media_type, charset = _read_response(url, deadline)
        except TimeoutError:
            raise ArticleUnavailable('request_timeout') from None
        except (OSError, HTTPException, ValueError):
            raise ArticleUnavailable('request_failed') from None
        if redirect:
            url = redirect
            continue
        if not charset and media_type != 'text/plain':
            declared = re.search(rb'<meta[^>]+charset\s*=\s*[\'"]?([a-zA-Z0-9_-]+)', data[:4096], re.I)
            charset = declared[1].decode('ascii') if declared else None
        try:
            text = data.decode(charset or 'utf-8', errors='replace')
        except LookupError:
            text = data.decode('utf-8', errors='replace')
        if media_type == 'text/plain' and text.strip():
            return text.strip()
        parser = _ArticleText()
        parser.feed(text)
        parser.close()
        return parser.body()
    raise ArticleUnavailable('too_many_redirects')

from email.message import Message
from io import BytesIO
import socket

import pytest

from bullbear.data import article_body


class Response(BytesIO):
    def __init__(self, *, content=b'', status=200, location=None):
        super().__init__(content)
        self.status = status
        self.headers = Message()
        self.headers['Content-Type'] = 'text/html; charset=utf-8'
        if location:
            self.headers['Location'] = location

    def getheader(self, key, default=None):
        return self.headers.get(key, default)


def install_transport(monkeypatch, responses):
    connected = []

    def resolve(host, port, **_):
        address = '127.0.0.1' if host == 'private.example' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', (address, port))]

    class Connection:
        def __init__(self, host, port, ip, secure, timeout):
            self.host = host
            connected.append((host, ip, port, secure))

        def request(self, method, path, *, headers):
            assert method == 'GET'
            assert not {'Authorization', 'Cookie'} & headers.keys()

        def getresponse(self):
            return responses[self.host]

        def close(self):
            pass

    monkeypatch.setattr(article_body.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(article_body, '_PinnedConnection', Connection)
    return connected


def test_public_redirect_rechecks_address_and_returns_only_article_text(monkeypatch):
    paragraph = '메모리 수급과 기업 실적을 다룬 기사의 본문 문장입니다. ' * 4
    html = f'<main><aside>다른 기사</aside><div id="articleBody"><p>{paragraph}</p>' \
           '<script>숨은 스크립트</script></div><footer>페이지 하단</footer></main>'
    connected = install_transport(monkeypatch, {
        'news.example': Response(status=302, location='https://publisher.example/article'),
        'publisher.example': Response(content=html.encode('utf-8')),
    })
    assert article_body.fetch_article_body('https://news.example/story') == paragraph.strip()
    assert connected == [('news.example', '93.184.216.34', 443, True),
                         ('publisher.example', '93.184.216.34', 443, True)]


def test_redirect_to_private_address_is_rejected_before_connect(monkeypatch):
    connected = install_transport(monkeypatch, {
        'news.example': Response(status=302, location='https://private.example/article'),
    })
    with pytest.raises(article_body.ArticleUnavailable, match='address_not_public'):
        article_body.fetch_article_body('https://news.example/story')
    assert connected == [('news.example', '93.184.216.34', 443, True)]


def test_public_redirect_loop_stops_before_repeating_request(monkeypatch):
    connected = install_transport(monkeypatch, {
        'news.example': Response(status=302, location='https://news.example/story'),
    })
    with pytest.raises(article_body.ArticleUnavailable, match='redirect_loop'):
        article_body.fetch_article_body('https://news.example/story')
    assert connected == [('news.example', '93.184.216.34', 443, True)]

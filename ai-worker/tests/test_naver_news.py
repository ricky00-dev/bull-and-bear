from datetime import datetime

from bullbear.data.naver_news import filter_articles
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

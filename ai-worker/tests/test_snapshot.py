from datetime import date, datetime

import httpx
import pytest

from bullbear.data import NewsArticle, NewsSource
from bullbear.data.naver_news import NaverNewsSource
from bullbear.data.pykrx_dart import PykrxDartSource
from bullbear.snapshot import KST, build_snapshot
from bullbear.tools import SnapshotTools

from .fakes import AS_OF, NOW, FakeNews, FakeSource


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", news=FakeNews(), now=NOW)


def test_price_metrics(snap):
    f = snap.facts
    assert snap.as_of == AS_OF
    assert f["PX.CLOSE"].value == 399
    assert f["PX.RET_1M"].value == pytest.approx((399 / 378 - 1) * 100, abs=0.01)
    assert f["PX.MA20"].value == round(sum(range(380, 400)) / 20)
    assert f["PX.HIGH_52W"].value == 400  # 최근 252거래일 고가 최댓값


def test_financials_and_ttm_valuation(snap):
    f = snap.facts
    assert f["FIN.2026H1.REVENUE_YTD"].value == 600
    assert f["FIN.2026H1.REVENUE_YOY"].value == 20.0
    assert f["FIN.2025FY.NET_INCOME"].value == 70
    # TTM 순이익 = 70 + 40 - 30 = 80, 시가총액 = 399 * 10
    assert f["VAL.NET_INCOME_TTM"].value == 80
    assert f["VAL.MKTCAP"].value == 3990
    assert f["VAL.PER_TTM"].value == pytest.approx(3990 / 80, abs=0.01)
    assert f["VAL.PBR"].value == pytest.approx(3990 / 2000, abs=0.01)
    assert f["VAL.DEBT_RATIO"].value == 50.0
    assert set(f["VAL.PER_TTM"].inputs) == {"VAL.MKTCAP", "VAL.NET_INCOME_TTM"}


def test_disclosure_fact(snap):
    d = snap.facts["DISC.20261001000123"]
    assert d.value is None and d.as_of == date(2026, 10, 1)


def test_snapshot_id_is_content_hash():
    a = build_snapshot(FakeSource(), "000000", "가짜전자", news=FakeNews(), now=NOW)
    b = build_snapshot(FakeSource(), "000000", "가짜전자", news=FakeNews(), now=NOW)
    assert a.snapshot_id == b.snapshot_id
    assert a.snapshot_id.startswith("000000-20261016-")


def test_save_load_roundtrip(snap, tmp_path):
    snap.save(tmp_path)
    loaded = type(snap).load(tmp_path, snap.snapshot_id)
    assert loaded.facts == snap.facts


def test_tools_only_return_their_category(snap):
    import json

    out = json.loads(SnapshotTools(snap)("get_valuation", {}))
    assert out["snapshot_id"] == snap.snapshot_id
    assert all(item["id"].startswith("VAL.") for item in out["items"])


def test_news_facts_and_cutoff(snap):
    news = snap.by_category("news")
    assert [n.label for n in news] == ["가짜전자, 자사주 1조 매입 결정"]  # 생성 시각 이후 기사는 제외
    assert news[0].value is None and news[0].published_at is not None


def test_news_stops_at_as_of_close_when_prices_lag():
    """시세가 늦게 올라와 기준일이 며칠 전이면, 그 뒤 기사(채점 구간 정보)는 넣지 않는다."""
    class LateNews(NewsSource):
        name = "late-news"
        calls = []

        def search(self, ticker, name, start, end):
            self.calls.append(end)
            articles = [
                NewsArticle("1", datetime(2026, 10, 16, 9, 30, tzinfo=KST), "기준일 장중 기사", "요약", "https://news/1"),
                NewsArticle("2", datetime(2026, 10, 16, 16, 10, tzinfo=KST), "기준일 장 마감 뒤 기사", "요약", "https://news/2"),
                NewsArticle("3", datetime(2026, 10, 19, 10, 0, tzinfo=KST), "다음 거래일 장중 반등", "요약", "https://news/3"),
            ]
            return articles  # 공급자가 범위를 무시해도 스냅샷이 다시 자른다

    news = LateNews()
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", news=news,
                          now=datetime(2026, 10, 19, 21, 0, tzinfo=KST))
    assert snap.as_of == AS_OF
    assert news.calls == [datetime(2026, 10, 16, 15, 30, tzinfo=KST)]
    assert [n.label for n in snap.by_category("news")] == ["기준일 장중 기사"]


def test_without_news_source_warns():
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    assert not snap.by_category("news")
    assert "뉴스 소스 미설정" in snap.warnings


def test_optional_news_failure_warns_and_preserves_price_snapshot():
    def handle(request):
        return httpx.Response(503, text="PRIVATE provider response")

    news = NaverNewsSource("test-id", "test-secret")
    news._http.close()
    news._http = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        snap = build_snapshot(FakeSource(), "000000", "가짜전자", news=news, now=NOW)
    finally:
        news._http.close()

    assert snap.as_of == AS_OF
    assert snap.facts["PX.CLOSE"].value == 399
    assert snap.facts["VAL.PER_TTM"].value == pytest.approx(3990 / 80, abs=0.01)
    assert not snap.by_category("news")
    assert any(warning.startswith("뉴스 없음:") for warning in snap.warnings)
    assert "PRIVATE" not in " ".join(snap.warnings)


def test_optional_dart_failure_warns_and_preserves_price_snapshot(tmp_path, monkeypatch):
    import io
    import zipfile

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as company_file:
        company_file.writestr("CORPCODE.xml", "<result><list><stock_code>000000</stock_code>"
                             "<corp_code>test-corp</corp_code><corp_name>가짜전자</corp_name></list></result>")

    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/corpCode.xml"):
            return httpx.Response(200, content=archive.getvalue())
        return httpx.Response(503, text="PRIVATE provider response: test-key")

    source = PykrxDartSource("test-key", tmp_path)
    monkeypatch.setattr(source, "get_daily_prices", FakeSource().get_daily_prices)
    source._dart._http.close()
    source._dart._http = httpx.Client(base_url="https://opendart.example.test/api", transport=httpx.MockTransport(handle))
    try:
        snap = build_snapshot(source, "000000", "가짜전자", news=FakeNews(), now=NOW)
    finally:
        source._dart._http.close()

    assert snap.as_of == AS_OF and snap.facts["PX.CLOSE"].value == 399
    assert snap.by_category("news")
    assert not snap.by_category("financials") and not snap.by_category("valuation") and not snap.by_category("disclosure")
    for prefix in ("재무 데이터 없음:", "발행주식수 없음:", "공시 없음:"):
        assert any(warning.startswith(prefix) for warning in snap.warnings)
    assert {path.rsplit("/", 1)[-1] for path in calls} == {
        "corpCode.xml", "fnlttSinglAcnt.json", "stockTotqySttus.json", "list.json"}
    assert "PRIVATE" not in " ".join(snap.warnings) and "test-key" not in " ".join(snap.warnings)

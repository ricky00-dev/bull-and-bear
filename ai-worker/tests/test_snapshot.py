from datetime import date

import pytest

from bullbear.snapshot import build_snapshot
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


def test_without_news_source_warns():
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    assert not snap.by_category("news")
    assert "뉴스 소스 미설정" in snap.warnings

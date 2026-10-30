"""Large market snapshots must not evict the background query's core concepts."""
from bullbear.rag.retrieval import query_terms
from bullbear.snapshot import Fact, build_snapshot
from .fakes import FakeSource, NOW


def snapshot_with_articles():
    snapshot = build_snapshot(FakeSource(), "005930", "삼성전자", now=NOW)
    for category, prefix in (("news", "NEWS"), ("disclosure", "DISC")):
        for i in range(30):
            fid = f"{prefix}.{20261030000000+i}.abcdef{i:08x}"
            snapshot.facts[fid] = Fact(id=fid, category=category,
                label=f"AAA제목{i} BBB시장기사{i} CCC공개내용{i}", value=None, unit="text",
                as_of=snapshot.as_of, source="synthetic")
    return snapshot


def test_full_snapshot_preserves_target_identity_and_financial_aliases():
    snapshot = snapshot_with_articles()
    original = snapshot.model_dump_json()
    terms = query_terms(snapshot)
    assert {"kospi", "코스피", "초과수익", "거래일", "event_relevance", "005930", "삼성전자",
            "per", "주가수익비율", "volatility", "변동성", "roe", "자기자본이익률"} <= set(terms)
    assert {"disclosure", "공시", "news", "뉴스"} <= set(terms)
    assert not any("제목" in term or "시장기사" in term or "공개내용" in term or term.startswith("abcdef")
                   for term in terms)
    assert not any(term.startswith("20261030") for term in terms)
    assert len(terms) == len(set(terms)) <= 128
    assert snapshot.model_dump_json() == original


def test_core_terms_survive_budget_pressure_and_order_is_deterministic():
    snapshot = snapshot_with_articles()
    for i in range(300):
        fid = f"VAL.AAA{i}"
        snapshot.facts[fid] = Fact(id=fid, category="valuation", label=f"AAAextra{i}", value=1,
                                  unit="x", as_of=snapshot.as_of, source="synthetic")
    terms = query_terms(snapshot)
    assert len(terms) == 128
    assert {"per", "주가수익비율", "volatility", "변동성", "코스피", "삼성전자", "005930"} <= set(terms)
    reverse = snapshot.model_copy(deep=True)
    reverse.facts = dict(reversed(list(reverse.facts.items())))
    assert query_terms(reverse) == terms


def test_more_news_changes_neither_background_concepts_nor_term_order():
    snapshot = snapshot_with_articles()
    before = query_terms(snapshot)
    sample = next(f for f in snapshot.facts.values() if f.category == "news")
    for i in range(200):
        fid = f"NEWS.more{i}"
        snapshot.facts[fid] = sample.model_copy(update={"id": fid, "label": f"전혀다른제목{i}"})
    assert query_terms(snapshot) == before

import pytest

from bullbear.snapshot import build_snapshot
from bullbear.verifier import verify

from .fakes import NOW, FakeNews, FakeSource, statement


@pytest.fixture(scope="module")
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", news=FakeNews(), now=NOW)


def codes(result, severity="error"):
    return [i.code for i in result.issues if i.severity == severity]


def test_exact_values_pass(snap):
    per = snap.facts["VAL.PER_TTM"].value
    r = verify(statement(("E1", "VAL.PER_TTM", per), ("E2", "PX.CLOSE", 399)), snap)
    assert r.passed and r.correct == 2


def test_rounding_tolerance(snap):
    # 49.88배를 49.9로 반올림해도 통과
    r = verify(statement(("E1", "VAL.PER_TTM", 49.9)), snap)
    assert r.passed


def test_wrong_value_rejected(snap):
    r = verify(statement(("E1", "VAL.PER_TTM", 12.0)), snap)
    assert not r.passed and codes(r) == ["value_mismatch"]


def test_unknown_source_rejected(snap):
    r = verify(statement(("E1", "VAL.EV_EBITDA", 8.0)), snap)
    assert codes(r) == ["unknown_source"]


def test_disclosure_requires_null(snap):
    assert verify(statement(("E1", "DISC.20261001000123", None)), snap).passed
    assert not verify(statement(("E1", "DISC.20261001000123", 1.0)), snap).passed


def test_dangling_ref_rejected(snap):
    st = statement(("E1", "PX.CLOSE", 399), argument="종가 [E1], 그리고 [E2].")
    assert codes(verify(st, snap)) == ["dangling_ref"]


def test_no_evidence_rejected(snap):
    assert codes(verify(statement(argument="근거 없음"), snap)) == ["no_evidence"]


def test_unbacked_percentage_is_warning(snap):
    debt = snap.facts["VAL.DEBT_RATIO"].value  # 50%
    st = statement(("E1", "VAL.DEBT_RATIO", debt), argument=f"부채비율 {debt}% [E1], 영업이익률은 35%다.")
    r = verify(st, snap)
    assert r.passed
    assert codes(r, "warning") == ["unbacked_number"]

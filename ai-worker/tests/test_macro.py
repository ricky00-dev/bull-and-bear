"""HTTP transport fixtures. These cases do not require external API keys."""
from datetime import date, datetime, timedelta

import httpx
import pytest

from bullbear.data.macro import BOK_RATE, FRED_SERIES, MacroSource
from bullbear.snapshot import KST, build_snapshot
from .fakes import AS_OF, NOW, FakeSource

CUTOFF = datetime(2026, 10, 16, 15, 30, tzinfo=KST)


def fred_response(request, value="24.0", *, future_only=False):
    vintage = request.url.params["realtime_start"]
    assert request.url.params["realtime_end"] == vintage == "2026-10-15"
    assert request.url.params["observation_end"] == vintage
    rows = [{"date": "2026-10-16", "realtime_start": "2026-10-16",
             "realtime_end": "2026-10-16", "value": "999"}]
    if not future_only:
        rows.extend([
            {"date": "2026-10-15", "realtime_start": vintage, "realtime_end": vintage, "value": "."},
            {"date": "2026-10-14", "realtime_start": vintage, "realtime_end": vintage, "value": value},
        ])
    return httpx.Response(200, json={"realtime_start": vintage, "realtime_end": vintage, "observations": rows})


def ecos_response(value="2.5"):
    return httpx.Response(200, json={"StatisticSearch": {"row": [
        {"STAT_CODE": "722Y001", "ITEM_CODE1": "0101000", "TIME": "20261015", "DATA_VALUE": value},
        {"STAT_CODE": "722Y001", "ITEM_CODE1": "0101000", "TIME": "20261017", "DATA_VALUE": "999"},
    ]}})


def test_fred_uses_prior_vintage_and_ecos_requires_observation_before_cutoff(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "ecos.bok.or.kr":
            assert request.url.path.endswith("/722Y001/D/20260916/20261016/0101000")
            return ecos_response()
        return fred_response(request)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        source = MacroSource("fixture-fred", "fixture-ecos", tmp_path, vix_enabled=True,
                             client=client, clock=lambda: CUTOFF + timedelta(hours=1))
        snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, macro=source)
        assert snap.data_status[BOK_RATE] == "AVAILABILITY_UNVERIFIED"
        assert BOK_RATE not in snap.facts
        assert {r.url.params.get("series_id") for r in calls[:-1]} == {s[1] for s in FRED_SERIES}
        for key, *_ in FRED_SERIES:
            f = snap.facts[key]
            assert f.status == "OK" and f.value == 24
            assert f.as_of == date(2026, 10, 14) and f.vintage_date == date(2026, 10, 15)
            assert f.available_at is None

        def no_rewrite(request):
            return ecos_response("3.0")

        observed_at = CUTOFF + timedelta(hours=1)
        client2 = httpx.Client(transport=httpx.MockTransport(no_rewrite))
        with client2:
            next_run = MacroSource(None, "fixture-ecos", tmp_path, client=client2,
                                   clock=lambda: observed_at + timedelta(days=1))
            bok = next_run.collect(CUTOFF + timedelta(days=1))[-1]
        assert bok.status == "OK" and bok.value == 2.5
        assert bok.available_at == observed_at
    finally:
        client.close()


@pytest.mark.parametrize("failure", ["http", "json", "future"])
def test_optional_macro_failure_is_private_and_preserves_snapshot(tmp_path, failure):
    def handle(request):
        if failure == "http":
            return httpx.Response(503, text="PRIVATE fixture key")
        if request.url.host == "ecos.bok.or.kr" or failure == "json":
            return httpx.Response(200, json={"malformed": True})
        return fred_response(request, future_only=True)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        macro = MacroSource("fixture-fred", "fixture-ecos", tmp_path, client=client, clock=lambda: NOW)
        snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, macro=macro)
    assert not snap.by_category("macro") and snap.as_of == AS_OF and snap.facts["PX.CLOSE"].value == 399
    assert snap.data_status[BOK_RATE] == "FAILED"
    assert snap.data_status["MACRO.VIX"] == "UNSUPPORTED"  # opt-in, even when FRED is configured
    assert snap.data_status["MACRO.WTI_SPOT"] == ("AVAILABILITY_UNVERIFIED" if failure == "future" else "FAILED")
    assert "PRIVATE" not in snap.model_dump_json() and "fixture-fred" not in snap.model_dump_json()


def test_missing_macro_keys_make_no_requests(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("unexpected network"))) as client:
        macro = MacroSource(None, None, tmp_path, vix_enabled=True, client=client)
        assert {r.status for r in macro.collect(CUTOFF)} == {"UNSUPPORTED"}

from datetime import date

import pytest

from bullbear.config import load_settings
from bullbear.server.errors import ApiError
from .fakes import AS_OF
from .http_fixture import fixture_market


def test_settled_prices_are_opt_in_and_keep_snapshot_date():
    settings = load_settings()
    normal = fixture_market(settings)
    settled = fixture_market(settings, settled_prices=True)
    end = date(2026, 11, 2)
    assert normal.daily('005930', AS_OF, end)['items'][-1]['date'] == AS_OF.isoformat()
    assert settled.quote('005930').bars[-1].date == AS_OF
    rows = settled.daily('005930', AS_OF, end)['items']
    assert len(rows) == 11
    assert rows[3] == {'date': '2026-10-21', 'close': 402.0}
    assert rows[7] == {'date': '2026-10-27', 'close': 406.0}
    assert rows[-1] == {'date': '2026-10-30', 'close': 409.0}
    indices = settled.daily('KOSPI', AS_OF, end, index=True)['items']
    assert [r['date'] for r in indices] == [r['date'] for r in rows]
    assert indices[7]['close'] == 1406.0


def test_settled_prices_preserve_validation_and_requested_window():
    market = fixture_market(load_settings(), settled_prices=True)
    rows = market.daily('005930', date(2026, 10, 27), date(2026, 10, 27))['items']
    assert rows == [{'date': '2026-10-27', 'close': 406.0}]
    assert market.daily('005930', date(2026, 11, 1), date(2026, 11, 2)) == {'items': []}
    with pytest.raises(ApiError):
        market.daily('bad', AS_OF, AS_OF)
    with pytest.raises(ApiError):
        market.daily('bad', date(2026, 10, 27), date(2026, 10, 27))
    with pytest.raises(ApiError):
        market.daily('UNKNOWN', date(2026, 10, 27), date(2026, 10, 27), index=True)
    with pytest.raises(ApiError):
        market.daily('005930', date(2026, 10, 30), AS_OF)

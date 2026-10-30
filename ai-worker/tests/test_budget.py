from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest

from bullbear.budget import BudgetError, PRICE, SpendLedger, input_upper_bound


def payload(**changes):
    return {"model": "gpt-5-mini", "instructions": "규칙", "input": [{"role": "user", "content": "질문"}],
            "tools": [{"type": "function", "name": "local", "parameters": {"type": "object"}}],
            "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
            "max_output_tokens": 16000, **changes}


def response(inputs=100, output=20, cached=30, model="gpt-5-mini-2025-08-07"):
    return NS(model=model, usage=NS(input_tokens=inputs, output_tokens=output,
                                   input_tokens_details={"cached_tokens": cached}))


def test_settlement_uses_cached_input_once_and_is_durable(tmp_path):
    ledger = SpendLedger(tmp_path / "budget.db", "approved", "3")
    request = ledger.reserve(payload(), scope="a")
    assert ledger.summary()["reserved_unconfirmed_usd"] == .128
    ledger.settle(request, response())
    reopened = SpendLedger(tmp_path / "budget.db", "approved", "3")
    assert reopened.summary()["cost_usd"] == pytest.approx((70*.25 + 30*.025 + 20*2)/1_000_000)
    assert reopened.summary()["unconfirmed_requests"] == 0
    with pytest.raises(BudgetError):
        ledger.settle(request, response())


def test_unconfirmed_retains_reservation_across_conditions_and_restart(tmp_path):
    path = tmp_path / "budget.db"
    ledger = SpendLedger(path, "same", ".2")
    request = ledger.reserve(payload(), scope="condition-a")
    ledger.unconfirmed(request)
    reopened = SpendLedger(path, "same", ".2")
    with pytest.raises(BudgetError):
        reopened.reserve(payload(), scope="condition-b")
    assert reopened.summary()["cost_usd"] is None
    assert reopened.summary()["accounted_upper_usd"] == .128


def test_missing_usage_cannot_become_zero_cost(tmp_path):
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    request = ledger.reserve(payload(), scope="a")
    ledger.settle(request, NS(model="gpt-5-mini", usage=None))
    assert ledger.summary()["cost_usd"] is None


@pytest.mark.parametrize("model", ["unknown", "gpt-5-mini-2099-01-01", "gpt-5.4"])
def test_unknown_requested_and_actual_model_fail_closed(tmp_path, model):
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    with pytest.raises(BudgetError):
        ledger.reserve(payload(model=model), scope="a")
    request = ledger.reserve(payload(), scope="a")
    with pytest.raises(BudgetError):
        ledger.settle(request, response(model=model))
    assert ledger.summary()["halted"] and ledger.summary()["cost_usd"] is None
    with pytest.raises(BudgetError):
        ledger.reserve(payload(), scope="a")


@pytest.mark.parametrize("bad", ["NaN", "0", "-1", "0.0000000001"])
def test_invalid_limits(tmp_path, bad):
    with pytest.raises(ValueError):
        SpendLedger(tmp_path / "budget.db", "same", bad)


def test_authorization_cannot_change_limit_or_price(tmp_path):
    from dataclasses import replace
    path = tmp_path / "budget.db"
    SpendLedger(path, "same", "3")
    with pytest.raises(BudgetError):
        SpendLedger(path, "same", "4")
    with pytest.raises(BudgetError):
        SpendLedger(path, "same", "3", price=replace(PRICE, version="new"))


def test_context_check_includes_system_tools_schema_and_reasoning(tmp_path):
    request = payload()
    base = input_upper_bound(request, 16000)
    assert input_upper_bound(payload(instructions="가" * 1000), 16000) > base + 2500
    assert input_upper_bound(payload(input=[{"type": "reasoning", "encrypted_content": "abc"}]), 16000) > 16000
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    with pytest.raises(BudgetError, match="context"):
        ledger.reserve(payload(instructions="x"*400000), scope="a")
    assert ledger.summary()["requests"] == 0


@pytest.mark.parametrize("change", [
    {"tools": [{"type": "web_search"}]}, {"previous_response_id": "r"},
    {"service_tier": "priority"}, {"input": [{"type": "input_image", "image_url": "x"}]},
    {"truncation": "auto"}, {"max_output_tokens": 128001},
])
def test_unbudgeted_fees_or_inputs_rejected(tmp_path, change):
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    with pytest.raises(BudgetError):
        ledger.reserve(payload(**change), scope="a")


def test_concurrent_reservations_cannot_overspend(tmp_path):
    path = tmp_path / "budget.db"
    SpendLedger(path, "same", ".2")
    def reserve(_):
        try:
            SpendLedger(path, "same", ".2").reserve(payload(), scope="a")
            return True
        except BudgetError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert sum(results) == 1


def test_usage_exceeding_reservation_halts_authorization(tmp_path):
    ledger = SpendLedger(tmp_path / "budget.db", "same", "3")
    request = ledger.reserve(payload(), scope="a")
    with pytest.raises(BudgetError):
        ledger.settle(request, response(inputs=500000, output=20000, cached=0))
    assert ledger.summary()["halted"]

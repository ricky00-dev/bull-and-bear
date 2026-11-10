"""Offline transport and spend-boundary tests for the local experiment runner."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest

import worker_minimal_experiment as runner
from bullbear.anthropic_budget import BudgetDenied, WorkerSpendLedger
from bullbear.llm import LLMError
from bullbear.snapshot import Fact, Snapshot


class Model(SimpleNamespace):
    def model_dump(self, **kwargs):
        def plain(value):
            if isinstance(value, Model):
                return {key: plain(child) for key, child in vars(value).items()}
            if isinstance(value, list):
                return [plain(child) for child in value]
            return value
        return plain(self)


def message(*blocks, stop="end_turn"):
    return Model(model=runner.MODEL, content=list(blocks), stop_reason=stop,
                 usage=Model(input_tokens=100, output_tokens=20,
                             cache_read_input_tokens=0, cache_creation_input_tokens=0))


def text(value="근거와 해석을 구분한 발언입니다."):
    return Model(type="text", text=value)


def tool(name="get_price_metrics", **arguments):
    return Model(type="tool_use", id="tool-1", name=name, input=arguments)


class FakeClient:
    max_retries = 0

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **parameters):
        self.requests.append(deepcopy(parameters))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return SimpleStream(response)


class SimpleStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self.response


@pytest.fixture
def snapshot():
    fact = Fact(id="PX.CLOSE", category="price", label="종가", value=123,
                unit="KRW/share", as_of=date(2026, 11, 4), source="fixture")
    return Snapshot(snapshot_id="fixed", ticker="005930", name="삼성전자",
                    as_of=fact.as_of, created_at=datetime(2026, 11, 4, 9, tzinfo=timezone.utc),
                    provider="fixture", facts={fact.id: fact})


def completion(tmp_path, snapshot, responses, **kwargs):
    client = FakeClient(responses)
    ledger = WorkerSpendLedger(tmp_path / "budget.sqlite3", "offline-test", "3")
    return runner.TextCompletion(client, snapshot, ledger, tmp_path, **kwargs)


def invoke(complete, role="bull"):
    return complete(role, "역할과 문체", [{"role": "user", "content": "첫 주장"}])


def test_tool_result_uses_only_bound_snapshot_and_settles_every_request(tmp_path, snapshot):
    # Even a model-supplied alternate identifier cannot select another snapshot.
    complete = completion(tmp_path, snapshot, [
        message(tool(snapshot_id="other"), stop="tool_use"), message(text())])
    original = [{"role": "user", "content": "첫 주장"}]
    assert complete("bull", "역할과 문체", original) == "근거와 해석을 구분한 발언입니다."
    assert original == [{"role": "user", "content": "첫 주장"}]
    requests = complete.client.requests
    returned = json.loads(requests[1]["messages"][-1]["content"][0]["content"])
    assert returned["snapshot_id"] == "fixed"
    assert returned["items"][0]["value"] == 123
    assert requests[0]["output_config"] == {"effort": "medium"}
    assert len(requests[0]["tools"]) == 5
    assert complete.ledger.summary()["known_cost_usd"] == pytest.approx(0.0008)
    assert complete.ledger.summary()["unconfirmed_requests"] == 0
    assert len(list(tmp_path.glob("*-response.json"))) == 2


def test_unknown_transport_usage_halts_next_dispatch_without_retry(tmp_path, snapshot):
    complete = completion(tmp_path, snapshot, [TimeoutError("transport")])
    with pytest.raises(TimeoutError):
        invoke(complete)
    report = complete.ledger.summary()
    assert report["halted"] and report["unconfirmed_requests"] == 1
    assert report["reserved_unconfirmed_usd"] == 2.16
    with pytest.raises(BudgetDenied):
        invoke(complete)
    assert len(complete.client.requests) == 1


def test_loop_limit_stops_after_paid_tool_responses_are_settled(tmp_path, snapshot):
    complete = completion(tmp_path, snapshot, [message(tool(), stop="tool_use") for _ in range(2)],
                          max_requests=2)
    with pytest.raises(LLMError, match="limit"):
        invoke(complete)
    assert len(complete.client.requests) == 2
    assert complete.ledger.summary()["known_cost_usd"] == pytest.approx(0.0008)
    assert complete.ledger.summary()["unconfirmed_requests"] == 0


@pytest.mark.parametrize("response", [message(text(" ")), message(text("잘린 발언"), stop="max_tokens")])
def test_invalid_completion_fails_without_rewriting_or_losing_usage(tmp_path, snapshot, response):
    complete = completion(tmp_path, snapshot, [response])
    with pytest.raises(LLMError):
        invoke(complete)
    assert len(complete.client.requests) == 1
    assert complete.turns == []
    assert complete.ledger.summary()["known_cost_usd"] == pytest.approx(0.0004)
    assert complete.ledger.summary()["unconfirmed_requests"] == 0


def test_unknown_tool_gets_error_result_and_cannot_read_external_data(tmp_path, snapshot):
    complete = completion(tmp_path, snapshot, [
        message(tool("web_search", query="outside data"), stop="tool_use"), message(text())])
    invoke(complete, "moderator")
    request = complete.client.requests[1]
    assert request["output_config"] == {"effort": "high"}
    result = request["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "알 수 없는" in result["content"]


def test_request_audit_write_failure_releases_reservation_before_transport(tmp_path, snapshot, monkeypatch):
    complete = completion(tmp_path, snapshot, [message(text())])

    def fail_save(*_):
        raise OSError("disk full")

    monkeypatch.setattr(runner, "save", fail_save)
    with pytest.raises(OSError):
        invoke(complete)
    assert complete.client.requests == []
    report = complete.ledger.summary()
    assert report["known_cost_usd"] == 0
    assert report["unconfirmed_requests"] == 0
    assert not report["halted"]

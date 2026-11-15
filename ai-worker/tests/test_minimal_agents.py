import json
from datetime import date, datetime

import pytest

from bullbear.experiments.minimal_agents import build_messages, build_system, run_debate
from bullbear.snapshot import Fact, KST, Snapshot
from bullbear.tools import SnapshotTools, TOOL_DEFINITIONS


@pytest.fixture
def snapshot():
    return Snapshot(
        snapshot_id="frozen-example", ticker="000000", name="가짜전자",
        as_of=date(2026, 11, 6), created_at=datetime(2026, 11, 9, 9, tzinfo=KST),
        provider="fixture", facts={
            "PX.CLOSE": Fact(id="PX.CLOSE", category="price", label="종가",
                             value=123456, unit="KRW/share", as_of=date(2026, 11, 6),
                             source="fixture"),
        },
    )


def test_round_join_hides_current_speech_and_moderator_sees_all_six(snapshot):
    calls = []
    observed = []

    def complete(role, system, messages):
        payload = json.loads(messages[0]["content"])
        calls.append((role, payload))
        return f"speech-{len(calls)}"

    def on_turn(turn):
        observed.append(dict(turn))
        turn["text"] = "callback mutation must not leak"

    result = run_debate(snapshot, complete, on_turn)
    assert [role for role, _ in calls] == ["bull", "bear"] * 3 + ["moderator"]
    assert [len(payload["history"]) for _, payload in calls] == [0, 0, 2, 2, 4, 4, 6]
    for first, second in ((0, 1), (2, 3), (4, 5)):
        assert calls[first][1]["history"] == calls[second][1]["history"]
    assert [entry["text"] for entry in calls[-1][1]["history"]] == [
        f"speech-{number}" for number in range(1, 7)
    ]
    assert [turn["round"] for turn in result["turns"]] == [
        "opening", "opening", "rebuttal", "rebuttal", "closing", "closing"
    ]
    assert result["moderator"] == {"role": "moderator", "round": "verdict", "text": "speech-7"}
    assert observed == [*result["turns"], result["moderator"]]


def test_messages_drop_private_metadata_and_current_or_future_rounds(snapshot):
    history = [
        {"role": "bull", "round": "opening", "text": "공개 주장", "analysis": "비공개 분석"},
        {"role": "bear", "round": "opening", "text": "공개 반대 주장", "review": "검토 기록"},
        {"role": "bull", "round": "rebuttal", "text": "같은 라운드 발언"},
        {"role": "bear", "round": "closing", "text": "미래 발언"},
        {"role": "moderator", "round": "verdict", "text": "최종 판정"},
    ]
    messages = build_messages("bear", "rebuttal", snapshot, history)
    payload = json.loads(messages[0]["content"])
    assert payload["history"] == [
        {"role": "bull", "round": "opening", "text": "공개 주장"},
        {"role": "bear", "round": "opening", "text": "공개 반대 주장"},
    ]
    assert "비공개 분석" not in messages[0]["content"]
    assert "검토 기록" not in messages[0]["content"]


def test_snapshot_boundary_preserves_price_date_and_uses_existing_tools(snapshot):
    before = snapshot.model_dump(mode="json")
    tools = SnapshotTools(snapshot)
    calls = []

    def complete(role, system, messages):
        payload = json.loads(messages[0]["content"])
        assert payload["subject"] == {"name": "가짜전자", "ticker": "000000"}
        assert payload["price_as_of"] == "2026-11-06"
        assert payload["information_cutoff"] == "2026-11-09T09:00:00+09:00"
        assert payload["snapshot_id"] == snapshot.snapshot_id
        assert "123456" not in system + messages[0]["content"]
        prices = json.loads(tools("get_price_metrics", {}))
        assert prices["snapshot_id"] == snapshot.snapshot_id
        assert prices["items"][0]["value"] == 123456
        calls.append(role)
        return "자유로운 발언입니다."

    result = run_debate(snapshot, complete)
    assert len(calls) == 7
    assert result["snapshot_id"] == snapshot.snapshot_id
    assert len(TOOL_DEFINITIONS) == 5
    assert snapshot.model_dump(mode="json") == before


def test_free_prose_is_preserved_without_length_checks_or_regeneration(snapshot):
    text = "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다.\n다른 문단입니다."
    calls = []

    def complete(role, system, messages):
        calls.append(role)
        return text

    result = run_debate(snapshot, complete)
    assert len(calls) == 7
    assert all(turn["text"] == text for turn in [*result["turns"], result["moderator"]])


def test_transport_failure_stops_without_hidden_retry_or_fake_completion(snapshot):
    observed = []
    calls = []

    def complete(role, system, messages):
        calls.append(role)
        if len(calls) == 2:
            raise RuntimeError("transport failed")
        return "첫 발언"

    with pytest.raises(RuntimeError, match="transport failed"):
        run_debate(snapshot, complete, observed.append)
    assert calls == ["bull", "bear"]
    assert observed == [{"role": "bull", "round": "opening", "text": "첫 발언"}]


@pytest.mark.parametrize("role,round_kind", [("moderator", "opening"), ("bull", "verdict")])
def test_rejects_wrong_role_round_pair_before_dispatch(snapshot, role, round_kind):
    with pytest.raises(ValueError, match="role/round"):
        build_messages(role, round_kind, snapshot, [])


def test_empty_completion_is_not_counted_as_a_completed_turn(snapshot):
    observed = []
    with pytest.raises(ValueError, match="Empty or non-text"):
        run_debate(snapshot, lambda *_: "  ", observed.append)
    assert observed == []


def test_role_and_task_inputs_do_not_impose_a_grading_question(snapshot):
    systems = [build_system(role, snapshot) for role in ("bull", "bear", "moderator")]
    messages = [build_messages(role, stage, snapshot, [])[0]["content"]
                for role, stage in (("bull", "opening"), ("bear", "rebuttal"),
                                    ("moderator", "verdict"))]
    for text in [*systems, *messages]:
        assert all(term not in text for term in ("7거래일", "코스피", "2%p", "초과수익", "채점"))
    assert all("조회 도구" in text and "존댓말" in text for text in systems)

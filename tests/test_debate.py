import pytest

from bullbear.debate import Debate, verification_stats
from bullbear.events import EventLog
from bullbear.schemas import Decision, Side
from bullbear.snapshot import build_snapshot

from .fakes import AS_OF, FakeSource, ScriptedDebater, ScriptedModerator, statement


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", today=AS_OF)


def make(snap, tmp_path, *, actions=(), bad_first=False, max_extra=1):
    good = statement(("E1", "PX.CLOSE", 399))
    bad = statement(("E1", "PX.CLOSE", 1.0)) if bad_first else None
    debater, moderator = ScriptedDebater(good, bad), ScriptedModerator(list(actions))
    log = EventLog(tmp_path / "d.jsonl")
    return Debate(snap, debater, moderator, log, debate_id="t", max_extra_rounds=max_extra), debater, moderator


def test_three_rounds_alternate_sides(snap, tmp_path):
    debate, debater, moderator = make(snap, tmp_path)
    result = debate.run()
    assert [(c[0], c[1]) for c in debater.calls] == [
        (Side.BULL, "opening"), (Side.BEAR, "opening"),
        (Side.BULL, "rebuttal"), (Side.BEAR, "rebuttal"),
        (Side.BULL, "closing"), (Side.BEAR, "closing"),
    ]
    # 각 발언자는 앞선 발언을 모두 본다
    assert [c[2] for c in debater.calls] == [0, 1, 2, 3, 4, 5]
    assert len(moderator.calls) == 1 and len(result.turns) == 6


def test_extra_round_then_forced_verdict(snap, tmp_path):
    debate, debater, moderator = make(snap, tmp_path, actions=["extra_round", "extra_round"])
    result = debate.run()
    extra = [c for c in debater.calls if c[1] == "extra"]
    assert len(extra) == 2 and extra[0][3] == "자사주 매입 규모는?"
    assert [c[2] for c in moderator.calls] == [True, False]
    assert len(result.evaluations) == 2


def test_stats_count_rejections(snap, tmp_path):
    debate, _, _ = make(snap, tmp_path, bad_first=True)
    result = debate.run()
    stats = verification_stats(result.turns)
    assert stats["bull"]["rejected_attempts"] == 1
    assert stats["bull"]["first_try_pass_rate"] == pytest.approx(0.67, abs=0.01)
    assert stats["bear"]["rejected_attempts"] == 0
    assert stats["bull"]["evidence_accuracy"] == 0.75


def test_verdict_sealed_until_user_submits(snap, tmp_path):
    debate, _, _ = make(snap, tmp_path)
    debate.run()
    types = [e["type"] for e in EventLog.read(debate.log.path)]
    assert "verdict_sealed" in types and "verdict_revealed" not in types
    debate.submit_user_verdict(Decision.BUY, "실적 개선")
    events = EventLog.read(debate.log.path)
    assert [e["type"] for e in events][-2:] == ["user_verdict", "verdict_revealed"]
    assert events[-1]["agrees_with_user"] is False
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

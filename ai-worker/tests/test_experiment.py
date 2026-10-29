import json
from types import SimpleNamespace

import pytest

from bullbear import experiment
from bullbear.config import load_settings
from bullbear.schemas import Side
from bullbear.snapshot import build_snapshot
from .fakes import FakeSource, NOW, ScriptedDebater, ScriptedModerator, statement


@pytest.mark.parametrize("first_side", [Side.BULL, Side.BEAR])
def test_pilot_saves_replay_usage_and_history(tmp_path, monkeypatch, first_side):
    class FakeLLM:
        def __init__(self, model):
            self.model = model
            self.client = SimpleNamespace(close=lambda: None)

        def usage_payload(self):
            return {"calls": []}

    class FakeDebater(ScriptedDebater):
        def __init__(self, *args, **kwargs):
            super().__init__(statement(("E1", "PX.CLOSE", 399)))

    monkeypatch.setattr(experiment, "LLM", FakeLLM)
    monkeypatch.setattr(experiment, "Debater", FakeDebater)
    monkeypatch.setattr(experiment, "Moderator", lambda *a, **kw: ScriptedModerator([]))
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)
    report = experiment.run_condition(snap, load_settings(), tmp_path, first_side)
    assert report["status"] == "completed"
    assert [row["previous_statements"] for row in report["history_lengths"]] == list(range(6))
    assert report["history_lengths"][0]["side"] == first_side.value
    assert len(report["transcript"]) == 6
    assert json.loads((tmp_path / f"{first_side.value}-first.json").read_text(encoding="utf-8")) == report
    assert (tmp_path / f"{first_side.value}-first.jsonl").exists()

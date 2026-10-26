"""LLM 없이 도는 토론자·중재자 (개발·연동 확인용). BULLBEAR_AGENTS=scripted

실제 스냅샷의 수치를 그대로 인용하므로 검증기를 통과한다. API 키·비용 없이 Spring ↔ 워커 전체 흐름
(스냅샷, 이벤트, 봉인, 채점용 시세)을 실제 데이터로 확인할 때 쓴다. 판정은 항상 보류.
"""

from __future__ import annotations

import time

from ..agents import Attempt
from ..llm import Usage
from ..schemas import Decision, ModeratorDecision, SideScore, Statement
from ..snapshot import Snapshot

_PICKS = {"bull": ["PX.RET_1Y", "PX.VS_MA120", "PX.CLOSE"], "bear": ["PX.VOL_20D", "PX.RET_1M", "PX.CLOSE"]}


class ScriptedDebater:
    def __init__(self, snap: Snapshot, delay: float = 1.0):
        self.snap = snap
        self.delay = delay

    def speak(self, side, round_kind, transcript, *, verify, question=None, on_event=None):
        time.sleep(self.delay)  # 화면에서 진행이 보이게
        fid = next((f for f in _PICKS[side.value] if f in self.snap.facts), "PX.CLOSE")
        fact = self.snap.facts[fid]
        st = Statement.model_validate({
            "claim": f"[연습용 발언] {side.label} 측 {round_kind}",
            "argument": f"{fact.label} 값은 {fact.value} [E1]이다. (LLM 없이 만든 발언)",
            "evidence": [{"ref": "E1", "source_id": fid, "value": fact.value, "interpretation": f"{fact.label} 인용"}],
        })
        return [Attempt(st, verify(st))]


class ScriptedModerator:
    def __init__(self, delay: float = 1.0):
        self.delay = delay

    def evaluate(self, transcript, stats, *, extra_allowed):
        time.sleep(self.delay)
        score = SideScore(relevance=3, materiality=3, rebuttal=3, risk_awareness=3, comment="연습용 평가")
        return ModeratorDecision(action="verdict", extra_question=None, bull=score, bear=score, decision=Decision.HOLD,
                                 confidence=0.5, reasoning="LLM 없이 만든 연습용 판정입니다.", decisive_evidence=["PX.CLOSE"])


def usage() -> list[tuple[str, Usage]]:
    return []  # LLM을 부르지 않았으므로 비용 0

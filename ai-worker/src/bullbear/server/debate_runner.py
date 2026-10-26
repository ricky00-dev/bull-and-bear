"""토론 한 건 실행: 스냅샷 고정 → 토론 엔진 실행 → 계약 이벤트로 내보내기.

토론 엔진(`bullbear.debate.Debate`)은 CLI와 같은 것을 쓴다. 여기서는 바깥과 잇는 일만 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ..config import Settings
from ..data import DataUnavailable
from ..data.universe import UNIVERSE
from ..debate import Debate, verification_stats
from ..events import EventLog
from ..llm import LLMError, Usage
from ..snapshot import Snapshot, build_snapshot
from . import wire
from .market import Market
from .runs import DebateRun

log = logging.getLogger("bullbear.server")


@dataclass
class Agents:
    debater: object
    moderator: object
    usage: Callable[[], list[tuple[str, Usage]]]  # 모델별 사용량 (토론이 끝난 뒤 읽는다)


class WireLog(EventLog):
    """내부 기록(JSONL)은 그대로 남기면서, 반려된 발언 시도는 계약 이벤트로도 내보낸다."""

    def __init__(self, path, run: DebateRun):
        super().__init__(path)
        self.run = run

    def append(self, type_: str, **payload) -> None:
        super().append(type_, **payload)
        if type_ == "statement_attempt":
            rejected = wire.statement_rejected(payload)
            if rejected is not None:
                self.run.emit("statement_rejected", rejected)


def run_debate(run: DebateRun, settings: Settings, *, snapshot: Callable[[str, str], Snapshot],
               agents: Callable[[Snapshot], Agents]) -> None:
    usage: Callable[[], list[tuple[str, Usage]]] = lambda: []
    try:
        snap = snapshot(run.ticker, UNIVERSE.get(run.ticker, run.ticker))
        snap.save(settings.snapshot_dir)
        run.emit("snapshot_created", wire.snapshot_created(snap))

        a = agents(snap)
        usage = a.usage

        def on_event(event: str, payload: dict) -> None:
            mapped = wire.from_engine(event, payload)
            if mapped is not None:
                run.emit(*mapped)

        debate = Debate(snap, a.debater, a.moderator, WireLog(settings.debate_dir / f"{run.debate_id}.jsonl", run),
                        debate_id=run.debate_id, max_extra_rounds=run.max_extra_rounds, on_event=on_event)
        result = debate.run()
        run.emit("debate_completed", wire.debate_completed(
            run.debate_id, result.verdict, verification_stats(result.turns), wire.usage(usage())))
        log.info("토론 완료 %s %s", run.debate_id, result.verdict.decision.value)
    except DataUnavailable as e:
        run.emit("debate_failed", wire.debate_failed("DATA_UNAVAILABLE", str(e), wire.usage(usage())))
    except LLMError as e:
        run.emit("debate_failed", wire.debate_failed("LLM_ERROR", str(e), wire.usage(usage())))
    except Exception as e:
        log.exception("토론 실패 %s", run.debate_id)
        run.emit("debate_failed", wire.debate_failed("INTERNAL", f"{type(e).__name__}: {e}", wire.usage(usage())))


# 실제 구성 -------------------------------------------------------------------

def make_market(settings: Settings) -> Market:
    from ..data.pykrx_dart import PykrxDartSource

    return Market(PykrxDartSource(settings.dart_api_key, settings.cache_dir))


def make_runner(settings: Settings) -> Callable[[DebateRun], None]:
    from ..agents import Debater, Moderator
    from ..data.naver_news import NaverNewsSource
    from ..data.pykrx_dart import PykrxDartSource
    from ..llm import LLM

    source = PykrxDartSource(settings.dart_api_key, settings.cache_dir)
    try:
        news = NaverNewsSource(settings.naver_client_id, settings.naver_client_secret)
    except DataUnavailable as e:
        log.warning("뉴스 없이 토론합니다: %s", e)
        news = None

    def agents(snap: Snapshot) -> Agents:
        if settings.agents == "scripted":
            from . import scripted

            return Agents(scripted.ScriptedDebater(snap), scripted.ScriptedModerator(), scripted.usage)
        # 토론자·중재자 LLM을 따로 둬서 모델별 사용량을 나눠 센다.
        # TODO(jangwonii): 토론자 Haiku 5.5로 바꿀 때 llm.py의 fallbacks 처리 (Haiku는 서버 측 폴백 미지원)
        debater_llm, moderator_llm = LLM(settings.model), LLM(settings.model)
        return Agents(
            Debater(debater_llm, snap, effort=settings.debater_effort),
            Moderator(moderator_llm, snap, effort=settings.moderator_effort),
            lambda: [(debater_llm.model, debater_llm.usage), (moderator_llm.model, moderator_llm.usage)],
        )

    def runner(run: DebateRun) -> None:
        run_debate(run, settings, snapshot=lambda t, n: build_snapshot(source, t, n, news=news), agents=agents)

    return runner

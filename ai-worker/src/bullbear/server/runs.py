"""토론 실행 관리: 동시 실행 상한, 대기열, 멱등 키, 이벤트 보관·구독.

토론 엔진은 동기 코드(Anthropic SDK, pykrx)라 스레드 풀에서 돌린다. 이벤트는 순번(seq)을 붙여
메모리와 파일(JSONL)에 함께 쌓고, SSE 구독자(asyncio)에게는 이벤트 루프로 안전하게 넘긴다.

- 끊겼다 다시 붙은 구독자는 Last-Event-ID 뒤부터 이어 받는다 (메모리에 없으면 파일에서).
- 같은 request_id로 다시 시작하면 같은 토론을 돌려준다 (Spring 재시도 대비).
- 워커가 재시작돼 끝나지 못한 토론은 실패(WORKER_RESTARTED)로 닫는다. Spring이 새로 요청하면 된다.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..snapshot import KST

TERMINAL = {"debate_completed", "debate_failed"}


@dataclass(frozen=True)
class WireEvent:
    seq: int
    type: str
    data: dict

    @property
    def terminal(self) -> bool:
        return self.type in TERMINAL


class Busy(Exception):
    """동시 토론·대기열이 다 찼다 (429)."""


@dataclass
class DebateRun:
    debate_id: str
    ticker: str
    request_id: str
    max_extra_rounds: int
    path: Path
    status: str = "queued"  # queued → running → completed | failed
    snapshot_id: str | None = None
    events: list[WireEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _subscribers: set = field(default_factory=set, repr=False)

    def emit(self, type_: str, data: dict) -> WireEvent:
        with self._lock:
            if self.events and self.events[-1].terminal:
                raise RuntimeError(f"이미 끝난 토론: {self.debate_id}")
            event = WireEvent(len(self.events) + 1, type_, data)
            self.events.append(event)
            with self.path.open("a") as f:
                f.write(json.dumps({"seq": event.seq, "type": type_, "data": data}, ensure_ascii=False) + "\n")
            if type_ == "snapshot_created":
                self.snapshot_id = data["snapshot_id"]
            if event.terminal:
                self.status = "completed" if type_ == "debate_completed" else "failed"
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        return event

    def subscribe(self, after: int, loop: asyncio.AbstractEventLoop) -> tuple[list[WireEvent], asyncio.Queue, Callable[[], None]]:
        """after 뒤 이벤트(밀린 것)와, 이후 새 이벤트를 받을 큐. 둘 사이에 빠지는 이벤트가 없게 잠근 채로 등록한다."""
        queue: asyncio.Queue = asyncio.Queue()
        entry = (loop, queue)
        with self._lock:
            backlog = [e for e in self.events if e.seq > after]
            self._subscribers.add(entry)

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.discard(entry)

        return backlog, queue, unsubscribe

    @property
    def finished(self) -> bool:
        return bool(self.events) and self.events[-1].terminal


class Registry:
    def __init__(self, data_dir: Path, runner: Callable[[DebateRun], None], *, max_concurrent: int, max_queued: int):
        self.wire_dir = data_dir / "wire"
        self.request_dir = data_dir / "requests"
        self.wire_dir.mkdir(parents=True, exist_ok=True)
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.max_queued = max_queued
        self.pool = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="debate")
        self.runs: dict[str, DebateRun] = {}
        self._lock = threading.RLock()  # start()가 잠근 채 get()을 부른다

    def start(self, ticker: str, request_id: str, max_extra_rounds: int) -> tuple[DebateRun, bool]:
        """@return (토론, 이미 있던 요청인지)"""
        with self._lock:
            known = self.request_dir / _safe(request_id)
            if known.exists():
                run = self.get(known.read_text().strip())
                if run is not None:
                    return run, True
            active = sum(1 for r in self.runs.values() if not r.finished)
            if active >= self.max_queued:
                raise Busy(f"진행·대기 중인 토론 {active}개")
            debate_id = f"{datetime.now(KST):%Y%m%d-%H%M%S}-{ticker}-{uuid.uuid4().hex[:6]}"
            run = DebateRun(debate_id, ticker, request_id, max_extra_rounds, self.wire_dir / f"{debate_id}.jsonl")
            run.path.touch()
            known.write_text(debate_id)
            self.runs[debate_id] = run
        self.pool.submit(self._run, run)
        return run, False

    def _run(self, run: DebateRun) -> None:
        run.status = "running"
        try:
            self.runner(run)
        except Exception as e:  # runner가 놓친 오류도 반드시 실패 이벤트로 닫는다
            if not run.finished:
                run.emit("debate_failed", {"error": {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}"}})
        finally:
            if not run.finished:
                run.emit("debate_failed", {"error": {"code": "INTERNAL", "message": "토론이 결과 없이 끝났습니다"}})

    def get(self, debate_id: str) -> DebateRun | None:
        """메모리에 없으면 파일에서 읽는다. 끝나지 못한 채 남은 기록은 실패로 닫는다."""
        run = self.runs.get(debate_id)
        if run is not None:
            return run
        path = self.wire_dir / f"{_safe(debate_id)}.jsonl"
        if not path.exists():
            return None
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        ticker = debate_id.split("-")[2] if debate_id.count("-") >= 2 else ""
        run = DebateRun(debate_id, ticker, "", 0, path,
                        events=[WireEvent(r["seq"], r["type"], r["data"]) for r in records])
        for e in run.events:
            if e.type == "snapshot_created":
                run.snapshot_id = e.data["snapshot_id"]
        if run.finished:
            run.status = "completed" if run.events[-1].type == "debate_completed" else "failed"
        else:
            run.emit("debate_failed", {"error": {"code": "WORKER_RESTARTED", "message": "워커가 재시작되어 토론이 중단됐습니다"}})
        with self._lock:
            return self.runs.setdefault(debate_id, run)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def _safe(name: str) -> str:
    """파일 이름으로 쓸 수 없는 문자를 막는다 (경로 조작 방지)."""
    if not name or any(c in name for c in "/\\.") or len(name) > 100:
        raise ValueError(f"잘못된 ID: {name!r}")
    return name

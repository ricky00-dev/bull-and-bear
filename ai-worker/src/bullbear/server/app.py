"""AI 워커 HTTP 서버 (FastAPI). 계약: docs/worker-api.md

  uv run uvicorn bullbear.server:app --port 8000

Spring만 호출한다 (내부망). 헤더 X-Worker-Token이 환경 변수 WORKER_TOKEN과 같아야 한다.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import Settings, load_settings
from ..data import DataUnavailable
from ..snapshot import Snapshot
from .market import Market, NotFound
from .runs import Busy, DebateRun, Registry

log = logging.getLogger("bullbear.server")
HEARTBEAT_SECONDS = 15


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers


class StartDebate(BaseModel):
    ticker: str = Field(pattern=r"^\d{6}$")
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    max_extra_rounds: int = Field(default=1, ge=0, le=2)


def create_app(settings: Settings | None = None, *, market: Market | None = None,
               runner: Callable[[DebateRun], None] | None = None) -> FastAPI:
    """market, runner를 넘기면 그걸 쓴다 (테스트용 가짜). 안 넘기면 실제 데이터 소스와 LLM으로 만든다."""
    settings = settings or load_settings()
    if market is None or runner is None:
        from .debate_runner import make_market, make_runner  # 실제 소스·LLM은 필요할 때만 불러온다

        market = market or make_market(settings)
        runner = runner or make_runner(settings)
    registry = Registry(settings.data_dir, runner, max_concurrent=settings.max_concurrent_debates,
                        max_queued=settings.max_queued_debates)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        registry.shutdown()

    app = FastAPI(title="bullbear ai-worker", version="0.4", lifespan=lifespan)
    app.state.registry = registry

    def auth(x_worker_token: str | None = Header(default=None)) -> None:
        if not x_worker_token or not hmac.compare_digest(x_worker_token, settings.worker_token):
            raise ApiError(401, "UNAUTHORIZED", "X-Worker-Token이 맞지 않습니다")

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, e: ApiError):
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status, headers=e.headers)

    @app.exception_handler(NotFound)
    async def _not_found(_req: Request, e: NotFound):
        return JSONResponse({"error": {"code": "NOT_FOUND", "message": str(e)}}, status_code=404)

    @app.exception_handler(DataUnavailable)
    async def _unavailable(_req: Request, e: DataUnavailable):
        return JSONResponse({"error": {"code": "DATA_UNAVAILABLE", "message": str(e)}}, status_code=503)

    @app.exception_handler(HTTPException)
    async def _http(_req: Request, e: HTTPException):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": str(e.detail)}}, status_code=e.status_code)

    def run_or_404(debate_id: str) -> DebateRun:
        try:
            run = registry.get(debate_id)
        except ValueError:
            run = None
        if run is None:
            raise ApiError(404, "NOT_FOUND", f"토론 없음: {debate_id}")
        return run

    @app.get("/health")
    def health() -> dict:
        return {"status": "UP"}

    # 1. 종목 (시세 조회가 블로킹이라 def로 둔다 → FastAPI가 스레드 풀에서 돌린다)

    @app.get("/stocks/search", dependencies=[Depends(auth)])
    def search(q: str, limit: int = Query(default=10, ge=1, le=50)) -> dict:
        return {"items": market.search(q, limit)}

    @app.get("/stocks/{ticker}", dependencies=[Depends(auth)])
    def stock(ticker: str) -> dict:
        return market.detail(ticker)

    @app.get("/stocks/{ticker}/eligibility", dependencies=[Depends(auth)])
    def eligibility(ticker: str) -> dict:
        return market.eligibility(ticker)

    # 2. 토론

    @app.post("/debates", status_code=202, dependencies=[Depends(auth)])
    def start_debate(body: StartDebate) -> dict:
        eligible = market.eligibility(body.ticker)
        if not eligible["eligible"]:
            raise ApiError(422, "NOT_ELIGIBLE", ", ".join(eligible["reasons"]))
        try:
            run, _known = registry.start(body.ticker, body.request_id, body.max_extra_rounds)
        except Busy as e:
            raise ApiError(429, "BUSY", f"토론이 몰려 있어요. 잠시 후 다시 시도해 주세요 ({e})", {"Retry-After": "30"})
        # 스냅샷은 비동기로 만든다 (DART·뉴스 조회가 수 초). 그래서 snapshot_id는 처음엔 null일 수 있고,
        # snapshot_created 이벤트로 확정된다 (계약 v0.5)
        return {"debate_id": run.debate_id, "snapshot_id": run.snapshot_id, "status": run.status, "reused": False}

    @app.get("/debates/{debate_id}/events", dependencies=[Depends(auth)])
    async def events(debate_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        run = run_or_404(debate_id)
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        loop = asyncio.get_running_loop()

        async def stream():
            backlog, queue, unsubscribe = run.subscribe(after, loop)
            last = after
            try:
                for e in backlog:
                    yield _sse(e.seq, e.type, e.data)
                    last = e.seq
                    if e.terminal:
                        return
                while True:
                    try:
                        e = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                    except TimeoutError:
                        yield ": ping\n\n"  # 프록시가 유휴 연결을 끊지 않게
                        continue
                    if e.seq <= last:
                        continue
                    yield _sse(e.seq, e.type, e.data)
                    last = e.seq
                    if e.terminal:
                        return
            finally:
                unsubscribe()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/debates/{debate_id}", dependencies=[Depends(auth)])
    def debate(debate_id: str) -> dict:
        run = run_or_404(debate_id)
        body: dict = {"debate_id": run.debate_id, "status": run.status, "snapshot_id": run.snapshot_id,
                      "statements": [e.data for e in run.events if e.type == "statement_accepted"]}
        last = run.events[-1] if run.events else None
        if last is not None and last.terminal:
            body.update({k: v for k, v in last.data.items() if k != "debate_id"})
        return body

    # 3. 스냅샷

    @app.get("/snapshots/{snapshot_id}", dependencies=[Depends(auth)])
    def snapshot(snapshot_id: str) -> dict:
        if not snapshot_id.replace("-", "").isalnum():
            raise ApiError(404, "NOT_FOUND", f"스냅샷 없음: {snapshot_id}")
        try:
            snap = Snapshot.load(settings.snapshot_dir, snapshot_id)
        except FileNotFoundError:
            raise ApiError(404, "NOT_FOUND", f"스냅샷 없음: {snapshot_id}")
        return snap.model_dump(mode="json")

    # 4. 채점용 시세

    @app.get("/prices/daily", dependencies=[Depends(auth)])
    def prices(ticker: str, from_: date = Query(alias="from"), to: date = Query()) -> dict:
        return {"items": market.daily_closes(ticker, from_, to)}

    @app.get("/indices/daily", dependencies=[Depends(auth)])
    def indices(code: str, from_: date = Query(alias="from"), to: date = Query()) -> dict:
        if code not in ("KOSPI", "KOSDAQ"):
            raise ApiError(404, "NOT_FOUND", f"지수 없음: {code}")
        return {"items": market.index_closes(code, from_, to)}

    return app


def _sse(seq: int, type_: str, data: dict) -> str:
    return f"id: {seq}\nevent: {type_}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

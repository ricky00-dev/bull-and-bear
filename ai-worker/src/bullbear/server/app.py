"""Internal HTTP/SSE API v0.6: debate and frozen-snapshot single mode."""
from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException

from ..config import load_settings
from ..data.base import DataUnavailable
from .errors import ApiError
from .market import Market
from .service import Service


class StartDebate(BaseModel):
    ticker: str = Field(pattern=r'^[0-9]{6}$')
    request_id: str = Field(min_length=1, max_length=128)
    max_extra_rounds: int = Field(default=1, ge=0, le=3)
    mode: Literal['debate', 'single'] = 'debate'
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode='after')
    def require_single_snapshot(self):
        if self.mode == 'single' and self.snapshot_id is None:
            raise ValueError('single mode requires snapshot_id')
        return self


def create_app(*, settings=None, market=None, runner_factory=None, token=None, max_running=None):
    settings = settings or load_settings()
    worker_token = token if token is not None else os.getenv('WORKER_TOKEN', 'dev-worker-token')
    if not worker_token:
        raise ValueError('WORKER_TOKEN must not be empty')
    capacity = max_running if max_running is not None else int(os.getenv('WORKER_MAX_CONCURRENT', '2'))
    if capacity < 1:
        raise ValueError('WORKER_MAX_CONCURRENT must be positive')

    @asynccontextmanager
    async def lifespan(app):
        active_market = market if market is not None else Market(settings)
        app.state.service = Service(settings, active_market, runner_factory=runner_factory, max_running=capacity)
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(app.state.service.close)
            finally:
                # Injected providers belong to the caller and may span lifespans.
                if market is None:
                    await asyncio.to_thread(active_market.close)

    app = FastAPI(title='bullbear ai-worker', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def service(request: Request):
        return request.app.state.service

    def auth(x_worker_token: str | None = Header(default=None)):
        if not x_worker_token or not hmac.compare_digest(x_worker_token.encode(), worker_token.encode()):
            raise ApiError(401, 'UNAUTHORIZED', 'X-Worker-Token이 맞지 않습니다')

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        error = {'code': exc.code, 'message': exc.message}
        if exc.reasons is not None:
            error['reasons'] = exc.reasons
        return JSONResponse({'error': error}, status_code=exc.status,
                            headers={'Retry-After': '5'} if exc.status == 429 else None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return await api_error(request, ApiError(400, 'INVALID_REQUEST', '요청 형식이나 범위를 확인하세요'))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return await api_error(request, ApiError(exc.status_code, 'NOT_FOUND' if exc.status_code == 404 else 'INVALID_REQUEST', '요청 경로 또는 메서드를 확인하세요'))

    @app.exception_handler(DataUnavailable)
    @app.exception_handler(httpx.HTTPError)
    async def data_error(request, exc):
        return await api_error(request, ApiError(503, 'DATA_UNAVAILABLE', '시장 데이터 공급자에 연결할 수 없습니다'))

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return await api_error(request, ApiError(500, 'INTERNAL_ERROR', '워커 내부 오류가 발생했습니다'))

    @app.get('/health')
    def health():
        return {'status': 'UP'}

    secured = [Depends(auth)]

    @app.get('/stocks/search', dependencies=secured)
    def search(q: str = Query(max_length=100), limit: int = Query(default=10, ge=1, le=20), svc=Depends(service)):
        return svc.market.search(q, limit)

    @app.get('/stocks/{ticker}', dependencies=secured)
    def stock(ticker: str, svc=Depends(service)):
        return svc.market.quote(ticker).detail()

    @app.get('/stocks/{ticker}/eligibility', dependencies=secured)
    def eligibility(ticker: str, svc=Depends(service)):
        quote = svc.market.quote(ticker)
        return {'ticker': ticker, 'eligible': not quote.reasons, 'reasons': quote.reasons}

    @app.post('/debates', status_code=202, dependencies=secured)
    def start(body: StartDebate, svc=Depends(service)):
        return svc.create(body)

    @app.get('/debates/{debate_id}/events', dependencies=secured)
    async def events(debate_id: str, request: Request, last_event_id: int = Header(default=0, ge=0, le=2**63-1, alias='Last-Event-ID'), svc=Depends(service)):
        svc.store.get(debate_id)

        async def stream():
            after = last_event_id
            idle = 0
            while True:
                if await request.is_disconnected():
                    return
                batch = svc.store.events(debate_id, after)
                for event in batch:
                    yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {event['data']}\n\n"
                    after = event['seq']
                # Terminal state and a final read avoid a completion/read race.
                if svc.store.get(debate_id)['status'] != 'running':
                    for event in svc.store.events(debate_id, after):
                        yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {event['data']}\n\n"
                    return
                idle = 0 if batch else idle + 1
                if idle >= 40:
                    yield ': heartbeat\n\n'
                    idle = 0
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/debates/{debate_id}', dependencies=secured)
    def debate(debate_id: str, svc=Depends(service)):
        return svc.detail(debate_id)

    @app.get('/snapshots/{snapshot_id}', dependencies=secured)
    def snapshot(snapshot_id: str, svc=Depends(service)):
        return svc.store.snapshot(snapshot_id)

    @app.get('/prices/daily', dependencies=secured)
    def prices(ticker: str, from_: date = Query(alias='from'), to: date = Query(), svc=Depends(service)):
        return svc.market.daily(ticker, from_, to)

    @app.get('/indices/daily', dependencies=secured)
    def indices(code: str, from_: date = Query(alias='from'), to: date = Query(), svc=Depends(service)):
        return svc.market.daily(code, from_, to, index=True)

    return app


app = create_app()

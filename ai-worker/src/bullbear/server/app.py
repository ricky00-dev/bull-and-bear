"""AI 워커 HTTP 서버 틀 (FastAPI). 계약: docs/worker-api.md

엔드포인트 모양, 인증, 오류 형식만 있다. 각 엔드포인트의 내용은 비어 있다 (501).
설계·구현은 jangwonii가 한다. 구조(파일 나누기, 동기/비동기, 실행 방식)도 자유롭게 바꿔도 된다.
지켜야 할 것은 요청·응답·이벤트 형식(계약)뿐이다. Spring은 그 형식만 본다.
"""

from __future__ import annotations

import hmac
import os
from datetime import date

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

WORKER_TOKEN = os.getenv("WORKER_TOKEN", "dev-worker-token")  # Spring의 bullbear.worker.token과 같아야 한다

app = FastAPI(title="bullbear ai-worker")


class ApiError(Exception):
    """계약의 오류 형식 {"error": {"code", "message"}}로 응답한다. 코드 목록은 계약 '공통' 절."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ApiError)
async def _api_error(_req: Request, e: ApiError):
    return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status)


def auth(x_worker_token: str | None = Header(default=None)) -> None:
    if not x_worker_token or not hmac.compare_digest(x_worker_token, WORKER_TOKEN):
        raise ApiError(401, "UNAUTHORIZED", "X-Worker-Token이 맞지 않습니다")


def todo(what: str):
    raise ApiError(501, "NOT_IMPLEMENTED", f"아직 구현하지 않음: {what}")


class StartDebate(BaseModel):
    ticker: str
    request_id: str  # Spring이 만드는 멱등 키. 같은 키면 같은 debate_id를 돌려준다
    max_extra_rounds: int = 1


@app.get("/health")
def health() -> dict:
    return {"status": "UP"}


# 1. 종목 ---------------------------------------------------------------------

@app.get("/stocks/search", dependencies=[Depends(auth)])
def search(q: str, limit: int = 10):
    """계약 1절. 종목명·코드·초성 검색, 토론 불가 종목도 이유와 함께."""
    todo("GET /stocks/search")


@app.get("/stocks/{ticker}", dependencies=[Depends(auth)])
def stock(ticker: str):
    """계약 1절. as_of는 지금 토론을 시작하면 스냅샷이 쓸 날짜와 같아야 한다 (Spring이 재사용 키로 씀)."""
    todo("GET /stocks/{ticker}")


@app.get("/stocks/{ticker}/eligibility", dependencies=[Depends(auth)])
def eligibility(ticker: str):
    todo("GET /stocks/{ticker}/eligibility")


# 2. 토론 ---------------------------------------------------------------------

@app.post("/debates", status_code=202, dependencies=[Depends(auth)])
def start_debate(body: StartDebate):
    """계약 2절. Spring은 15초 안에 응답을 기다린다."""
    todo("POST /debates")


@app.get("/debates/{debate_id}/events", dependencies=[Depends(auth)])
async def events(debate_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    """계약 2절. text/event-stream, 각 이벤트에 id(순번)·event·data(JSON 한 줄).
    Spring은 끊기면 Last-Event-ID(마지막으로 받은 순번, 처음엔 0)를 보내 그 뒤부터 받는다."""
    todo("GET /debates/{id}/events")


@app.get("/debates/{debate_id}", dependencies=[Depends(auth)])
def debate(debate_id: str):
    todo("GET /debates/{id}")


# 3. 스냅샷 -------------------------------------------------------------------

@app.get("/snapshots/{snapshot_id}", dependencies=[Depends(auth)])
def snapshot(snapshot_id: str):
    todo("GET /snapshots/{id}")


# 4. 채점용 시세 ---------------------------------------------------------------

@app.get("/prices/daily", dependencies=[Depends(auth)])
def prices(ticker: str, from_: date = Query(alias="from"), to: date = Query()):
    """계약 4절. 확정된 종가만, 날짜 오름차순."""
    todo("GET /prices/daily")


@app.get("/indices/daily", dependencies=[Depends(auth)])
def indices(code: str, from_: date = Query(alias="from"), to: date = Query()):
    todo("GET /indices/daily")

# AI 워커 API 계약 (v0.5, 초안)

Spring API 서버 ↔ Python AI 워커 사이의 약속. 양쪽은 이 문서만 보고 동시에 개발한다.
바꿀 때는 이 문서를 먼저 고치는 PR을 올리고 양쪽 담당자가 승인한다.

## 역할 나누기

| | Spring API 서버 (`api/`) | Python AI 워커 (`ai-worker/`) |
|---|---|---|
| 외부 노출 | 브라우저가 호출하는 유일한 서버 | 내부망 전용, Spring만 호출 |
| 상태 | 사용자, 판정, 원장, 채점, 리그. **DB가 기준 데이터** | 스냅샷, 토론 이벤트 파일. 다시 만들 수 있는 데이터 |
| 토론 | 요청 → 워커 이벤트 구독 → 저장 → 브라우저로 중계 | 스냅샷 고정, 토론 진행, 검증, 중재자 판정 |
| 판정 봉인 | **중재자 판정을 사용자 판정 제출 전까지 숨긴다** | 판정을 그대로 돌려준다 (숨기지 않음) |
| 채점 | 3일·7일 뒤 스케줄러가 종가·지수 조회 후 채점 | 종가·지수 조회 엔드포인트 제공 |

봉인은 Spring 책임이다. 워커 응답에 판정이 들어 있으므로 브라우저로 그대로 넘기면 안 된다.

## 공통

- Base URL: `http://ai-worker:8000` (로컬 `http://localhost:8000`)
- 인증: 헤더 `X-Worker-Token: <공유 비밀>` (환경변수 `WORKER_TOKEN`)
- 시간: ISO 8601, KST 오프셋 포함 (`2026-10-22T15:41:02+09:00`). 날짜는 `YYYY-MM-DD`
- 오류 형식:

```json
{ "error": { "code": "DATA_UNAVAILABLE", "message": "OpenDART 재무 보고서 없음: 005930" } }
```

| code | HTTP | 뜻 |
|---|---|---|
| `NOT_FOUND` | 404 | 종목, 토론, 스냅샷 없음 |
| `NOT_ELIGIBLE` | 422 | 토론 불가 종목 (`reasons` 포함) |
| `DATA_UNAVAILABLE` | 503 | 외부 데이터 공급자 실패 |
| `LLM_ERROR` | 502 | 모델 호출 실패, 거절 |
| `BUSY` | 429 | 동시 토론 한도 초과. `Retry-After` 헤더 |

## 1. 종목

### `GET /stocks/search?q=삼성&limit=10`

종목명 일부, 6자리 코드 앞부분, 초성(`ㅅㅅㅈㅈ`)으로 찾는다. 우선주·ETF처럼 토론할 수 없는 종목도
숨기지 않고 `eligible: false`와 사유를 붙여 돌려준다 (사용자가 왜 없는지 헷갈리지 않게).

```json
{ "items": [
  { "ticker": "005930", "name": "삼성전자", "market": "KOSPI", "featured": true,
    "close": 214500, "change_pct": -4.03, "eligible": true, "block_reason": null },
  { "ticker": "005935", "name": "삼성전자우", "market": "KOSPI", "featured": false,
    "close": 166600, "change_pct": -3.36, "eligible": false, "block_reason": "우선주는 토론하지 않아요" }
] }
```

`featured`: 추천 종목 여부. `close`, `change_pct`: 최근 거래일 종가와 전일 대비 등락률(%).

### `GET /stocks/{ticker}`

종목 확인 화면용.

```json
{ "ticker": "005930", "name": "삼성전자", "market": "KOSPI", "close": 214500, "change_pct": -4.03,
  "as_of": "2026-10-22", "eligible": true, "reasons": [], "sparkline": [249500, 254000, "... 60개, 오래된 순"] }
```

`as_of`는 지금 `POST /debates`를 하면 스냅샷이 쓸 날짜(최신 종가 날짜)와 **같아야 한다**. Spring은 `(ticker, as_of)`로
이미 있는 토론을 재사용하므로, 이 값이 틀리면 지난 데이터 토론을 보여 주거나 같은 토론을 두 번 돌린다.

### `GET /stocks/{ticker}/eligibility`

토론 가능 여부. 기준(시가총액, 거래대금, 종목 유형)은 워커가 판단하고 이유를 준다.

```json
{ "ticker": "123456", "eligible": false, "reasons": ["시가총액 1,000억 원 미만", "최근 20일 평균 거래대금 부족"] }
```

## 2. 토론

### `POST /debates`

```json
{ "ticker": "005930", "request_id": "c0a8...uuid", "max_extra_rounds": 1 }
```

- `request_id`: Spring이 만드는 멱등 키. 같은 키로 다시 보내면 같은 `debate_id`를 돌려준다 (중복 토론 방지).
- 같은 스냅샷의 토론이 이미 있으면 새로 돌리지 않고 재사용한다 (`reused: true`).

`202 Accepted`

```json
{ "debate_id": "20261022-154102-005930", "snapshot_id": "005930-20261022-2d76e3f5e8", "status": "running", "reused": false }
```

### `GET /debates/{debate_id}/events` (SSE)

`text/event-stream`. 각 이벤트에 `id`(순번)가 있어 끊기면 `Last-Event-ID`로 이어 받는다.
이미 끝난 토론을 구독하면 처음부터 전부 재생하고 닫는다.

| event | 언제 | data |
|---|---|---|
| `snapshot_created` | 시작 | `{snapshot_id, ticker, name, as_of, close, warnings[]}`. `close`는 채점 기준 가격 |
| `turn_started` | 발언 차례 시작 | `{side, round}` |
| `tool_call` | 에이전트가 데이터 조회 | `{side, tool}` (진행 표시용) |
| `statement_rejected` | 검증기 반려 | `{side, round, attempt, issues[]}` |
| `statement_accepted` | 발언 확정 | 아래 예시 |
| `extra_round_requested` | 중재자가 추가 질문 | `{question}` |
| `moderator_started` | 평가 시작 | `{}` |
| `debate_completed` | 끝 | 아래 예시. **판정 포함 → Spring이 봉인** |
| `debate_failed` | 실패 | `{error: {code, message}, usage?}` |

`side`: `bull` | `bear`. `round`: `opening` | `rebuttal` | `closing` | `extra`.

발언 본문은 검증을 통과한 뒤에만 보낸다 (`statement_accepted`). 검증 전 토큰은 흘리지 않는다.
화면의 타이핑 효과는 클라이언트에서 낸다.

`statement_accepted`:

```json
{
  "side": "bear",
  "round": "rebuttal",
  "attempts": 2,
  "verified": true,
  "statement": {
    "claim": "20일 변동성이 연율 70%대다. 반등을 기다리는 동안 손실 폭이 클 수 있다.",
    "argument": "최근 20일 변동성은 70.4% [E1]로 ...",
    "evidence": [
      { "ref": "E1", "source_id": "PX.VOL_20D", "value": 70.4, "interpretation": "변동성은 ..." }
    ]
  },
  "warnings": [ { "code": "unused_evidence", "message": "..." } ]
}
```

근거 칩에 원본 정보(라벨, 단위, 출처 링크)가 필요하면 `GET /snapshots/{snapshot_id}`의 `facts[source_id]`를 쓴다.

`debate_completed`:

```json
{
  "debate_id": "20261022-154102-005930",
  "verdict": {
    "decision": "HOLD",
    "confidence": 0.55,
    "reasoning": "7거래일 뒤 코스피 대비 비슷하게 움직일 것으로 예상해요 [E1]. 상승과 하락 요인이 상쇄될 것으로 봐요 [E2].",
    "decisive_evidence": ["PX.VS_MA120", "PX.VOLUME_RATIO"],
    "scores": {
      "bull": { "relevance": 4, "materiality": 3, "rebuttal": 4, "risk_awareness": 3, "comment": "..." },
      "bear": { "relevance": 4, "materiality": 4, "rebuttal": 3, "risk_awareness": 3, "comment": "..." }
    }
  },
  "stats": {
    "bull": { "statements": 3, "first_try_pass_rate": 1.0, "rejected_attempts": 0, "evidence_accuracy": 1.0 },
    "bear": { "statements": 3, "first_try_pass_rate": 0.67, "rejected_attempts": 1, "evidence_accuracy": 0.83 }
  },
  "usage": {
    "calls": [
      { "model": "claude-haiku-5-5", "input_tokens": 98000, "output_tokens": 21000,
        "cache_read_input_tokens": 61000, "cache_creation_input_tokens": 9000 },
      { "model": "claude-opus-5-5", "input_tokens": 20000, "output_tokens": 8000,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0 }
    ],
    "cost_usd": 0.2131
  }
}
```

`usage`는 이 토론에서 쓴 LLM 사용량을 **모델별로 합친 것**이다 (재시도·반려된 발언 포함).
`input_tokens`는 캐시를 뺀 입력 토큰 (API 응답 `usage`와 같은 뜻). `cost_usd`는 선택이다.
워커가 보내면 Spring은 그 값을 쓰고, 없으면 Spring 설정의 모델별 단가로 계산한다.
Spring은 이 값으로 하루 비용 상한을 건다. `debate_failed`에도 그때까지 쓴 `usage`를 넣어 주면 좋다.

`decision`: `BUY` | `HOLD` | `SELL`.

### `GET /debates/{debate_id}`

완료된 토론 전체 (확정 발언 목록 + `debate_completed`와 같은 필드). 진행 중이면 `status: "running"`.

## 3. 스냅샷

### `GET /snapshots/{snapshot_id}`

```json
{
  "snapshot_id": "005930-20261022-2d76e3f5e8",
  "ticker": "005930", "name": "삼성전자", "as_of": "2026-10-22",
  "facts": {
    "PX.VOL_20D": { "label": "20일 변동성(연율)", "value": 70.4, "unit": "%", "as_of": "2026-10-22", "source": "pykrx" },
    "NEWS.1a2b3c4d": { "label": "기사 제목", "value": null, "unit": "text", "url": "https://...", "published_at": "2026-10-22T09:30:00+09:00" }
  },
  "warnings": []
}
```

## 4. 채점용 시세

Spring 채점 스케줄러가 장 마감 뒤(16:10, 18:10, 20:10) 호출한다. 거래일 달력은 따로 두지 않고,
기준일 이후 이 응답에 실제로 있는 날을 세어 N거래일째 종가로 채점한다. 그래서 휴장일은 응답에 넣지 않는다.

### `GET /prices/daily?ticker=005930&from=2026-10-22&to=2026-11-05`

[from, to] 구간 일별 종가, 날짜 오름차순. 아직 오지 않은 날은 없다.

```json
{ "items": [ { "date": "2026-10-22", "close": 214500 }, { "date": "2026-10-23", "close": 216000 } ] }
```

### `GET /indices/daily?code=KOSPI&from=2026-10-22&to=2026-11-05`

같은 형식. `code`: `KOSPI` | `KOSDAQ`. `close`는 지수 값 (소수 둘째 자리).

## 채점 규칙 (Spring 구현, 팀 확정 필요)

- 기준 가격: 토론 스냅샷의 종가 (`snapshot_created.close`, 기준일 = `as_of`)
- N거래일째 = 기준일 다음 날부터 `/prices/daily`에 있는 N번째 날
- 초과수익 = 종목 수익률 − 코스피 수익률 (같은 기간, %p). 코스닥 종목도 지금은 코스피와 비교
- 적중: BUY는 초과수익 > +2%p, SELL은 < −2%p, HOLD는 ±2%p 이내 (경계 포함). 구간은 `bullbear.scoring.hold-band`
- 3일·7일 두 번 채점, 적중률은 7일 기준 (판정 질문이 "7거래일 뒤")
- 사용자 판정과 중재자 판정을 같은 규칙으로 채점

### 중재자 글의 번호 인용 (기존 필드 유지)

새 워커 출력의 `reasoning`, `scores.*.comment`에서 `[E1]`은 `verdict.decisive_evidence[0]`,
`[E2]`는 `[1]`에 대응한다. 토론자 발언 안의 E1과는 별도의 번호 범위다.
웹은 해당 배열의 source_id로 스냅샷 근거를 찾아 칩을 만들 수 있다. 배열은 인용 순서로 최대 3개이며
중복 없이 글에서 사용한 번호와 일치한다. 내부 ID·검증 통계는 글에 넣지 않는다.
기존 저장 판정·가짜 워커 출력에는 번호가 없을 수 있으므로 기존 텍스트 표시도 유지할 수 있다.

## 변경 이력

- v0.5 설명 보강 (2026-10-29): 사용자 요청에 따라 기존 decisive_evidence 배열 순서와 중재자 글의
  [E1] 번호 대응을 명시. JSON 필드 추가·삭제 없이 출력 표현을 정리하고 웹 칩 연결 방법을 설명함.

- v0.5 (2026-10-26): `POST /debates` 응답의 `snapshot_id`는 `null`이어도 된다 (스냅샷을 비동기로 만들 때).
  Spring은 첫 이벤트 `snapshot_created`로 확정한다. 형식 변경 없음.
- v0.4 (2026-10-23): `GET /stocks/{ticker}`의 `as_of`는 **지금 `POST /debates`를 하면 스냅샷이 쓸 날짜**와 같아야 한다.
  Spring이 이 날짜로 토론 재사용 여부를 정한다 (`docs/ARCHITECTURE.md` ADR-1). 형식 변경은 없음.
- v0.3 (2026-10-23): `usage`를 모델별 목록(`calls`)과 선택 필드 `cost_usd`로 변경. 토론자 Haiku + 중재자 Opus처럼
  모델을 섞어 쓸 때 비용을 정확히 계산하기 위함. Spring은 v0.2 형식(`{input_tokens, output_tokens, model}`)도 계속 받는다.
- v0.2 (2026-10-23): 채점용 시세를 날짜 하나 조회(`/prices/close`, `/indices/close`)에서 구간 조회(`/prices/daily`, `/indices/daily`)로 변경.
  거래일 달력 없이 실제 시세가 있는 날을 세기 위함.
- v0.1 (2026-10-23): 검색 결과에 시세·토론 가능 여부 추가, `GET /stocks/{ticker}` 추가, `snapshot_created`에 `close` 추가.
  Spring 쪽 가짜 워커(`api/.../FakeWorkerClient.java`)가 이 형식을 그대로 재생한다.

## 워커 담당 메모 (현재 상태)

**워커 설계·구현은 jangwonii 담당.** 지켜야 하는 건 이 문서의 형식뿐이고, 내부 구조는 자유다.

- HTTP 서버: 인증·종목 조회·비동기 토론·스냅샷·종목/지수 기간 시세 및 SSE 재생을 구현했다.
  SQLite로 이벤트·멱등 키를 보존하며 데이터 디렉터리당 단일 프로세스로 실행한다.
  `uv run uvicorn bullbear.server:app --port 8000`, Spring은 `worker` 프로필과 같은 `WORKER_TOKEN`을 사용한다.
- 토론 엔진은 7거래일 판정 기준, 수치·개념·논리·표현 검증과 재작성을 적용한다.
  HTTP/CLI는 Anthropic 경로이고, OpenAI는 `python -m bullbear.experiment` 비교 실험에서 사용한다.
- 주가·지수는 KRX 공식 OPEN API, 재무·공시는 OpenDART, 뉴스는 NAVER API HUB를 사용한다.
  최초 시세 캐시는 `bullbear snapshot`으로 미리 준비한다. 원시 종가의 기업행사 보정은 아직 없다.
- 종목 검색은 OpenDART 목록으로 확장하며, 토론 허용 대상은 현재 대형주 30종목이다.
  전체 ETF/우선주 마스터 및 시장 전체 시총·거래대금 필터는 아직 구현하지 않았다.

### Spring이 기대하는 것 (연동하면서 확인한 점)

- `POST /debates`는 15초 안에 응답해야 한다. 스냅샷·토론은 응답 뒤에 진행하는 게 안전하다.
- SSE: 이벤트마다 `id`(1부터 순번)·`event`·`data`(JSON 한 줄). `id`·`event`가 없는 줄(하트비트 주석 등)은 Spring이 무시한다.
  Spring은 끊기면 `Last-Event-ID: <마지막 순번>`으로 다시 붙는다 (처음엔 `0`). 끝난 토론은 처음부터 재생하고 닫는다.
- 토론은 반드시 `debate_completed` 또는 `debate_failed`로 끝나야 한다. 안 오면 Spring은 재시도 5번 뒤 실패 처리한다.
- `snapshot_created.close`가 채점 기준 가격이다. **장중 값이면 안 된다** (확정 종가). 같은 이유로 `GET /stocks/{ticker}`의 `as_of`,
  `/prices/daily`, `/indices/daily`도 확정 종가만.
- 토큰 사용량(`debate_completed.usage`)으로 Spring이 하루 비용 상한을 건다. 빠지면 추정치($0.3)로 센다.

### 웹 쪽 희망 사항 (제안, 계약 아님 — jangwonii 판단)

사용자는 주식을 배우러 온 입문자다. 웹은 본문 속 용어(PER, 이동평균, 투매 등)에 밑줄을 긋고 누르면 풀이를 띄우지만,
발언 자체가 쉬우면 더 좋다.

- 발언은 입문자 기준 말투로. 전문용어를 쓰면 짧게 풀어 쓰기 (예: "PER 8배, 즉 1년 이익의 8배 가격").
- 발언에 선택 필드 `statement.plain`("쉽게 말하면: …" 한 줄)이 있으면 웹이 발언 아래에 보여준다. 없으면 안 보인다.
  같은 호출 안에서 쓰므로 호출 수·지연은 그대로. 넣기로 하면 계약 버전을 올리고 변경 이력에 적는다.

# AI 워커 API 계약 (기본 v0.6 / LangGraph v1.1 구현 초안)

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
- `max_extra_rounds`: 기존 호출 호환용으로 기본 1, 범위 0~3을 받는다. 현재 v1.1 고정 3단계 흐름에서는 추가 라운드/조사를 실행하지 않는다.
- 같은 스냅샷의 토론이 이미 있으면 새로 돌리지 않고 재사용한다 (`reused: true`).
- `mode` (v0.6, 선택): `"debate"`(기본) | `"single"`. 아래 "단일 모드" 참고.
- `snapshot_id` (v0.6, 선택): 이 스냅샷으로 진행한다. 단일 모드에서는 **필수** (짝이 되는 토론과 같은 스냅샷).
  없는 스냅샷이면 `404 NOT_FOUND`.

#### 단일 모드 (`mode: "single"`, 실험 조건 B)

실험 "토론 vs 단일"(docs/experiment.md)의 조건 B. 매수·매도 토론 없이 **중재자와 같은 모델 하나가**
같은 스냅샷을 보고 바로 판정한다. 사용자에게는 보여 주지 않고 실험 집계에만 쓴다.

```json
{ "ticker": "005930", "request_id": "single-c0a8...", "mode": "single", "snapshot_id": "005930-20261111-2d76e3f5e8" }
```

- 모델: `BULLBEAR_MODERATOR_MODEL`과 같은 모델 (모델 차이를 섞지 않기 위해)
- 판정 질문·기준은 토론 중재자와 같다 (7거래일 뒤 코스피 대비 ±2%p)
- 응답(`202`)과 이벤트 스트림은 토론과 같은 형식. 이벤트는 `snapshot_created`(선택) → `moderator_started` →
  `debate_completed` | `debate_failed`. `turn_*`·`statement_*`는 없다
- `debate_completed.verdict`는 토론과 같은 필드에서 `scores`만 `null`. `stats`도 `null`. `usage`는 그대로 보낸다
- 재사용: 같은 `snapshot_id` + 같은 `mode`면 재사용 (`reused: true`). 토론과 단일은 서로 재사용하지 않는다

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

## 7. 문서 검색과 구조화 수치 조회 (v0.8 구현 초안, 공동 검토 대기)

자연어 의도 판별을 제거하고 호출자가 경로를 명시적으로 선택한다. 기존 v0.6 토론/단일 분석/SSE는
유지한다. Spring/브라우저 연동은 아래 경로로 구현했으며 공동 승인·배포는 아직 하지 않았다. 두 경로 모두 기존
`X-Worker-Token` 인증과 `BULLBEAR_RAG_ENABLED=true`가 필요하다. 저장된 snapshot만 사용하며
시장 수집·LLM·임베딩·runner·shadow를 시작하지 않는다.

문서 검색은 워커가 저장 snapshot에 고정한 generation으로 라우팅한다. 전역 generation 설정 변경은 기존 연결을
바꾸지 않는다. 연결 없는 과거 snapshot이나 누락/변경된 게시 receipt는 RETRIEVAL_UNAVAILABLE503이다.
Spring은 토론의 snapshot_id만 전달하고 브라우저가 generation을 지정하지 않는다. 이 내부 연결은 공개 응답 필드를
추가하지 않는다. Fact 조회는 generation과 무관하다. 이관·교체 절차는 [운영 안내](RAG-PUBLICATION-RUNBOOK.md)를 따른다.

### POST /rag/search — 일반 문서 검색

```json
{"snapshot_id":"저장된-id","ticker":"005930","question":"PER 뜻과 현재 값의 차이가 궁금해"}
```

필수 snapshot_id(1~256자), ticker(6자리), question(공백만 제외, 1~1000자).
선택 mode는 `documents`만 허용하며 생략 시 해당 경로가 지정한다. as_of/unit/metric 등 추가 필드는400이다.
질문의 의도·종목 이름·날짜를 정규식으로 추정하지 않는다. **검색 대상은 명시한 ticker/snapshot**이다.
질문에 다른 종목명이 있어도 대상을 자동 변경하지 않는다. 일반 텍스트를 검색하며 기존 종목·시점·검수
필터와 관련성/문단 제한은 유지한다.

200 응답의 공통 필드: snapshot_id, ticker, snapshot_as_of, context_id, mode, answerability, reasons.
문서 경로에는 `documents` 배열과 `answer_scope="retrieved_documents_not_verified_numeric_answer"`를 추가한다.
문서는 chunk_id/text/horizons/applicability/limitations를 담는다. answerability는 documents_found 또는
no_documents다. snapshot ticker 불일치 등 메타데이터 검증 실패는 insufficient_evidence와 빈 배열이다.
`facts` 필드는 없으며, 문단이 검색되었다고 질문의 수치 답변이 검증된 것은 아니다.

### POST /rag/facts — 구조화 수치 조회

```json
{"snapshot_id":"저장된-id","ticker":"005930","metric":"per_ttm","as_of":"2026-11-02","unit":"x"}
```

필수 snapshot_id, ticker, metric. 선택 as_of(날짜), unit(`KRW`, `KRW/share`, `%`, `x`, `shares`, `count`),
mode(`facts`만 허용). question/period 등 추가 필드는400이다. 자연어를 받거나 해석하지 않는다.

| metric | Fact ID | 단위 |
|---|---|---|
| close | PX.CLOSE | KRW/share |
| per_ttm | VAL.PER_TTM | x |
| pbr | VAL.PBR | x |
| roe_ttm | VAL.ROE_TTM | % |
| operating_margin_ttm | VAL.OP_MARGIN_TTM | % |
| market_cap | VAL.MKTCAP | KRW |

날짜 생략 시 snapshot.as_of, 단위 생략 시 지표의 정해진 단위를 사용한다. 이름에 TTM을 명시하고
분기 수치를 TTM으로 대체하지 않는다. 미지원 지표/기간을 추정하지 않고 요청 오류400을 반환한다.
정상 요청이라도 종목·날짜·단위 불일치, 미확정/미래 날짜, None/NaN, 출처/ID 오류,
누락·순환·미래·단위 오류 입력 근거가 있으면 insufficient_evidence와 이유를 반환한다.

공통 응답에 `facts` 배열을 추가한다. 성공은 supported_fact이며 배열 항목은 fact_id/ticker/value/unit/as_of/
source/inputs/verified_lineage다. 근거 부족은 빈 배열이다. documents 배열은 없다.
숫자는 snapshot 원값이며 새 계산·단위 변환·시장 조회를 하지 않는다. verified_lineage는 입력 존재·형식·시점
검사 목록이며 공급자 원본 대사나 수식 재계산은 아니다. 수치 조회에는 검색 generation이 필요 없다.

### 오류와 이전 초안 이전

인증 실패401, 형식·잘못된 경로의 필드400, snapshot 없음404, RAG_DISABLED503,
RETRIEVAL_UNAVAILABLE503(문서 검색 실패/timeout), 저장 실패500. 근거 부족/검색결과 없음은200이다.
각 요청의 명시 mode/제약/검색결과 또는 Fact 검증 결과는 context/감사에 보존하며 동일 조회를 재생할 수 있다.
중재자 판정·토론 이벤트·모델 사용량은 반환하지 않는다.

이전 v0.7 혼합 `POST /rag/query`는 인증 후 **410 RAG_QUERY_RETIRED**를 반환한다. 자동 분류나
리다이렉트하지 않는다. 문서 찾기는 /rag/search로 옮기고, 수치 조회는 화면/호출자가 metric/as_of/unit을
명시해 /rag/facts로 보내야 한다. 기존 질문을 서버가 자동으로 지표로 바꾸지 않는다.

### Spring·웹 연동 (v0.8)

토론 화면의 **자료 찾아보기**에서 문서 검색/수치 조회를 직접 고른다. 선택이나 입력 변경만으로 조회하지
않으며 제출할 때 한 경로만 호출한다. 대상은 해당 토론 종목과 저장 자료다. 웹에는 워커 토큰을 전달하지 않는다.

| Spring 경로 (Bearer 인증) | 웹 요청 JSON | 워커 경로 |
|---|---|---|
| POST /api/debates/{id}/rag/search | `{"question":"PER 뜻"}` | /rag/search |
| POST /api/debates/{id}/rag/facts | `{"metric":"per_ttm","asOf":"2026-10-30","unit":"x"}` | /rag/facts |

Spring이 토론 레코드에서 snapshot_id/ticker를 결정한다. 클라이언트가 이를 덮어쓰거나 두 요청 필드를 섞으면400.
asOf/unit은 선택이며 생략 시 워커 기본값을 따른다. 날짜는 워커에 as_of로 변환한다. 웹은 지표별 고정 단위를
함께 전송하고 자동 단위 변환은 하지 않는다. 응답은 위 워커 snake_case 형식의 명시적 DTO만 전달한다.
문서 응답에는 facts를, 수치 응답에는 documents를 포함하지 않으며 중재자 판정 등 미정의 필드는 전달하지 않는다.

스냅샷 미준비409 SNAPSHOT_NOT_READY, 인증401, 요청 형식400 INVALID_REQUEST, 없는 토론/스냅샷404,
워커 비활성·통신/검색/저장 실패503 WORKER_UNAVAILABLE. 정상 근거 부족은200으로 구분한다.
fake 모드에서는 결과를 만들어내지 않고503을 반환한다. 조회는 토론 생성·시장 수집·모델 호출로 우회하지 않는다.
웹은 날짜·출처·문서 한계와 근거 부족을 표시하며, 조회 방식/조건 변경 시 이전 결과를 지운다.

## v1.1: 고정 공방과 역할 유지 (구현 초안)

- HTTP·CLI는 양측 opening → 양측 rebuttal → 양측 closing → 중재자 순서로 총 6개 발언을 생성한다.
  각 단계는 병렬이며 양측의 이전 단계 완료 후 다음 단계가 시작된다. 새 근거를 강제하지 않는다.
- 토론자의 analysis.outlook은 bull=BUY, bear=SELL이며 claim/argument도 배정 입장을 유지한다.
  가정·한계와 closing.stance_change로 논거 약화·수정을 설명할 수 있다. 배정 역할은 예측 투표가 아니다.
  개별 해석의 expected_outcome은 반대 근거를 인정할 수 있도록 BUY/HOLD/SELL을 유지한다.
- 중재자는 공통 사실·해석 차이·약화/유지된 논점·불확실성을 정리한다. 독립 전망은 BUY/HOLD/SELL,
  판단 유보는 ABSTAIN이다. 추가 라운드/조사 요청을 생성하지 않는다.
- turn_started에 debate_flow=fixed_three_rounds를 추가한다. 이 기록은 6개 발언 완료가
  generation.base_rounds_complete/debate_complete 기준이다. 기존 engine=langgraph만 있는 기록은
  2개 opening 완료 기준으로, engine이 없는 과거 기록은 6개 기준으로 계속 읽는다.
- 중재자 검증 재시도 소진은 error.code=LLM_ERROR, error.reason=moderator_validation_failed다.
  세부 검증 코드는 비공개 JSONL moderator_rejected에만 보존한다. SSE에는 탈락 이유/전망을 보내지 않는다.
- 이미 완료된 토론과 중재자 실패는 generation에서 구분한다. Spring 사용자 판정 허용/저장 정책은 변경하지 않는다.
- 기존 필드 삭제 없음. 발언 ID·해석 ID·최종 verdict 봉인 형식은 유지한다. 공동 계약 리뷰는 필요하다.

## v1.0: LangGraph HTTP·CLI 연결 (이전 동작 기록)

아래는 v1.0 동작이다. 신규 생성은 위 v1.1 규칙을 적용한다.


기존 순차 `Debater/Moderator/Debate` 실행 코드는 삭제했다. HTTP `mode=debate`와 CLI의
`bullbear debate`는 `LiveRunner → GraphRuntime → build_debate_graph`를 사용한다.
Spring·웹 코드는 변경하지 않았으며 공동 담당자 리뷰·실제 모델·운영 통합 검증은 미완료다.

- 최초 양측 분석은 독립 LLM 클라이언트로 병렬 실행한다. 양쪽 완료 후 중재한다.
- CHALLENGE_BULL/BEAR는 해당 쪽만 다시 실행하며 REQUEST_RESEARCH는 고정 스냅샷만 조회한다.
  추가 실행은 요청 상한 이내에서만 이루어지고, 상한 뒤 추가 요청은 실행하지 않는다.
- 최초 발언의 기존 round 값은 opening, 재검토는 rebuttal이다. **고정 6발언·closing 발언을 생성하지 않는다.**
  기존 화면의 라운드 구역 일부가 비어 있을 수 있다. 모든 초기 발언이 완료된 후에만 중재하며,
  병렬 발언의 도착 순서에 의미를 부여하지 않는다.
- ACCEPT와 검증된 forecast가 있어야 기존 `debate_completed.verdict`를 반환한다.
  decision/confidence/reasoning/decisive_evidence/scores 및 analysis의 형식은 유지한다.
- ABSTAIN은 HOLD 예측이 아니다. `debate_failed.error.reason=graph_abstained`로 종료한다.
  상한 도달은 `graph_round_limit`, 모델·검증 오류는 `generation_failed`다. 기존 error.code는 LLM_ERROR다.
  확정 발언은 조회·재생할 수 있지만 Spring의 사용자 판정 허용 정책은 이 변경에 포함하지 않는다.
- 중간 중재자의 forecast·reason 원문은 공개 이벤트로 내보내지 않는다. extra_round_requested의 question은
  자료 재확인/주장 재검토 요청이라는 고정 안내이며, 최종 verdict는 기존처럼 Spring이 봉인한다.
- 새 생성의 진행 이벤트와 완료 payload에는 `engine=langgraph`를 추가한다. terminal payload의
  graph_status는 accepted/abstained/round_limit이다(일반 생성 오류에서는 생략).
- generation.base_rounds_complete는 engine=langgraph일 때 최초 양측 opening 완료를 뜻한다.
  과거 이벤트는 종전 6발언 기준으로 읽는다. moderator_status에는 abstained/round_limit이 추가된다.
- 발언 ID는 `{debate_id}:{bull|bear}:t{해당 쪽의 1부터 발언순번}`, 해석 ID는 여기에 `:{ref}`를 붙인다.
  병렬 완료 순서·검증 재시도와 무관하며, 소비자는 ID를 분해하지 않고 불투명 식별자로 사용한다.
- 단일 분석(`mode=single`), RAG·시세 조회, 기존 이벤트 재생, 비용 장부는 유지한다.
  새 엔진과 과거 순차 엔진의 실험 결과를 같은 정책의 결과로 합치지 않는다.

## v0.9: 구조화된 토론 해석 (v1.0에서도 유지하는 필드)

현재 적용 경로는 HTTP·CLI의 GraphRuntime이다. 직접 build_debate_graph를 호출하고 analyze 콜백을
주입하지 않는 라이브러리 사용은 기존 기본 Statement 검증만 수행한다. 단일 분석은 기존 생성 스키마를 유지한다.

### 발언과 해석

`statement_accepted.statement`의 기존 `claim`, `argument`, `evidence`와 evidence의
`ref`, `source_id`, `value`, `interpretation`은 유지한다. 다음 필드만 추가한다.

| 필드 | 의미 |
|---|---|
| `statement_id` | 확정 발언의 불투명 식별자. v1.0의 역할별 ID 형식 참고. 재시도 횟수와 무관 |
| `evidence[].interpretation_id` | `{statement_id}:{ref}`. 같은 source_id라도 서로 다른 발언의 해석은 다른 ID |
| `evidence[].observation` | 고정 snapshot의 해당 Fact 전체 사본. id/label/value/unit/as_of/source/inputs/note/url/published_at/category. LLM 작성 아님 |
| `analysis.outlook` | 현재 발언자의 BUY/HOLD/SELL 상대수익 전망. 배정된 side와 달라도 허용 |
| `analysis.interpretations[]` | 각 evidence.ref와 정확히 1:1. `evidence_ref`, `expected_outcome`(BUY/HOLD/SELL), `assumptions`, `limitations` |
| `analysis.rebuttal` | 반박 시 필수 객체. `target_statement_id`, `target_quote`, `acknowledged`, `reason`, `unresolved` |
| `analysis.closing` | 최종 정리 단계에 생성하며 opening/rebuttal에서는 null. 기존 객체는 `retained`, `conceded`, `outlook_reason`, `uncertainties`, `change_conditions`, `stance_change` |

가정/한계/미해결 쟁점/유지/인정/불확실성/변경 조건은 문자열 배열이다. 반박 대상·인정 내용·이유 및
최종 전망 이유는 문자열이다. 반박 대상은 실제 이전 **상대편** 발언이어야 하며 quote는 그 claim 또는
argument의 6자 이상 연속 원문이다. 판단상 중요한 논점을 고르는지는 의미 검토 대상으로 남는다.
첫 주장에서는 rebuttal=null, 최종 변론 이외에서는 closing=null이다. 최종 변론·기존 추가 질문에서
특정 반론을 기록할 경우 rebuttal도 사용할 수 있다. 인정할 부분이 없으면 그 이유를 명시하며 가짜 합의를 만들지 않는다.

예: 매수 첫 발언의 `d1:bull:t1:E1`과 매도 첫 발언의 `d1:bear:t1:E1`은 source_id가 둘 다 `PX.CLOSE`여도
별개의 해석이다. 해석 문장은 기존 `evidence[].interpretation`에서, 가정·한계는 같은 ref의 analysis에서 읽는다.
관찰 사본은 해당 시점의 **자료 내용**이지 뉴스 속 전망의 사실성이나 인과관계를 보증하지 않는다.
발언자의 side와 round는 기존 statement_accepted 이벤트 바깥 필드에서 읽는다.

### 중재자

기존 `verdict.decision/confidence/reasoning/decisive_evidence/scores`는 유지한다.
추가 `verdict.analysis`에는 문자열 배열 `common_ground`, `core_issues`, `disagreements`,
`unverified`, `outlook_basis`, `outlook_limits`와 실제 확정 해석 ID 배열 `key_interpretation_ids`가 들어간다.
outlook_basis/limits는 기존 decision의 근거·한계이며 새로운 별도 예측이 아니다.
AI 간 동의는 독립된 검증이나 인과 증명이 아니다. confidence는 기존 비보정 자기평가이며 정밀 확률을 추가하지 않는다.
이 정보는 terminal verdict 안에만 내보내고 moderator_started에는 넣지 않는다. 기존 Spring 판정 봉인을 유지한다.

### 생성 상태와 오류

`GET /debates/{id}` 및 생성의 terminal 이벤트에 `generation`을 추가한다.

```json
{
  "status": "failed",
  "generation": {
    "stage": "moderator",
    "base_rounds_complete": true,
    "debate_complete": true,
    "moderator_status": "failed"
  },
  "error": {"code": "LLM_ERROR", "message": "AI 토론을 완료하지 못했습니다",
            "stage": "moderator", "reason": "generation_failed"}
}
```

- 기존 status는 running/completed/failed 그대로다. 위 예에서도 저장된 statements는 삭제하지 않는다.
- stage: preparation/statements/moderator/completed. 실패·중단 시 마지막 진행 단계다.
- base_rounds_complete: fixed_three_rounds는 양측 opening/rebuttal/closing 6개 완료 여부. 이전 LangGraph는 양측 opening 완료 여부. engine 표시가 없는 과거 기록은 6개 완료 여부.
- debate_complete: 기본 분석이 완료되고 요청된 추가 조사·재검토가 진행 중이지 않은지. single 모드는 null이다.
- moderator_status: not_started/running/waiting/completed/failed/interrupted.
  v1.0의 abstained/round_limit도 허용한다.
  waiting은 중재자가 추가 조사·재검토를 요청하고 다음 판정을 기다리는 상태다.
- `error.reason=generation_failed`는 생성 실패, `worker_restart`는 프로세스 재시작으로 미완료 작업을 종결한 경우다.
  provider 원문 오류나 키는 공개하지 않는다. 시작 전 작업 제출 실패는 기존 INTERNAL_ERROR를 유지한다.
- 상태는 영속 이벤트에서 계산하며 기존 데이터도 조회 가능하다. 예전 실패 이벤트에 중단 사유가 없으면
  재시작 여부를 소급 추정하지 않는다. 사용자 판정 가능 여부·저장 정책은 결정하지 않는다.

### 호환·검증 범위

새 생성에는 analysis를 요구하지만 과거 Statement/ModeratorDecision 모델 파싱은 누락/null을 허용한다.
과거 기록을 다시 생성하거나 추정 가정·ID로 채우지 않는다. DB 마이그레이션·요청 필드 변경은 없다.
Spring `DebateRelay`는 이벤트 원문과 verdict JSON을 저장하고 알려진 필드만 읽으므로 추가 필드를 수용한다.
`ClientEvent`는 debate_completed 내용을 기존대로 숨긴다. 웹의 기존 필드 접근도 유지되지만 새 필드 표시·선택 저장은 구현하지 않았다.

Fact ID/값, ref 1:1 연결, 상대 발언 ID/인용, 중재자 해석 ID, 필수 구조를 검사한다.
가정·한계·반론 문장도 기존 의미 검토 대상에 포함한다. 의미 검토 역시 모델이므로 사실성·인과 타당성을 완전히 보장하지 못한다.
새 근거 강제는 프롬프트·사전 조건·검증에서 제거했고 기존 값 검증 오차 허용 정책은 유지한다.
유료 실제 모델의 출력 품질·지연·비용과 소비자의 새 필드 활용은 후속 검증 대상이다.

## 변경 이력

- v1.1 구현 초안 (2026-11-05): 사용자 요청으로 고정 3단계 양측 공방·BUY/SELL 역할 유지 적용. max_extra_rounds 수신 호환 유지, 운영 추가 실행 중단. 완료 기준 식별 및 중재자 검증 실패 reason 추가. 프론트·Spring 코드 변경 없음.
- v1.0 구현 초안 (2026-11-05): 사용자 승인으로 기존 순차 토론 엔진과 전용 실험 실행기를 삭제하고 LangGraph를 HTTP·CLI에 연결. 기존 이벤트 종류·판정 필드는 유지하되 고정 라운드 수와 max_extra_rounds 의미를 변경. 역할별 식별자·중재 종료 상태 추가. Spring/web 수정 없음. 공동 리뷰·실모델·배포 검증은 미완료.

- v0.9 구현 초안 (2026-11-05): 사용자 요청으로 기존 토론 생성 경로에 해석 식별자·관측 사본·구조화된 해석/반박/최종 변론/중재 정보를 추가. 생성 진행 상태·실패 단계·재시작 중단 사유 추가. 기존 요청, 필드, 이벤트 종류, 종결 status, 점수 의미 유지. Spring의 원문 JSON 저장 및 선택 필드 읽기와 호환되는 추가 필드 방식이며 Spring/web 수정 없음. 공동 담당자 리뷰·운영 배포·실제 모델 연동 검증은 미완료. 아래 확장 명세 참고.

- v0.8 내부 라우팅 보강 (2026-11-02): 공개 요청/응답 형식 유지. 최초 저장 snapshot별 generation/게시 receipt 고정,
  과거 조회 자동 라우팅, 명시적 legacy context 이관과 무연결503 처리. 미래 색인/reconstructed-v1 우회 없음.

- v0.8 단위 정정 (2026-11-02): 실제 저장 snapshot 연동에서 종가 단위 기대값 오류 확인. close의 단위를 원본 생성기와 같은 KRW/share로 정정하고 종가에 의존하는 PER/시총 계보도 정상 검증. KRW로 자동 변환하거나 입력 검증을 완화하지 않음.

- v0.8 연동 초안 (2026-11-02): 사용자 요청으로 Spring의 토론별 문서/수치 조회 API와 웹의 명시적 선택 패널 구현. 워커 형식 변경 없음. 저장 스냅샷 연결·인증·응답 허용 필드 제한 및 오류/근거 부족 구분. 공동 승인·운영 배포 미완료.

- v0.8 구현 초안 (2026-11-02): 사용자 요청으로 정규식 의도 필수 관문 제거, `/rag/search`와 `/rag/facts` 분리. TTM 지표 명시·Fact 검증 유지. v0.7 `/rag/query`는410으로 폐기 안내, 기존 v0.6 유지. 공동 검토·운영 연동 미완료.

- v0.7 구현 초안 (2026-11-02): 사용자 요청으로 모델 없는 `POST /rag/query` 추가. 저장 snapshot의 질문 의도·종목/시점/단위별 Fact 연결과 근거 부족 처리. 기존 v0.6 호환, 공동 검토·Spring 연동·운영 배포는 미완료.

- v0.6 (2026-10-31): `POST /debates`에 선택 필드 `mode`(`debate`|`single`)·`snapshot_id` 추가.
  단일 모드는 실험 조건 B (정식 운용 11/11부터 Spring 전향 운용이 토론마다 한 번 요청). 기존 요청은 그대로 동작.

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
  HTTP/CLI는 Anthropic 기반 LangGraph 경로다. 과거 OpenAI 비교 실행기는 삭제했다.
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

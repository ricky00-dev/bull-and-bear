# AI 워커 API 계약 (v0.13, 초안)

Spring API 서버 ↔ Python AI 워커 사이의 약속. 양쪽은 이 문서만 보고 동시에 개발한다.
바꿀 때는 이 문서를 먼저 고치는 PR을 올리고 양쪽 담당자가 승인한다.

## 역할 나누기

| | Spring API 서버 (`api/`) | Python AI 워커 (`ai-worker/`) |
|---|---|---|
| 외부 노출 | 브라우저가 호출하는 유일한 서버 | 내부망 전용, Spring만 호출 |
| 상태 | 사용자, 판정, 원장, 채점, 리그. **DB가 기준 데이터** | 스냅샷, 토론 이벤트 파일. 다시 만들 수 있는 데이터 |
| 토론 | 요청 → 워커 이벤트 구독 → 저장 → 브라우저로 중계 | 스냅샷 고정, 토론 진행, 중재자 판정 |
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

**백테스트 (v0.10, 선택 쿼리)**: `GET /stocks/{ticker}?as_of=2026-09-01`이면 그날(휴장일이면 그 전 마지막 거래일)
기준으로 답한다. 응답 `as_of`는 실제로 쓸 거래일이고 **요청한 날짜보다 뒤면 안 된다**. Spring은 응답 `as_of`가
요청보다 뒤면 워커가 기준일을 지원하지 않는 것으로 보고 백테스트 전체를 멈춘다. `eligible`도 그날 기준
(상장 여부·코스피 여부). `sparkline`은 비워도 된다.

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
- `mode` (v0.6, 선택): `"debate"`(기본) | `"single"`. 아래 "단일 모드" 참고.
- `snapshot_id` (v0.6, 선택): 이 스냅샷으로 진행한다. 단일 모드에서는 **필수** (짝이 되는 토론과 같은 스냅샷).
  없는 스냅샷이면 `404 NOT_FOUND`.
- `as_of` (v0.10, 선택, 백테스트): `"2026-09-01"`. Spring은 `GET /stocks/{ticker}?as_of=`가 돌려준 거래일을 그대로 보낸다.
  스냅샷은 **이 날짜 종가까지의 데이터만** 쓴다 (시세·재무·공시 모두 그날 이후 공개분 제외). `snapshot_created.as_of`는
  이 날짜, `close`는 그날 확정 종가. 없으면 지금처럼 최신 종가 기준. 멱등·재사용은 `(ticker, as_of)` 스냅샷 기준으로 같다.

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
| `statement_rejected` | 응답 형식 처리 실패 | `{side, round, attempt, issues[]}` |
| `statement_accepted` | 발언 확정 | 아래 예시 |
| `extra_round_requested` | 중재자가 추가 질문 | `{question}` |
| `moderator_started` | 평가 시작 | `{}` |
| `debate_completed` | 끝 | 아래 예시. **판정 포함 → Spring이 봉인** |
| `debate_failed` | 실패 | `{error: {code, message}, usage?}` |

`side`: `bull` | `bear`. `round`: `opening` | `rebuttal` | `closing` | `extra`.

발언 본문은 응답 형식을 처리한 뒤 보낸다 (`statement_accepted`). 원시 토큰은 흘리지 않는다. v0.12부터 공개 전 리뷰어는 없다.
v0.11 토론은 코드 내용 검증기를 실행하지 않으므로 `verified=false`, `verification_scope=not_checked`를 반환한다.
`verified=false`는 코드 검증 미실시를 뜻하며 발언 공개 실패를 뜻하지 않는다. 이전 기록의 `verified=true`도 읽을 수 있다.
화면의 타이핑 효과는 클라이언트에서 낸다.

`statement_accepted`:

```json
{
  "side": "bear",
  "round": "rebuttal",
  "attempts": 2,
  "verified": false,
  "verification_scope": "not_checked",
  "statement": {
    "claim": "20일 변동성이 연율 70%대다. 반등을 기다리는 동안 손실 폭이 클 수 있다.",
    "argument": "최근 20일 변동성은 70.4% [E1]로 ...",
    "evidence": [
      { "ref": "E1", "source_id": "PX.VOL_20D", "value": 70.4, "interpretation": "변동성은 ..." }
    ]
  },
  "warnings": []
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
    "bull": { "statements": 3, "first_try_pass_rate": null, "rejected_attempts": 0, "evidence_accuracy": null },
    "bear": { "statements": 3, "first_try_pass_rate": null, "rejected_attempts": 0, "evidence_accuracy": null }
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

검증 미실시 시 `stats.first_try_pass_rate`와 `stats.evidence_accuracy`는 `null`이다. `rejected_attempts`는 코드 내용 검증 반려 수이므로 0이다.
필수 응답 형식의 복구 횟수는 발언별 `attempts`와 비공개 이벤트에 남는다.

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

- v0.13 구현 초안 (2026-11-12): 사용자 요청으로 최초 LLM 판정이 HOLD일 때만 단순 평균 점수 규칙을 적용한다.
  매수 측 4항목 평균 − 매도 측 4항목 평균이 **±0.2 이내(경계 포함)는 HOLD**,
  +0.2 초과는 BUY, −0.2 미만은 SELL이다. HOLD에서 BUY/SELL로 바뀔 때만 새 중재 요청의 task에 판정을 지정해 해설을 재생성하며 점수·평가 문구는 보존한다.
  최초 BUY/SELL은 계산·재생성 없이 유지하며 평균·차이·mean_decision은 null로 저장한다.
  `verdict`에 선택 필드 `decision_comparison`을 추가한다: `policy`(`hold-only-simple-mean-v1`), `hold_band`(0.2),
  `bull_mean`, `bear_mean`, `mean_gap`, `mean_decision`, `original_verdict`(최초 판정 전체, 기존 verdict 형식),
  `explanation_regenerated`(boolean). 과거 기록·단일 분석에는 이 필드가 없을 수 있다.
  Spring은 기존 전체 verdict JSON 저장 경로로 원본을 보존하며 기존 최종 판정 채점·봉인 방식은 유지한다.
  재생성 실패 시 최종 판정을 발행하지 않고 최초 판정은 워커 비공개 `moderator_original` 이벤트에 남긴다.
  초기 중재 요청 형식·토론 흐름은 유지하며 변경 시의 추가 호출도 기존 사용량에 합산된다. 공동 검토 전 초안이다.

- v0.12 구현 초안 (2026-11-12): 사용자 결정으로 공개 전 리뷰어를 제거한다(비용: 토론당 LLM 호출 6회, effort high).
  필드·이벤트 구조는 그대로이며 `statement_accepted`는 응답 형식 처리 직후 전달된다. 비공개 `statement_reviewed` 이벤트와
  감사 기록의 `statement_reviewer` 역할은 더 이상 생기지 않는다. 워커 설정 `BULLBEAR_REVIEW_STATEMENTS`는 삭제됐다. 공동 검토 전 초안이다.
  같은 초안에서 스냅샷 `facts`에 근거로 걸 수 있는 ID가 추가된다(필드 구조는 그대로): 최근 20거래일 날짜별
  `PX.DAY_YYYYMMDD`(값은 그날 등락률 %, note에 가격·거래량·같은 날 코스피 등락률), `PX.VS_MA200`(200일 이동평균 대비 %).
  이동평균 Fact 값은 원 단위로 반올림한다. 웹 용어 사전에 이 ID들과 기존 `PX.MA200`이 없어 칩 이름이 ID로 보일 수 있다
  (`facts[source_id].label` 또는 `observation.label`로 대체 필요).
  같은 초안에서 사용자 결정으로 중재자 `verdict.decision`은 `BUY` 또는 `SELL`만 낸다(`HOLD`·판단 유보 없음, 필드 타입은 그대로라
  예전 기록의 `HOLD`도 읽을 수 있다). `confidence`는 고른 쪽이 맞다고 보는 정도로 0.5~1을 쓴다.
  Spring 채점에서 중재자는 더 이상 ±2%p 보유 구간을 맞힐 수 없으므로 AI 적중률의 의미가 달라진다.

- v0.11 구현 초안 (2026-11-11): 사용자 요청으로 토론의 코드 내용 검증기를 제거하고 공개 전 리뷰어는 유지한다.
  기존 필드 구조로 `verified=false`, `verification_scope=not_checked`, 미측정 검증 비율 `null`을 전달한다.
  필수 응답 형식 복구·리뷰어 패치 처리·판정 봉인은 유지한다. Spring/web은 해당 검증 필드를 게이트로 사용하지 않음을 확인했으며 공동 검토 전 초안이다.

- v0.10 (2026-11-11): 백테스트용 선택 필드. `GET /stocks/{ticker}?as_of=`, `POST /debates`의 `as_of`.
  보내지 않으면 기존과 똑같다. Spring 백테스트 실행기(`POST /ops/backtest`)가 쓴다. 워커 구현은 jangwonii.

- v0.9 구현 초안 (2026-11-10): 워커의 RAG 실행 경로 제거에 맞춰 `POST /rag/query`, `POST /rag/search`,
  `POST /rag/facts`와 Spring의 `POST /api/debates/{id}/rag/search`, `POST /api/debates/{id}/rag/facts`를 폐기한다.
  토론과 단일 분석은 저장 스냅샷의 Fact를 사용하며 종목·스냅샷·토론·SSE·가격 조회의 계약은 유지한다.

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
- 토론 엔진은 공개 전 리뷰어를 유지하며 코드의 수치·개념·논리·표현 검증과 내용 재작성을 적용하지 않는다.
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

# 불앤베어 API 서버 (Spring Boot)

브라우저가 호출하는 유일한 서버. 사용자, 토론 중계, 판정 봉인, 사용자 판정을 맡는다.
AI 토론 자체는 Python 워커가 하고, 계약은 [`../docs/worker-api.md`](../docs/worker-api.md).

## 실행

```bash
docker compose up -d          # 루트에서. Postgres 16 (포트 5433)
cd api
./gradlew bootRun             # http://localhost:8080
./gradlew test                # Testcontainers로 Postgres를 띄워 통합 테스트 (Docker 필요)
```

기본은 **가짜 워커**(`bullbear.worker.mode=fake`)라서 Python 워커 없이 전체 흐름이 돈다.
실제 워커에 붙일 때는 `application.yml`의 `bullbear.worker.mode`를 `http`로, `base-url`·`token`을 맞춘다.

또는 `WORKER_TOKEN`을 Python 워커와 동일하게 설정하고 `./gradlew bootRun --args='--spring.profiles.active=worker'`로 실행한다.
`WORKER_BASE_URL` 기본값은 `http://localhost:8000`이다. Windows는 `./gradlew.bat`을 사용한다.
워커 기동·키 설정·재현 가능한 HTTP 통합 테스트는 [워커 README](../ai-worker/README.md#spring과-실제-워커-연결)를 참고한다.

스택: Spring Boot 4.1, Java 17, PostgreSQL 16, Flyway, JPA, WebClient(워커 SSE 구독).

## API (브라우저용)

인증은 `Authorization: Bearer <token>`. 첫 접속 때 게스트 토큰을 받는다.
브라우저 `EventSource`는 헤더를 못 붙이므로 `/stream`만 `?access_token=` 쿼리도 받는다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/guest` | 게스트 계정 생성 → `{userId, token}` |
| GET | `/api/me` | 내 정보 |
| GET | `/api/stocks/search?q=` | 종목명·코드·초성 검색. 토론 불가 종목은 `eligible:false` + `blockReason` |
| GET | `/api/stocks/{ticker}` | 종목 확인 화면: 종가, 60일 스파크라인, 토론 가능 여부, 오늘 토론(`todayDebate`) |
| POST | `/api/debates` | `{ticker}` 토론 시작. 오늘 같은 종목 토론이 있으면 재사용(`reused:true`) |
| GET | `/api/debates/{id}` | 토론 상태, 스냅샷 기준일·기준가 |
| GET | `/api/debates/{id}/stream` | SSE. 쌓인 이벤트 재생 후 라이브. `Last-Event-ID` 또는 `?after=`로 이어 받기 |
| POST | `/api/debates/{id}/judgment` | 내 판정 `{decision, confidence, evidencePicks, memo}` → 중재자 판정 공개 |
| GET | `/api/debates/{id}/reveal` | 내 판정을 낸 뒤에만. 그 전에는 403 `SEALED` |
| GET | `/api/me/judgments` | 내 판정 목록 + 채점 상태(3·7거래일, 예상일, 결과) |
| GET | `/api/me/judgments/{id}` | 채점 결과 화면: 내가 고른 근거, 중재자의 결정적 근거, 메모 |
| GET | `/api/me/stats` | 7거래일 기준 적중률, AI 적중률, AI를 이긴 판정 수, 근거 습관 |

오류는 모두 `{"error": {"code", "message"}}`.

## 설계 메모

**판정 봉인.** 워커의 `debate_completed`에는 중재자 판정이 들어 있다. DB에는 원본 그대로 저장하지만,
브라우저로는 `debate_sealed`(내용 없음)로 바꿔 보낸다 (`ClientEvent`). 판정은 `/judgment` 제출 응답이나
`/reveal`로만 나가고, 둘 다 그 사용자의 판정이 있어야 한다.

**중계와 재연결.** `DebateRelay`가 워커 SSE를 구독해 이벤트마다 한 트랜잭션으로 저장한다.
끊기면 마지막으로 저장한 seq부터 다시 구독하고(지수 백오프 5회), 같은 seq는 한 번만 저장한다.
서버가 재시작되면 진행 중이던 토론을 이어서 구독한다. 5회 실패하면 `debate_failed`를 남기고 닫는다.

**브라우저 스트림.** `DebateStreamHub`는 연결 시 DB 이벤트를 먼저 재생하고 라이브로 이어 붙인다.
재생과 라이브 전송을 구독자 단위로 동기화하고 seq로 중복을 걸러, 그 틈에 들어온 이벤트가 빠지거나 두 번 가지 않는다.

**토론 재사용.** 같은 날(KST) 같은 종목이면 스냅샷 데이터가 같으므로 새로 돌리지 않는다.
동시에 두 요청이 들어오면 지금은 토론이 두 개 생길 수 있다 (다음 단계: 종목·날짜 유니크 제약 또는 advisory lock).

**채점.** 판정을 내면 3·7거래일 채점이 예약된다(`judgment_scores`). 거래일 달력을 하드코딩하지 않고,
기준일 이후 워커 시세에 실제로 있는 날을 세어 N번째 종가로 채점한다 (휴장일이 끼면 자연히 밀림).
평일 16:10·18:10·20:10(KST)에 돌고, 시세가 아직 없으면 다음 회차에 다시 본다. 같은 건은 두 번 채점하지 않는다.
테스트는 `MutableClock`으로 날짜를 옮겨 검증한다.

**판정 1회.** `(user_id, debate_id)` 유니크. 더블 탭으로 두 번 오면 먼저 저장된 판정을 돌려준다.

## 다음 단계

- 카카오 로그인 (게스트 → 회원 승격, 토큰을 JWT로)
- 모의체결 원장 (멱등 키, 잔고 동시성)
- 토론 동시 생성 방지

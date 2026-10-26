# 작업 로그

작업을 마칠 때(또는 PR을 올릴 때) **맨 위에** 한 항목을 추가한다. 다음 사람이 이것만 읽고 이어서 할 수 있게 쓴다.
Claude Code는 세션 시작 시 이 파일의 최근 항목이 자동으로 보인다 (SessionStart 훅). Codex는 `AGENTS.md` 안내에 따라 `./scripts/session-brief.sh`를 실행해 본다.

형식:

```
## YYYY-MM-DD · 이름 · 영역(api / web / ai-worker / docs)
- 한 것: 무엇을 했는지 (PR 번호)
- 진행 중: 끝나지 않은 것, 어느 브랜치에 있는지
- 다음: 다음에 할 일 (누가)
- 막힘·결정 필요: 다른 사람 확인이 필요한 것
```

---

## 2026-10-26 · ricky00-dev · ai-worker, api
- 한 것: 워커 FastAPI 서버 골격 (feat/worker-server) + Spring ↔ 실제 워커 첫 연동
  - 계약 엔드포인트 전부: 검색(초성)·상세·토론 가능 여부·토론 시작·SSE 이벤트·토론 조회·스냅샷·채점용 시세·지수
  - 동시 실행 3 + 대기열(넘치면 429 BUSY), request_id 멱등, Last-Event-ID 이어 받기, 재시작 시 끊긴 토론은 실패로 닫음
  - 확정 종가만 사용 (장중 일봉 제외) → 채점 기준 가격·재사용 키가 흔들리지 않음
  - `BULLBEAR_AGENTS=scripted`: LLM 없이 실제 시세로 전체 흐름 확인. Spring http 모드로 NAVER 토론 → 봉인 → 판정 → 공개 확인
  - **버그 수정 (api)**: Spring Boot 4에서 WebClient.Builder가 별도 스타터라 http 모드로 아예 못 떴음 → `spring-boot-starter-webclient`, 회귀 테스트 추가
  - 워커 계약 v0.5
- 다음: M3 타임머신 퀴즈 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**): `docs/worker-api.md` "워커 담당 메모"의 남은 일. 골격은 바꿔도 되지만 계약 형식은 `wire.py`에서만 맞추기

## 2026-10-23 · ricky00-dev · api, web, docs
- 한 것: 전향 운용 스케줄러 + 토론 재사용 기준을 데이터 기준일로 (feat/forward-run)
  - 재사용 키 `(종목, 최신 종가 날짜)`: 장 마감 뒤 만든 토론은 다음 날 장 마감 전까지 누구나 대기 없이 재사용
  - 스케줄러: 고정 10종목을 16:40·18:40에 2개씩 동시 실행, 하루 $4 상한, 서버 시작 시 밀린 회차 실행. 기본은 꺼짐
  - `docs/ARCHITECTURE.md`(LLM 지연 줄이는 4층 전략, ADR), `docs/experiment.md`(토론 vs 단일 실험 설계)
  - 워커 계약 v0.4: `GET /stocks/{ticker}`의 `as_of` 의미 명시
- 다음: 홈 "오늘의 토론" 피드 + 투자 유의 고지 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**):
  - 발언 병렬화 제안 (ARCHITECTURE ADR-2): 라운드마다 매수·매도 동시 호출 → 발언 단계 약 절반, 순서 편향 제거
  - 단일 에이전트 모드 `mode: "single"` (experiment.md) — 계약 v0.5로 같이 정하기
  - 과거 날짜 스냅샷(`as_of` 지정) 가능 여부 — 타임머신 퀴즈 문제 미리 쌓기

## 2026-10-23 · ricky00-dev · api, web, docs
- 한 것: 토론 비용 상한·중복 방지 (feat/cost-guard)
  - 같은 종목 같은 날 토론은 DB 유니크 인덱스로 1건만. 동시 요청은 먼저 들어간 토론을 재사용 (테스트로 경합 확인)
  - 워커 `usage`로 토큰·비용(USD) 저장 → 사용자 토론 하루 $3 상한, 사용자당 하루 새 토론 5회
  - 종목 화면에 남은 횟수 표시, 막히면 버튼 비활성 + 이유
  - 워커 계약 v0.3: `usage`를 모델별(`calls`) + 선택 `cost_usd`로. v0.2 형식도 받음
- 다음: 전향 운용 스케줄러 + 실험 설계 문서 (ricky00-dev)
- 막힘·결정 필요: **jangwonii** 계약 v0.3 `usage` 형식 확인. Haiku 5.5는 `fallbacks` 미지원 (ROADMAP 위험 참고)

## 2026-10-23 · ricky00-dev · docs
- 한 것: 작업 로그, AGENTS.md(Codex)·CLAUDE.md(Claude Code) 공통 안내, 세션 시작 훅, PR 템플릿 추가
- 다음: 토론 중복 방지 + LLM 비용 집계·일일 상한 (api) — ricky00-dev
- 막힘·결정 필요:
  - 전향 운용 종목 수 10개 vs 20개 (팀 결정)
  - 채점 규칙 ±2%p, 코스닥도 코스피 비교로 갈지 (팀 결정)
  - Max 결제 갱신일 확인 → 월 $200 API 크레딧 일일 상한 계산 (ricky00-dev)

## 2026-10-23 · ricky00-dev · api, web
- 한 것: 채점 스케줄러 + 내 판정 탭 + 채점 결과 화면 (#4 머지)
  - 3·7거래일 뒤 코스피 대비 채점, 거래일 달력 없이 실제 시세가 있는 날을 셈
  - `GET /api/me/judgments`, `/api/me/judgments/{id}`, `/api/me/stats`
  - QA: `BULLBEAR_DEV_CLOCK_OFFSET=P11D BULLBEAR_SCORING_CRON='*/15 * * * * *' ./gradlew bootRun`
- 막힘·결정 필요: 워커 API 계약 v0.2 (`/prices/daily`, `/indices/daily`) — **jangwonii 확인 필요**

## 2026-10-23 · ricky00-dev · api, web
- 한 것: Spring API 뼈대 (#2), React 웹 뼈대 (#3) 머지
  - 게스트 토큰, 토론 중계(SSE), 판정 봉인, 판정 제출·공개, 가짜 워커
  - 웹 5개 화면: 검색 → 종목 → 토론 → 판정 → 공개
- 다음: **jangwonii**: `docs/worker-api.md` 기준으로 ai-worker에 FastAPI 엔드포인트 구현
  (지금 워커는 CLI만 있음. Spring은 `bullbear.worker.mode=http`로 바꾸면 실제 워커에 붙는다)

## 2026-10-20 · ricky00-dev · ai-worker
- 한 것: Python 핵심 파이프라인 (CLI)
  - `MarketDataSource`(pykrx+OpenDART), `NewsSource`(네이버), 스냅샷 고정, 근거 검증기, 3라운드 토론, 중재자
- 확인 못 한 것: API 키가 없어 실제 토론·DART·네이버 뉴스는 한 번도 안 돌려봄 (시세 스냅샷만 확인)
- 알려진 문제: pykrx의 KRX API(PER/PBR, 시가총액, 전체 종목 목록, 지수)는 빈 응답 → 밸류에이션은 직접 계산

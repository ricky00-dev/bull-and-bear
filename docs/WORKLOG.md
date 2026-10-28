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

## 2026-10-28 · ricky00-dev · api, web
- 한 것 (feat/time-machine-quiz):
  - `debate_outcomes`: 끝난 토론마다 7거래일 뒤 실제 결과(종목·코스피·초과수익)를 한 번 기록 (`OutcomeRecorder`, 채점과 같은 시각 + 시작 시 따라잡기). 실험 집계에도 쓸 수 있음
  - 퀴즈 API `POST /api/quiz/rounds`, `GET /api/quiz/rounds/{id}`, `POST /api/quiz/rounds/{id}/questions/{idx}/answer`
    - 문제: 결과가 기록된 토론에서 무작위 5개. 이미 풀었거나 실제로 판정한 토론은 뒤로. **결과를 보고 고르지 않음**
    - 공개 전: 종목명·별칭·종목코드를 "이 회사"로 가림, 차트는 판정일까지만(날짜·가격 없음), 힌트는 업종 + "몇 월 몇째 주"
    - 답하면 종목·실제 결과·AI 판정과 이유·전체 차트 공개. 기록은 `quiz_*` 테이블, 실제 판정 통계와 분리
  - 웹: 하단 탭 "리그"(미구현 자리) → "퀴즈". 입구 / 문제 / 공개 / 한 판 결과(나 vs AI)
  - 말풍선 컴포넌트 공통화 (`StatementBubble`), 차트 날짜 가림 모드
  - 채점 예정일이 지났는데 아직 채점 전이면 "곧 채점"으로 표시 (지난 날짜에 "예정"이 붙던 문제)
- 확인: QuizFlowTest(가림·채점·중복 답 방지·남의 퀴즈 404·통계 분리), 브라우저로 시계 +11일 띄워 한 판 끝까지
- 다음: 전시 모드 (ricky00-dev)
- 막힘·결정 필요: 실제 문제는 전향 운용 시작(늦어도 11/4) 뒤 7거래일, 즉 11/13쯤부터 생긴다. 그 전 시연은 가짜 워커 + 시계 앞당김으로
## 2026-10-28 · ricky00-dev · api, web
- 한 것 (feat/price-chart, #15):
  - `GET /api/debates/{id}/chart`: 판정일 앞 약 20거래일 ~ 7거래일 뒤(+2)까지, 종목·코스피를 판정일 종가 대비 수익률(%)로. 3·7거래일 지점(도달 전엔 예상일)
  - 두 선의 차이 = 채점 초과수익 (ChartFlowTest로 확인). 확정 종가만 씀
  - `PriceHistory`: (종목, 기간)별 그날 하루 캐시. 결과 화면을 여러 명이 열어도 워커는 하루 한 번
  - 채점 결과 화면에 `ReturnChart`: 판정 뒤 회색 띠 = 코스피 ±2%p(보류 구간). 판정 직후에도 7일까지 자리를 비워 두고 예정일 표시
  - 가짜 워커: 10/22 이전 시세도 거꾸로 생성(차트용), 모든 종목 스파크라인, 등락을 섞어 직선처럼 안 보이게
- 확인: API 테스트 20개 통과, 브라우저로 SK하이닉스(3일 채점 후)·현대차(판정 직후) 화면 확인
- 다음: 타임머신 퀴즈 (ricky00-dev). ROADMAP의 주가 차트 항목 체크는 #14 머지 뒤
- 막힘·결정 필요: 없음. 워커의 `/prices/daily`, `/indices/daily`가 판정일 30일 전부터도 응답해야 차트 앞부분이 나온다 (계약상 기간 조회라 추가 작업 없음)
## 2026-10-28 · ricky00-dev · web, docs
- 한 것 (feat/plain-terms):
  - 토론 발언·중재자 이유 본문의 투자 용어(40여 개)에 점선 밑줄 → 누르면 쉬운 풀이 시트 (`lib/glossary.ts` `TERMS`, `components/TermText.tsx`)
  - 같은 용어는 발언마다 처음 한 번만 밑줄. 영문 약어는 단어 경계를 지킴 (PERFORMANCE 속 PER 무시)
  - 시트 공통화 `ui.tsx` `BottomSheet` (근거 시트도 이걸 씀)
  - 판정 화면 "판정 팁": 말솜씨보다 근거의 탄탄함을 보라는 한 줄
  - README 맨 위에 서비스 한 줄 정의, ROADMAP에 주가 차트·퀴즈 원칙·11/18 발표 메시지 결정·실시간 시세 제외 이유
  - worker-api.md "웹 쪽 희망 사항": 입문자 말투, 선택 필드 `statement.plain` 제안 (계약 아님)
- 확인: 가짜 워커 토론에서 밑줄·시트 동작 브라우저로 확인, tsc·lint 통과
- 다음: 주가 차트(종가) → 타임머신 퀴즈 → 전시 모드 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**): `statement.plain`을 넣을지, 발언 말투를 입문자 기준으로 할지
## 2026-10-26 · ricky00-dev · ai-worker, api
- 한 것:
  - 워커 HTTP 서버 **틀만** (feat/worker-server-stub): 계약 엔드포인트 시그니처·인증·오류 형식, 내용은 전부 501
  - Spring http 모드 버그 수정 분리 (#12): Spring Boot 4 WebClient 스타터 누락으로 실제 워커 모드에서 앱이 안 떴음
  - PR #11(완성형 워커 서버)은 닫음. 에이전트·워커 설계는 jangwonii가 직접 하기로 (브랜치 `feat/worker-server`는 참고용으로 남김, 안 봐도 됨)
- 다음: M3 타임머신 퀴즈 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**): 워커 설계·구현 시작. 기존 10/20 코드는 초안이라 바꿔도 됨. `docs/worker-api.md` "Spring이 기대하는 것" 참고
## 2026-10-26 · ricky00-dev · deploy
- 한 것: 배포 준비 (chore/deploy)
  - Dockerfile: api(Gradle → JRE), web(Vite 빌드 → Caddy), ai-worker(uv, 비루트 실행)
  - `deploy/compose.yml`: Caddy(HTTPS 자동, /api 프록시, SPA) + Spring + Postgres + 워커(profile). 외부엔 80/443만
  - 로컬에서 운영 구성 실행 확인: 정적 파일·딥링크·API·SSE 스트림(버퍼링 없음)·서비스 워커·백업 스크립트
  - `docs/DEPLOY.md`: EC2 t3.small, sslip.io로 도메인 없이 HTTPS, 처음 설정·업데이트·운영 명령
- 다음: 워커 FastAPI 골격 초안 (jangwonii 인수인계용), 그다음 M3 타임머신 퀴즈 (ricky00-dev)
- 막힘·결정 필요:
  - **ricky00-dev**: AWS 계정 (11/2 전), 키 4종
  - **jangwonii**: 워커 이미지는 빌드됨. `bullbear.server:app`(FastAPI)과 `fastapi`·`uvicorn` 의존성만 있으면 뜸. 인증은 `X-Worker-Token` == env `WORKER_TOKEN`
## 2026-10-26 · ricky00-dev · api, web
- 한 것: 홈 "오늘의 토론" 피드 + 첫 방문 안내·투자 유의 고지 (feat/home-feed)
  - `GET /api/feed`: 최신 데이터 기준일 토론을 진행 중 → 판정 많은 순으로. 판정 수, 내 판정 여부 포함, 중재자 판정은 제외(봉인)
  - 워커 호출 없이 DB 쿼리 한 번. 피드의 토론은 전부 재사용 대상이라 누르면 대기 없음
  - 첫 방문 안내 시트(3단계 설명 + 투자 유의 고지), 공개 화면 하단 고지
- 다음: Docker 이미지 + 운영 compose (배포 준비, ricky00-dev)
- 메모: 이 터미널의 `NODE_OPTIONS`가 없는 파일을 가리켜 npm이 실패함 → `env -u NODE_OPTIONS npm ...`로 실행

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

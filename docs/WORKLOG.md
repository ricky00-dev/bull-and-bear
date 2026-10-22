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

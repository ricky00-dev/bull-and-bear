# 불앤베어 — AI 코딩 도구 작업 안내

Codex는 이 파일(`AGENTS.md`)을, Claude Code는 `CLAUDE.md`를 통해 같은 내용을 읽는다. 안내를 바꿀 때는 이 파일만 고친다.

졸업 전시 팀 프로젝트. 매수·매도 AI 에이전트 토론을 보고 사용자가 먼저 판정하고, AI 중재자 판정과
실제 주가(3·7거래일 뒤 코스피 대비)로 채점받는 모의투자 교육 서비스. 전체 구조는 `README.md`.

## 세션 시작할 때

1. 현황 요약을 먼저 본다: `./scripts/session-brief.sh` 실행 (브랜치, 최근 작업 로그, 열린 PR, develop 커밋).
   Claude Code는 세션 시작 훅이 자동으로 실행해 주므로 생략해도 된다.
2. 이어서 할 작업이 다른 사람 영역과 닿으면 `docs/WORKLOG.md`의 "막힘·결정 필요"를 확인한다.
3. Spring ↔ 워커 사이 일이면 `docs/worker-api.md`(계약)가 기준이다.
4. 일정·우선순위·결정 사항은 `docs/ROADMAP.md`.

## 작업 마칠 때 (필수)

- `docs/WORKLOG.md`의 `---` 바로 아래에 새 항목을 추가한다 (최신이 위). 형식은 파일 맨 위 참고.
- "한 것 / 진행 중 / 다음 / 막힘·결정 필요"를 다음 사람이 이것만 읽고 이어갈 수 있게 쓴다.
- 확인하지 못한 것(테스트 못 돌림, 키 없어서 미확인 등)은 숨기지 말고 적는다.

## 담당과 폴더

| 폴더 | 내용 | 담당 |
|---|---|---|
| `api/` | Spring Boot 4.1, Java 17, PostgreSQL, Flyway | ricky00-dev |
| `web/` | React 19, Vite, TS, Tailwind 4 (모바일 우선, PWA) | ricky00-dev |
| `ai-worker/` | Python 3.12, uv, Anthropic SDK. 에이전트·워커 설계와 구현 (기존 코드는 초안, 바꿔도 됨) | jangwonii |
| `docs/worker-api.md` | Spring ↔ 워커 계약 | 공동 (바꿀 땐 양쪽 승인) |

## 규칙

- 브랜치: `develop`에서 `feat/…`, `fix/…`, `docs/…`, `chore/…`로 따서 작업 → `develop`으로 PR. `main`은 마감 때만.
- API 키, `.env`는 커밋하지 않는다. 키는 레포 밖에서 공유.
- 워커 계약을 바꾸면 `docs/worker-api.md`의 변경 이력에 버전과 이유를 적는다.
- 중재자 판정은 사용자가 판정을 내기 전에는 브라우저로 나가면 안 된다 (판정 봉인). Spring의 책임.

## 자주 쓰는 명령

```bash
docker compose up -d                      # Postgres (포트 5433)
cd api && ./gradlew bootRun               # API :8080 (기본 가짜 워커)
cd api && ./gradlew test                  # 통합 테스트 (Docker 필요)
cd web && npm run dev                     # 웹 :5173
cd ai-worker && uv run pytest             # 워커 테스트
cd ai-worker && uv run bullbear snapshot 삼성전자   # 데이터만 확인 (LLM 호출 없음)
./scripts/session-brief.sh                # 작업 현황 요약 (훅과 같은 내용)
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build   # 운영 구성 (docs/DEPLOY.md)
```

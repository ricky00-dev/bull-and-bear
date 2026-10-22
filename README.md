# 불앤베어 (가칭)

매수·매도 AI 에이전트의 토론을 보고 사용자가 먼저 판정하고, AI 중재자 판정과 실제 주가로
채점받으며 투자 근거 읽는 법을 배우는 모의투자 교육 서비스. 졸업 전시 팀 프로젝트 (2026-10-19 ~ 11-30).

## 구조

```
브라우저 (web/, React) ── Spring API 서버 (api/) ── PostgreSQL
                  │  HTTP + SSE
                  ▼
           Python AI 워커 (ai-worker/) ── pykrx, OpenDART, 네이버 뉴스, Claude API
```

| 폴더 | 내용 | 담당 |
|---|---|---|
| `api/` | Spring Boot: 사용자, 판정, 모의체결 원장, 채점, 리그, 웹소켓 중계 | [이름] |
| `web/` | React + Vite + TypeScript, Tailwind, TanStack Query, SSE 수신 | [이름] |
| `ai-worker/` | 스냅샷, 토론 에이전트, 근거 검증기, 중재자 | [이름] |
| `docs/worker-api.md` | Spring ↔ 워커 API 계약 | 공동 |

각 폴더의 README에 실행 방법이 있다.

## 협업 규칙

- `main` 직접 푸시 금지. 브랜치 → PR → 리뷰 1명.
- 워커 API를 바꿀 때는 `docs/worker-api.md`를 먼저 고치는 PR을 올리고 양쪽 담당자가 승인한다.
- `.env`, 데이터 파일은 커밋하지 않는다. 키는 레포 밖에서 공유한다.

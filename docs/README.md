# 문서 안내

## 현재 작업을 이어갈 때

| 목적 | 먼저 읽을 문서 |
|---|---|
| 프로젝트 구조·실행 시작 | [루트 README](../README.md), [API](../api/README.md), [웹](../web/README.md), [워커](../ai-worker/README.md) |
| 워커 최신 결과·남은 순서 | [2026-11-02 현황·인계](evaluations/worker-goal-readiness-20261102.md) |
| 일정·담당·팀 결정 | [ROADMAP](ROADMAP.md) |
| 최근 작업·막힘 | [WORKLOG](WORKLOG.md), `scripts/session-brief.sh` |
| Spring ↔ 워커 연동 | [worker-api](worker-api.md): 공개 계약의 기준 |
| 인증·비용·재시작·복구 | [WORKER-OPERATIONS](WORKER-OPERATIONS.md) |
| 배포 구성·명령 | [DEPLOY](DEPLOY.md): 실제 배포 완료 증거와 구분 |
| 설계 이유·대안 | [ARCHITECTURE](ARCHITECTURE.md): 제안과 구현 상태를 구분 |
| 토론 vs 단일 평가 설계 | [experiment](experiment.md) |

## RAG 문서

| 문서 | 역할 |
|---|---|
| [RAG-DATA](RAG-DATA.md) | 자료 수집·저장 설계 |
| [RAG-LONG-TERM](RAG-LONG-TERM.md) | 시험 운영 계획·단계 |
| [RAG-WEEK-ONE](RAG-WEEK-ONE.md) | 구현 진행과 실행 안내 |
| [RAG-PUBLICATION-RUNBOOK](RAG-PUBLICATION-RUNBOOK.md) | 검색 세대 공개·전환 절차 |
| [RAG-READINESS-AUDIT](RAG-READINESS-AUDIT.md) | 준비 상태 점검 기록 |
| [RAG-PRIORITIES-20261030](RAG-PRIORITIES-20261030.md) | 당시 우선순위·평가 조건의 이력 |

RAG는 기본 비활성이다. 위 문서의 구현·실험 결과를 운영 활성화 또는 최신 실모델 완주로 해석하지 않는다.

## 실측 기록 읽기

2026-11-02 워커 검증은 [현황·인계의 실행 이력](evaluations/worker-goal-readiness-20261102.md#실모델-실행-이력과-비용)에서
기준 실행→v5→v7→v8 순서로 연결된다. 각 보고서·JSON·대화록은 당시 코드와 결과를 보존한다.
과거 문서의 ‘다음’, ‘미검증’, 승인 대기 문구는 당시 상태이며, 현재 상태는 최신 인계와 WORKLOG를 우선한다.

`evaluations/`의 다른 날짜·조건별 보고서와 [지표 감사](metric-audit-20261029.md)는 실험 근거로 유지한다.
fixture 통합 성공, 실모델 성공, 실제 배포 성공은 서로 대체하지 않는다.
보고서가 가리키는 `ai-worker/data/` 원자료는 Git 제외 대상이므로 새 clone에는 포함되지 않는다.

# 평가 기록 색인

보고서는 당시 코드·입력·조건의 증거다. 테스트 수를 합산하거나 오래된 미완료 항목을 현재 상태로 읽지 않는다.
각 보고서의 날짜·revision, fixture/실모델 구분, 원자료 위치와 한계를 확인한다. JSON·대화록은 해당 보고서에서 연결된다.
Git 제외 원자료는 새 clone에 포함되지 않는다.

현재 워커 인계는 [11월 2일 준비 상태](worker-goal-readiness-20261102.md), RAG 판단은 [운영 준비 감사](../RAG-READINESS-AUDIT.md)를 먼저 읽는다.
워커 실측은 기준 실행 → v5 → v7 → v8 순으로 인계 문서에 연결돼 있다. RAG 검색은 초기 corpus/BM25 → 임베딩 비교 → 선택 정책 → Fact 연결 → 명시적 문서/수치 분리와 교체·복원 기록 순으로 진행됐다.
현재 사용법은 [문서 안내](../README.md)를 기준으로 하며, 이전 계획·WIP 이관 메모는 [보관 영역](../archive/README.md)에 있다.

## 현재 인계와 11월 2일 실모델 실행

- [목표 작업의 실제 워커 1쌍 검증 — 2026-11-02](worker-goal-live-20261102.md)
- [워커 목표 추가 실측 — 2026-11-02, v7](worker-goal-live-v7-20261102.md)
- [v8 실제 토론 원문 — 2026-11-02](worker-goal-live-v8-20261102-transcript.md)
- [v8 실측 및 운영 보호 — 2026-11-02](worker-goal-live-v8-20261102.md)
- [워커 예비 운용 현황·인계 — 2026-11-02](worker-goal-readiness-20261102.md)
- [삼성전자 실제 토론 대화록 — 2026-11-02](worker-http-live-20261102-transcript.md)
- [실제 FastAPI 토론·단일 판정 실측 — 2026-11-02](worker-http-live-20261102.md)

## 단일 모드·의미 검토·데이터 품질

- [스냅샷 품질과 API → AI 입력 전달 설계 — 2026-11-11](worker-snapshot-context-design-20261111.md): 현재 v27 재현, 데이터 결함, 역할별 전달·조회·측정 설계
- [삼성전자 지표 재검증 · 2026-10-29](metric-audit-20261029.md)
- [실제 Claude 의미 검토 수정 전후 비교](semantic-ab-live-comparison.md)
- [B2 평가 구간 보완 및 실제 Claude 재검증](semantic-window-live-comparison.md)
- [HTTP 단일 모드 검증 — 2026-10-31](single-http-validation.md)
- [PR #23 단일 실행 비용·복구 수정](single-mode-recovery.md)
- [단일 판정 반려 원문 검토 및 문맥 지침 보완](single-pilot-review-context.md)
- [워커 데이터 정합성 세션](worker-data-consistency-session.md)
- [유료 호출 없는 실패 진단과 검수 준비](worker-offline-diagnostics.md)
- [워커 오프라인 품질 평가 세션](worker-quality-session.md)

## RAG 검색·저장·복구

- [실제 RAG seed 적재·검색 검증](rag-corpus-pilot.md)
- [질문 의도·Fact 연결 — 오프라인 구현 검증](rag-fact-binding.md)
- [실제 워커·Spring·웹 RAG 연동 검증](rag-live-e2e.md)
- [다종목 문서·Fact 연결 검증 — 2026-11-02](rag-multistock-live.md)
- [실제 임베딩 모델 소규모 평가 — 2026-11-02](rag-real-embedding-pilot.md)
- [로컬 백업·복원과 동시 요청 검사](rag-recovery-load-local.md)
- [PostgreSQL 전체 DB와 로컬 파일 복원 검증](rag-recovery-postgres.md)
- [스냅샷별 generation 고정과 색인 교체 검증](rag-rollover-live.md)
- [답 없음·문단 선택 개선 평가 — 2026-11-02](rag-selection-pilot.md)
- [RAG 4조건 CLI 실행](worker-rag-comparison-cli.md)
- [출처 연결 설명 corpus 독립 검토·검색 평가](worker-rag-editorial-quality.md)
- [RAG 평가 해석 후속 조사](worker-rag-evaluation-research.md)
- [RAG 안정화 통합 및 HTTP 장애 정책](worker-rag-hardening.md)
- [최소 RAG 원문·관측 이력 수집 평가](worker-rag-ingest.md)
- [gpt-5-mini 공통·단기 RAG 실제 호출 파일럿](worker-rag-live-pilot.md)
- [공통·단기 RAG 후속 구현·평가 기록](worker-rag-p1-followup.md)
- [공통·단기 RAG 구현 근거 조사](worker-rag-retrieval-research.md)
- [공통·단기 RAG 실제 검색 경로 평가](worker-rag-retrieval.md)
- [공통·단기 검색 품질 평가 실행기](worker-rag-search-quality.md)

## 워커 통합·비용·감사

- [PR #23·#24·#25 병합 평가](pr-23-24-25-merge-validation.md)
- [워커 HTTP 안정화 세션](worker-http-stability-session.md)
- [독립 검토 P1/P2 수정 및 통합 재검증](worker-integrated-review-fixes.md)
- [워커 완료 변경 통합 검증](worker-integrated-validation.md)
- [모델 입력·비용 예산 구현과 검증](worker-model-budget.md)
- [FastAPI·워커 운영 준비 계획](worker-operational-readiness.md)
- [동일 스냅샷 단일 분석가·토론 비교 실행기](worker-paired-baseline.md)
- [HTTP 워커 실행 감사 검증](worker-run-audit.md)
- [실제 Spring ↔ RAG 워커 로컬 통합 평가](worker-spring-integration.md)

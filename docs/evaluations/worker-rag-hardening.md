# RAG 안정화 통합 및 HTTP 장애 정책

2026-10-30. `feat/rag-hardening`, RAG 기준 `ad8cb26`, 통합 대상 로컬 추적
`origin/develop=447cdf4`의 안정화 변경. 원격 fetch 없이 확인한 참조이며 최신 원격 상태라는 뜻은 아니다.
원본 작업 트리의 미커밋 문서와 다른 RAG 작업 트리는 수정하지 않았다.

## 구현

기존 RAG의 검색 평가·예산·실모델 파일럿을 보존하면서 데이터 안정화 변경을 통합했다.
DART 미발표 응답의 영구 캐시 제거, 공급자 오류 정규화, 제한된 백그라운드 시세 준비,
설정 repr의 비밀값 제거를 포함한다. 충돌한 설정은 비밀값 보호와 RAG 설정을 함께 유지했고,
Spring fixture는 RAG/시계 주입과 Market 종료 정리를 모두 유지했다. 양쪽 WORKLOG도 보존했다.

HTTP 실행 정책 `http-empty-timeout-fallback-v1`을 추가했다.

| 검색 결과 | 실행 | 비공개 기록 |
|---|---|---|
| completed, 경고 없는 관측 시점 검색 | 배경 전달 | use_context, knowledge-short-v1 |
| empty, 경고 없음 | 배경 없이 실행 | fallback, none, no_matching_knowledge |
| timeout, search_deadline만 존재 | 배경 없이 실행 | fallback, none, search_deadline |
| 무결성/시점 위반·알 수 없는 실패·용량 초과 | 중단 | abort, 원래 검색 상태/경고 |
| 검색 또는 감사 저장 실패 | 모델 초기화 전 중단 | 저장 가능한 실패 기록만 유지 |

과거 재구성 컨텍스트는 HTTP 실행에서 거부한다. 사후 재생·비교 도구 자체는 바꾸지 않았다.
실패/빈 컨텍스트를 정상 검색으로 고쳐 쓰지 않으며 기존 불변 저장 형식과 재생을 유지한다.
실행 정책은 감사 fingerprint 입력에 포함된다. fallback인 경우 검색 컨텍스트는 감사에 남지만
토론자에게는 None을 전달한다. 공개 HTTP/SSE·Spring 계약과 판정 봉인 책임은 그대로다.
검색 원문/색인 손상은 안전한 `integrity_error`로 구분하고 예외 문자열은 노출하지 않는다.

검색 재시도나 새 유료 호출을 추가하지 않는다. 종목/기준일 재사용 정책은 유지하므로 fallback으로
완료된 당일 토론도 재사용된다. 검색이 복구됐다는 이유만으로 당일 토론을 다시 생성하지 않는다.
benchmark는 고정 RAG 조건 실패를 baseline으로 바꾸지 않도록 기존 정책을 유지한다.

## 검증

- 통합 및 최초 정책 변경 후 전체 Python: 373 passed, 외부 Spring 2 skipped (36.87초).
- 추가 무결성 분류·실제 Retriever 저장/재생·HTTP 정책 집중 회귀: 49 passed (17.64초).
- 최종 전체 Python 재검증: 377 passed, 외부 Spring 2 skipped (36.31초).
- 실제 저장층을 통과한 timeout은 원래 상태로 재생 가능하고 HTTP 토론만 배경 없이 완료한다.
  무결성 오류와 저장 실패는 runner가 호출되지 않는다. 감사 쓰기 실패도 모델 초기화 전에 중단한다.
- 종목/기준일 재사용과 공개 이벤트의 컨텍스트/대체 사유 비노출을 확인했다.
- 기존 synthetic 검색 CLI: 13시도, completed 6/empty 7, positive 6, negative 7.
  candidate Recall@20=1.0, MRR@20=1.0, 선택 recall=1.0, negative 오탐 0,
  시간/시장/종목/금지 문단 위반 각 0, 검색 p95 0.016초, 저장 포함 p95 0.093초.
  precision 정답 범위가 완전하지 않아 precision은 null이다.

검색 산출물: `ai-worker/data/evaluations/rag-hardening-20261030/report.json` (로컬, 미커밋).
현재 평가셋 hash: `64b8efb48220261e29d3573953dded657f2964a0748912274675f220c1cc4f71`.
평가셋·검색 순위 알고리즘은 이번에 수정하지 않았다. 기존 개발용 탐침의 회귀 성적이며
독립 검색 품질이나 운영 부하 SLA, 예측 성과 개선을 뜻하지 않는다.

재현: ai-worker에서 `python -m pytest -o pythonpath=src -q`.
검색 CLI는 `PYTHONPATH=src`로 `python -m bullbear.rag.evaluation
tests/fixtures/rag_evaluation/concept-probes-v1.json --output <새 출력 경로>`.

## 남은 작업

RAG 기본 비활성을 유지한다. 기존 실모델 파일럿의 1/4 완료와 운영 보류 판단은 변경하지 않는다.
이번 작업은 유료 모델·외부 데이터·실제 Spring/DB 운영 통합을 실행하지 않았다.
사람이 검수한 지식집/독립 평가셋, 검증기 오탐과 실제 추론 오류의 분리 평가,
정보 마감 시각/기준 가격 정합성, 반복 실모델 완료율·지연·비용 기준 및 전향 성과는 남아 있다.
다음 검색 개선은 해당 평가셋에서 누락 원인을 측정한 후 결정한다.

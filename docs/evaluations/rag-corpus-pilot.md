# 실제 RAG seed 적재·검색 검증

2026-11-01. 기준 `cdc46cb`, 브랜치 `feat/rag-corpus-pilot`.
사용자의 자료 입력 방식 수립·실제 적재·검증 요청에 따라 기존 corpus와 importer를 재사용했다.
자료가 없었던 것으로 가정하지 않았으며 기존 세션의 DB나 실험 산출물을 덮어쓰지 않았다.

## 실행한 것

- SEC/Investor.gov/FINRA 공식 출처4개를 열어 기존 설명의 근거를 재확인.
- `common-short-v1.json`의 자체 한국어 설명6개를 새로운 지속형 RagStore에 적재.
- 실제 UTC 관측 시각으로 generation 발행 후 observed-v1으로 검색. 과거 시각을 소급하지 않음.
- 같은 입력 재적재의 멱등성, 프로세스를 다시 실행했을 때 revision/검수 상태 보존 확인.
- 6개 직접 개념과 6개 표현 변형 및 common/short 무관 질의2개를 실제 FTS 검색에 입력.
- 미래 generation 차단, 원본 Snapshot 불변, 저장 context replay 동일성 확인.
- corpus/ingest/context-index/editorial-evaluation/agents/http 회귀100개 실행.

## 결과

| 검사 | 결과 |
|---|---|
| 실제 적재 문서 / revision / chunk / annotation | 각각6 |
| 두 번째 독립 실행 후 위 개수 | 각각6 유지, collection_runs만2 |
| 직접 개념 목표 문단 선택 | 6/6 |
| 표현 변형 목표 문단 선택 | 4/6 |
| common 무관 질의 | common 문단0개 |
| short 무관 질의 | 단기 고정 배경3개 |
| 미래 세대 차단 / Snapshot 불변 / replay 일치 | 모두 확인 |
| 관련 pytest | 100 passed, 실패0, 생략0 (13.04초) |
| 유료 모델 / 외부 시장 API 호출 | 0 |

누락 사례는 `매출 중 본업으로 남긴 이익의 비중`→영업이익률,
`가격의 흔들림은 오를 가능성을 뜻하나`→변동성이다.
FTS5의 단어 일치 및 제한된 alias로 포괄하지 못했다. 점수를 맞추기 위한 테스트 문장 전용
alias나 기준 완화는 하지 않았다. 현재 실제 호출자는 Snapshot의 Fact ID/개념 라벨을 사용하며,
이번 표현 변형은 그 경계의 탐색 평가이지 자연어 사용자 검색 API의 시험이 아니다.

short 검색은 고정 코스피/거래일/event_relevance 용어가 있어서 무관 개념에도 배경이 반환된다.
따라서 short의 목표 문단 포함을 정밀도나 질문별 의미 적합성으로 해석하지 않는다.
반환되는 배경 전체가 empty인지와 특정 경로에 문단이 없는지도 구분했다.

## 저장 위치와 재현

절차: [RAG-DATA](../RAG-DATA.md).
코드: `scripts/test-rag-corpus.py`.
로컬 DB: `ai-worker/data/rag-corpus-pilot/rag/rag.sqlite3`.
보고서2개: `ai-worker/data/rag-corpus-pilot/reports/`.
전체 metadata를 제외한 공개 결과: `rag-corpus-pilot-results.json`.

corpus SHA256: `c6d2dabdab21c4cbb50f5b4cf1a36022396a0b860716bafe6a16cfab22fa294e`.
최종 generation: `G.12a990680469ed68328900a4710025ec1e06a7597414d7811ab9f1477b4d458c`.
보고서의 시간은 실제 관측 시각이며 synthetic concept Snapshot을 사용했다.
기존 삼성전자 과거 Snapshot을 오늘 시각으로 조작하거나 새로운 실시장 자료라고 표시하지 않았다.

## 제한

이 작업은 적재/검색/주입 경계의 검증이다. 실제 Claude의 RAG 효과·생성 성공률은 아직 미측정이다.
100개 중 agent/HTTP 검사는 테스트 대역을 사용한다. 이전 Claude 실험 잔액 $1.141036은 사용하지 않았다.
자료6개는 사람 미검수 experimental이며 `--allow-agent-reviewed` opt-in으로만 적재했다.
운영 RAG 스위치·자동 수집 스케줄·배포는 활성화하지 않았다.
원천 사이트의 전체 HTML 불변 사본은 새로 수집하지 않았으며 자체 설명과 메타데이터 해시는 보존했다.
한국 공식 자료·연구 corpus 확장, 독립 검색 정답셋, 사람 승인 워크플로가 후속 과제다.

# 공통·단기 검색 품질 평가 실행기

2026-10-30. 범위는 **synthetic 개념 탐침의 검색 품질과 필터 검증**이다.
실제 모델·인간 검수 corpus·예측 결과·운영 활성화의 완료 기록이 아니다.

## 구현

- `ai-worker/src/bullbear/rag/evaluation.py`: 버전 고정 JSON을 검증하고 별도 출력 폴더에
  RagStore 원문·문단·검수 → GenerationIndex → 실제 Retriever → 불변 replay를 실행한다.
- `ai-worker/tests/fixtures/rag_evaluation/concept-probes-v1.json`: 9개 문단, 13개 탐침.
  정상 개념·영문 별칭·한국어 조사·띄어쓰기·무관 질문과 시점/시장/종목/검수/기간/자료형 제외를 포함한다.
- `ai-worker/tests/test_rag_evaluation.py`: 지표 산식·실검색·누락 보존·장애 분리·입력 검증·출력 보존·CLI 회귀.

현재 서비스는 사용자 자연어 검색 API가 아니라 Snapshot의 Fact 개념 라벨에서 질의를 만든다.
따라서 탐침은 `EVAL.PROBE` Fact의 **개념 라벨**에 질문 변형을 넣은 synthetic Snapshot이다.
이를 실제 서비스 질문 분포 또는 완성된 자연어 검색 벤치마크로 주장하지 않는다.
모델 호출이나 Snapshot Fact→knowledge의 운영 투영을 추가하지 않는다.

모든 문단은 평가용 자체 작성 텍스트다. PER 문단의 비율 정의만
[SEC 재무제표 입문 자료](https://www.sec.gov/investor/pubs/begfinstmtguide.htm)의 개념에 근거해 짧게 작성했다.
나머지는 토큰·필터 시험을 위한 문장이다. synthetic 발행·관측·검수 시각은 해당 공식 페이지의
실제 이력과 다르며 `simulated_publication_not_source_timestamp=true`로 저장한다.
`publication_verified/approved`는 테스트 상태를 모사하는 값이며 사람의 검수를 사칭하지 않는다.
입력 `evidence_type`은 `synthetic_not_human_reviewed`만 허용한다.

## 지표와 실패 처리

- 경로별 candidate Recall@K = 상위 K개 후보에 있는 관련 문단 수 / 정답 관련 문단 수.
- 경로별 reciprocal rank = 첫 관련 후보 순위의 역수. 상위 K 안에 없으면 0.
- macro recall/MRR은 **정답이 있고 검색 자체가 completed/empty인 질문**에 대해서만 평균한다.
  common/short의 BM25를 한 순위로 섞지 않는다. K는 각 경로 최대 20.
- 별도로 실제 선택 묶음의 recall을 기록한다. 후보 성공이 문단 예산·중복 제거 후 성공을 뜻하지 않는다.
- `relevance_scope="exhaustive"`를 명시한 synthetic 질문에는 `selected_precision`
  (선택된 정답 수 / 선택된 고유 문단 수), `unnecessary_selected_count`
  (선택됐으나 완전 정답 집합에 없는 고유 문단 수)를 추가로 기록한다.
  exhaustive는 common/short **전체 선택 묶음**의 관련성 판정이 완전하다는 선언이다.
  기본값은 보수적으로 `subset`이며 이때 미등재 문단을 오답으로 단정하지 않고 두 지표는 null이다.
  기존 고정 JSON에는 선언이 없어 새 precision 지표는 기본적으로 미산정이다.
  이를 실제 운영 corpus의 precision으로 해석하지 않는다.
- 선택 결과가 비었으면 precision 분모가 0이므로 null, 정상 exhaustive 검색의 불필요 선택 수는 0이다.
  실패/시간 초과/예외는 두 지표 모두 null이다. negative에서 문단을 선택했다면 exhaustive일 때
  precision=0이며 선택한 수만큼 불필요 선택으로 센다.
- `selected_precision_successful`은 분모가 있는 exhaustive 성공 질문만 macro 평균하고
  `scored_selected_precision_queries`를 함께 기록한다. 불필요 선택 합계는
  `unnecessary_selected_count_successful`, 집계 질문 수는 `exhaustive_successful_queries`다.
  해당 집계 질문이 하나도 없으면 합계도 null이다.
- 정답이 없는 negative는 recall/MRR=null이며, 선택 문단이 있으면 false positive다.
- failed/timeout/exception은 relevance 0점이나 negative 성공으로 변환하지 않는다.
  전체 시도·상태별 수·검색 가용률·positive 시도/채점 분모를 함께 기록한다.
- 선택 결과의 시간·시장·종목·명시 forbidden 위반을 fixture metadata에서 독립 계산한다.
  현재 통계는 선택 묶음 기준이며 모든 원문에 대한 정책 적합성을 보증하지 않는다.
- 검색 시간과 감사 저장 포함 전체 시간을 분리하고 nearest-rank p95를 사용한다.
- 출력 폴더가 이미 있으면 실패하고 보존한다. dataset hash, generation, policy, context_id,
  실제 query terms·후보·선택 결과·지연을 저장한다. 원시 예외 문자열은 저장하지 않는다.

실행기 자체의 엄격한 품질 게이트는 모든 검색 성공, 모든 positive 후보/선택 recall=1,
negative false positive=0, 정책 위반=0이다. 개선 전 fixture는 통과하지 못했고 아래 최소 별칭 개선 뒤 통과했다.
게이트를 통과하더라도 `operational_activation_eligible=false`이며 운영 활성화 근거가 아니다.
`cost_usd=null`, `accuracy=null`, `usage_status=no_model_calls`를 유지한다.

선택 precision 추가는 **진단 지표 추가**이며 기존 품질 게이트 계산은 변경하지 않았다.
따라서 recall=1이지만 불필요 문단도 포함한 결과에서 기존 gate=true와 precision<1이 함께
나올 수 있다. 추후 precision 수용 기준은 별도 결정해야 한다.
보완 회귀 `tests/test_rag_evaluation.py`: **20 passed, 3.16초**.
실제 저장층 평가 fixture에서 정답 1개+무관 1개 선택 시 recall=1/precision=0.5/불필요 선택=1,
subset null, empty precision null/불필요 선택=0, 장애 모두 null을 확인했다.

## 실제 실행 결과

Python 3.12.15, 기존 로컬 venv, `pythonpath=src`로 현재 worktree 소스를 사용했다.
키·.env 접근·유료 호출 없음. 초기 평가 실행기 테스트: **11 passed, 1.68초**.
별칭 개선 뒤 평가/검색/세대 회귀를 함께 실행해 **46 passed, 17.48초**.

실제 CLI를 별도 실행한 산출물은 ai-worker 아래
`.pytest_cache/search-quality-evaluation-v1/report.json`(개선 전),
`.pytest_cache/search-quality-evaluation-v2/report.json`(개선 후)이다. 로컬 원시 DB/산출물은 커밋하지 않는다.

| 지표 | 개선 전 v1 | 개선 후 v2-korean-alias |
|---|---:|---:|
| 시도 / completed / empty | 13 / 4 / 9 | 13 / 6 / 7 |
| 검색 가용률(completed+empty) | 13/13 | 13/13 |
| positive 질문 / 채점 질문 | 6 / 6 | 6 / 6 |
| candidate Recall@20 (macro) | 0.666667 | 1.0 |
| MRR@20 | 0.666667 | 1.0 |
| 선택 묶음 recall | 0.666667 | 1.0 |
| negative 질문 / false positive | 7 / 0 | 7 / 0 |
| 선택 시점·시장·종목·forbidden 위반 | 각 0 | 각 0 |
| 검색 p95 | 0.016초 | 0.016초 |
| 저장 포함 전체 p95 | 0.079초 | 0.079초 |
| 품질 게이트 / CLI 종료 코드 | false / 1 | true / 0 |

dataset SHA256: `8d4a59b95dc80ed4b21636db948ff227838b4cc6e4b790347cf951a7fb037516`.
13회의 작은 로컬 측정이며 cold/warm·운영 부하를 통제한 SLA 실험이 아니다.
검색 가용률 100%는 relevance 성공률 100%가 아니다.

개선 전 검색 누락은 `변동성은 무엇인가`와 `주가 수익 비율`이었다. 정확한 `변동성`, 영문 `volatility`,
`PER`, 단기 `발표일정`은 각각 정답을 찾았다. unicode61은 형태소 분석기가 아니므로 예상 가능한 한계다.
[SQLite 공식 토크나이저 설명](https://www.sqlite.org/fts5.html#unicode61_tokenizer).

부모 세션의 후속 지시에 따라 `retrieval.py`의 **기존 고정 별칭에만** 조사 접미사와
주가수익비율/주가순자산비율/자기자본이익률의 명시 띄어쓰기 패턴을 적용했다.
정책을 `filtered-bm25-v2-korean-alias`로 바꿔 기존 컨텍스트와 구분한다.
일반 stemming, 임의 부분문자열, 벡터, LLM 질의 재작성은 추가하지 않았다.
`변동성장`, `고변동성상품`, `주가 수익 비율표`, `자기 자본 이익률표`, `performance`의
별도 negative 5개도 실제 검색에서 오탐 0이었다. 이 추가 negative는 위 13개 지표에 합산하지 않는다.
개선 후 1.0은 **같은 개발용 fixture를 보고 수정한 in-sample 회귀 성적**이며 독립 검색 품질 증명이 아니다.

실패 경로는 별도 테스트에서 missing generation을 주입했다. status=failed, 가용률=0,
positive_attempts=1/scored_positive_queries=0, macro recall=null을 확인했다.
오류를 recall=0이나 empty로 숨기지 않았다.

## 재현

```powershell
cd ai-worker
python -m pytest -o pythonpath=src tests/test_rag_evaluation.py -q
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m bullbear.rag.evaluation tests/fixtures/rag_evaluation/concept-probes-v1.json --output data/evaluations/concept-probes-v1
```

동일 output은 덮어쓰지 않으므로 다음 실행에는 다른 경로를 지정한다.
품질 게이트 미달 시 CLI 종료 코드 1과 보고서를 함께 남긴다. 현재 고정 fixture는 개선 후 0으로 종료한다.

## 후속 판단

1. 현재 질의가 고정된 Fact 라벨에서 오는 점을 고려하면, 무조건 형태소 분석기를 추가하기보다
   실제 운영 라벨·별칭 목록을 먼저 고정하고 별도 held-out 변형 질문을 추가하는 편이 작고 검증 가능하다.
2. 동일 fixture를 보고 별칭을 조정한 점수는 학습용 개선치다. 독립 평가셋·사람의 관련성 검수 없이
   운영 검색 품질로 승격하지 않는다. 현재 자료는 실제 한국 금융 연구의 단기 적합성을 검수하지 않는다.
3. 이 작업의 최소 별칭 개선은 retrieval 질의 생성에 한정했고 index/corpus 통계는 바꾸지 않았다.
   RAG 기본 비활성·시장 Fact/공개 인용/7거래일 판정 계약을 유지한다.

# 출처 연결 설명 corpus 독립 검토·검색 평가

2026-10-30. `common-short-editorial-20261030-v1`의 6개 한국어 설명을 별도 하위 세션에서
읽고 공식 basis URL을 직접 열어 확인했다. tokenizer용 synthetic `concept-probes-v1`과 별도 평가다.
이 자료는 **출처를 참조해 AI가 작성한 설명**이며 SEC/FINRA 원문을 직접 인용·수집한 corpus가 아니다.
사람의 검수나 한국 단기 예측 실증으로 표시하지 않는다.

## 원문과 설명 검토

| 자체 설명 | 확인한 원문 | 판단과 한계 |
|---|---|---|
| PER 정의 | [SEC Financial Statement Ratios](https://www.sec.gov/investor/pubs/begfinstmtguide.htm) | 주가/주당순이익·업종별 비율 차이를 확인. 양의 이익·같은 기간 조건하에서 낮은 PER의 해석은 산식에 따른 자체 설명이며 7거래일 예측 주장이 아니다. |
| 영업이익률·보고 기간 | 같은 SEC 자료의 Income Statements/Ratios | 영업이익과 매출·보고 기간·이자/세금 구분과 일치. 현재 종목의 실적 수치를 대신하지 않는다. |
| 변동성과 방향 | [SEC Investor.gov Volatility Risk](https://www.investor.gov/introduction-investing/investing-basics/what-risk) | 내외부 사건으로 가격이 오르내릴 수 있음을 확인. 방향/상승확률로 비약하지 말라는 부분은 자체 해석 규칙이며 확률에 관한 실증 인용이 아니다. |
| 실적 발표와 기대 | [FINRA Earnings Season](https://syndication.finra.org/content/what-earnings-season) | 예상치 초과에도 부정적 전망으로 하락할 수 있다는 설명과 일치. 없는 컨센서스를 만들면 안 되며 미국 사례다. |
| 발표와 공시 시점 | 같은 FINRA 자료 | 정기 보고서 제출 전 발표 가능성을 확인. 한국 공시 제도·기한으로 이식하지 않고 실제 공개 시각을 별도 확인하도록 제한한다. |
| 모멘텀 한계 | [FINRA Momentum](https://syndication.finra.org/content/what-momentum-investing) | 외부 사건에 의한 추세 변경·지표 오신호·과거 성과의 비보장을 확인. 한국 7거래일/KOSPI 제한은 자체 서비스 적용 규칙이며 원문의 검증 결과가 아니다. |

공식 페이지 제목과 명시 날짜는 corpus와 일치했다: SEC 재무제표 2007-02-04,
FINRA 실적 2024-07-23, FINRA 모멘텀 2025-08-12. Investor.gov 위험 페이지의 날짜는
명시하지 않은 채 `published_on=null`로 유지한 것이 적절하다.

다만 원문 페이지 본문·응답 해시를 보관한 스냅샷은 없다. URL·절 제목 연결과 이번 시점의
개념 대조를 수행했으며, 링크가 가리키는 과거 버전의 불변성·미래 변경 추적까지 검증한 것은 아니다.

## 코드 경계 검토

`rag/corpus.py`는 `allow_agent_reviewed=True`를 명시해야 import할 수 있고,
`release_status=experimental`, `review_kind=agent_source_review`, `human_reviewed=false`를 보존한다.
원문 발행일을 한국어 설명의 공개일로 복사하지 않고 authored_at을 사용한다.
실제 archive 관측은 review 이후여야 하며, 문단 annotation도 import 관측 시각에 고정한다.
따라서 오래된 SEC 원문을 근거로 새 설명을 과거 snapshot에 소급 투입하지 않는다.

읽기 검토 중 Source.published_on이 Source.observed_at보다 미래여도 입력 모델이 허용하는
누락을 부모 세션에 보고했다. 부모 통합에서 source 공개일≤관측일 검증과 회귀를 추가했다.
재import가 새 승인 주석을 만들어 기존 세대를 무효화하는 문제도 별도 독립 검토에서 발견했다.
동일 문단에 이미 주석이 있으면 기존 승인·거절·제안 상태를 보존하는 원자적 initial-only 적재로 수정했다.
후속 검토에서 전체 corpus hash 때문에 무관한 문단 수정도 모든 revision을 바꾸어 거절 문단을 다시
승인하는 문제를 재현했다. 문단별 내용·basis·태그 fingerprint로 기존 revision/작성 시각을 재사용하고,
패키지 provenance는 관측 기록에 분리했다. 실제 내용·태그가 바뀐 기존 문단은 proposed로 저장해
별도 검수를 요구한다. 이전 corpus 형식도 최초 annotation에서 fingerprint를 복원해 거절을 보존한다.
거절/제안·동시 재관측·중단 후 재실행·legacy·검색 회귀는 **40 passed, 17.31초**였다.

knowledge 문서의 URL은 basis 원문이고 텍스트는 자체 설명이므로 동일 원문이라고 해석하면 안 된다.
metadata의 `authorship=original_Korean_paraphrase_not_source_quote`와 `basis_section`,
`source_locator=authored-note:...`가 구분 근거다. 현재 출력은 비공개 배경뿐이며 공개 [E#]에 넣지 않는다.

## 실제 검색 평가

`tests/test_rag_editorial_evaluation.py`는 실제 `import_corpus → RagStore → GenerationIndex →
Retriever → load_context`를 실행한다. 모델·시장 공급자 호출은 없다.
저장된 review 시각 1초 뒤 관측을 테스트 시각으로 잡고 `reconstructed-v1`을 명시했다.
당시 운영 세대가 실제 존재했다는 주장이 아니다.

직접 개념 6개(PER/영업이익률/변동성/실적 기대/공시 시각/모멘텀)를 각 설명의 정답으로 미리 지정했다.
negative는 같은 무관한 개념(`광합성 식물세포`)을 common/short 경로별로 따로 측정했다.
현재 Retriever 입력은 Snapshot 개념 라벨이므로 자연어 사용자 질문 API 평가가 아니다.

| 지표 | 결과 |
|---|---:|
| positive 개념 | 6 |
| candidate Recall@20 / MRR@20 | 1.0 / 1.0 |
| 선택 묶음 recall | 1.0 |
| common negative 반환 | 0문단 |
| short negative 반환 | 3문단 |
| 관측 1초 전 검색 | empty |
| Snapshot 변경 / replay 차이 | 없음 / 없음 |
| 실제 모델 비용 / 예측 accuracy | null / null |

source corpus hash: `c6d2dabdab21c4cbb50f5b4cf1a36022396a0b860716bafe6a16cfab22fa294e`.
최초 테스트 **2 passed, 3.14초**, 지표 assertion 추가 후 최종 **2 passed, 3.58초**. 원시 산출물은 ai-worker 아래
`.pytest_cache/rag-editorial-1/test_source_grounded_editorial0/editorial-quality.json`에 있으며 커밋하지 않는다.
짧은 개별 검색에서 monotonic 측정값 0.0도 나왔으므로 이를 실제 실행시간 0으로 해석하지 않는다.

short negative에는 `momentum-limit`, `earnings-expectations`, `release-vs-filing`이 반환됐다.
고정 질의의 `event_relevance`, `거래일`, `코스피`가 항상 매칭되기 때문이다.
엄격한 추가 개념 적합성 기준으로는 negative 2건 중 1건에 배경이 반환된 것이다.
그러나 서비스의 고정 7거래일 금융 판정이라는 전체 질문에는 일반 배경으로 관련될 수 있으므로
이를 운영 오탐률 50%라고 일반화하지 않는다. 현재 검색은 **질의별 개념 검색 + 고정 과제 배경**이라는
성격이 섞여 있고, 추후 개념 적합성과 과제 공통 적합성을 별도로 채점할 필요가 있다.

모든 positive가 corpus 제목·핵심어에서 직접 만든 작은 개발용 질문이다.
1.0은 독립 자연 질문 정답 집합이나 사람의 내용 검수를 대체하지 않는다.
운영 RAG 활성화·예측 성과·실제 LLM 품질의 증거가 아니며 `operational_activation_eligible=false`다.

```powershell
cd ai-worker
python -m pytest -o pythonpath=src tests/test_rag_editorial_evaluation.py -q -s
```

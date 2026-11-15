# 답 없음·문단 선택 개선 평가 — 2026-11-02

**구현은 완료했지만 운영 기본 전환은 보류한다.** 새 정책은 불필요한 문단과 답 없음 오류를 줄였고, 정답 문단 누락이 늘었다. 특히 실제 종목 수치를 묻는 질문을 교육용 개념 문단과 구별하는 능력은 부족하다. 정책은 CLI·HTTP 주 경로·HTTP shadow에서 선택적으로 적용할 수 있으며 기본값은 이전 정책이다. S3는 연결하지 않았다.

## 이전 평가 정정

이전 보고서의 **BM25 답 없음 오류 0/6은 전체 반환 문단 기준이 아니었다.** 해당 질문에 지정된 common/short 경로만 검사하여 다른 경로의 과잉 선택을 놓쳤다. 비교 코드를 수정하고 경로 교차 회귀 테스트를 추가했다. 기존 24개를 다시 계산하면 BM25도 **6/6**이다. dense/hybrid는 이전과 같이 6/6이다. 이전 수치를 전체 응답의 안전성 근거로 사용할 수 없다. 아래 수치는 모두 전체 선택 묶음 기준이다.

## 실험과 고정 절차

- 기존 6문서에 질문을 24개에서 **72개**로 확장했다. 문서 수는 늘리지 않았다. 문서와 gold는 에이전트 작성·검수이며 사람의 독립 검증은 아니다.
- 원래 24개를 development(양성 18/음성 6)로 사용했다. 새 holdout 48개는 단일 개념 24, 복수 개념 6, 무관 질문 6, 없는 금융 개념 6, 없는 종목 수치 6이다.
- 새 질문을 결과 확인 전에 고정하고, development만으로 모델별 최대 cosine distance/최선 후보와의 거리 차이를 44개 조합에서 선택했다. 목적함수는 `(양성 macro F1 + 음성 specificity)/2`이다. 동률은 specificity·불필요 문단 수·recall·더 작은 threshold/band 순서로 결정한다. 조정 시 dense의 선택을 모사하고 최종 비교는 실제 검색 경로를 실행했다.
- small은 distance 0.70/band 0.08, large는 0.65/0.04로 고정했다. BM25 점수 비율 0.5·전체 문단 상한 2는 사전에 정한 값이다. holdout 결과로 재조정하지 않았다.
- 각 모델의 **같은 generation/snapshot/검수 집합**에 기존/개선 BM25·dense·hybrid를 짝 비교했다. 실제 API의 저장된 벡터를 사용했고 모든 검색은 `reconstructed-v1`이다. 과거 운영 시점 가용성을 입증하지 않는다.
- 바뀐 것은 질의 구성과 선택 기준의 묶음이다. 개선 효과를 거리 임계값 하나의 효과로 분리해 주장하지 않는다. 동일 작성자가 만든 holdout이므로 독립 외부 일반화 증거는 아니다.

## Holdout 결과: 기존 → 개선

양성 30개·음성 18개다. 정밀도는 전체 선택 문단의 micro precision, 재현율은 양성 질문별 전체 gold recall의 평균이다. 정밀도를 높이기 위해 모두 비우는 결과가 유리해 보이지 않도록 재현율과 양성 완전 누락도 함께 표시한다.

| 방식 | 정밀도 | 재현율 | 답 없음 오류 /18 | 불필요 문단 합계 | 양성 완전 누락 /30 |
|---|---:|---:|---:|---:|---:|
| BM25 | 19.1% → 66.7% | 93.3% → 90.0% | 18 → 9 | 140 → 16 | 0 → 1 |
| small dense | 18.2% → 53.4% | 98.3% → 88.3% | 18 → 10 | 157 → 27 | 0 → 1 |
| small hybrid | 18.2% → 55.2% | 98.3% → 90.0% | 18 → 10 | 157 → 26 | 0 → 1 |
| large dense | 18.8% → 68.9% | 100% → 90.0% | 18 → 8 | 156 → 14 | 0 → 0 |
| large hybrid | 18.2% → 68.9% | 98.3% → 90.0% | 18 → 8 | 157 → 14 | 0 → 0 |

검색 실패와 금지 문단 선택은 모든 조건에서 0이다. 이는 답 없음 품질 통과를 뜻하지 않는다. LLM 최종 답변 정확도는 이번 실험에서 측정하지 않았다.

개선 후 음성 유형별 오류는 다음과 같다.

| 방식 | 무관 질문 /6 | 없는 금융 개념 /6 | 없는 종목 수치 /6 |
|---|---:|---:|---:|
| BM25 | 1 | 3 | 5 |
| small dense/hybrid | 0 | 5 | 5 |
| large dense/hybrid | 0 | 3 | 5 |

관련 없는 분야는 대부분 거절했지만, 예를 들어 특정 종목의 실제 PER을 묻는 질문에 PER 정의 문단을 선택하는 문제는 남아 있다. `supported_background`는 관련 배경 문단이 선택되었다는 상태이며 질문의 사실 답을 문단이 보장한다는 뜻이 아니다. 전체 상한 2문단 때문에 복수 개념/많은 Fact가 있는 실제 snapshot에서 필요한 문단이 누락될 수도 있다. 이번 개념 probe를 실제 다종목 트래픽 품질로 일반화하지 않는다.

## 비용과 재현 자료

기존 문서·legacy 질의 cache를 재사용했다. 모델별 신규 120회·4,577토큰, small **$0.00009154**, large **$0.00059501**, 합계 **$0.00068655**다. 공급자 usage×기존에 검증한 설정 단가의 계산값이며 청구서 대사는 아니다. 전체 계획 상한 $0.00242745, 예산 $0.05 이내였다. 과거 unknown 예약 $0.00000524 1건은 그대로 보존됐고 이번 실행에서 새 unknown은 없었다.

- [요약·누적 비용 원장](selection-quality-v2/summary.json)
- [고정 snapshot/gold/split](selection-quality-v2/cases.json), [입력 해시](selection-quality-v2/state.json)
- [small calibration](selection-quality-v2/text-embedding-3-small-calibration.json), [고정 정책](selection-quality-v2/text-embedding-3-small-policy.json)
- [large calibration](selection-quality-v2/text-embedding-3-large-calibration.json), [고정 정책](selection-quality-v2/text-embedding-3-large-policy.json)
- [small 기존 holdout](selection-quality-v2/text-embedding-3-small-holdout-legacy.json), [개선 holdout](selection-quality-v2/text-embedding-3-small-holdout-selective.json)
- [large 기존 holdout](selection-quality-v2/text-embedding-3-large-holdout-legacy.json), [개선 holdout](selection-quality-v2/text-embedding-3-large-holdout-selective.json)

보고서 원장은 이전 평가와 합친 누적값이다. 신규 비용은 이전 원장과 차이를 계산했다. 생성된 context/벡터는 전용 로컬 PostgreSQL, 원문/generation은 로컬 archive에 보존했다. JSON만으로 공급자 응답 벡터가 복원되지는 않는다. 실험 후 선택 결과를 바꾸지 않고 micro precision·양성 누락 집계 필드만 기존 고정 결과에서 추가 계산했다.

## 판단과 다음 검증

이 집합에서는 개선 BM25가 small 벡터보다 정밀도가 높았으며 large가 조금 더 좋았다. 표본이 작고 같은 6문서에 의존하므로 large 채택 근거로는 부족하다. 새 정책은 우선 shadow 관측 대상으로 두는 것이 타당하다. 다음에는 개념 설명과 실제 수치 요구를 구분하고, 답에 필요한 Fact/시점/단위가 있는지 확인하는 검증을 추가해야 한다. 사람 검수 자료와 더 큰 corpus로 검증하되, 이번 holdout은 후속 조정용으로 사용한 순간 새 holdout을 따로 확보해야 한다.

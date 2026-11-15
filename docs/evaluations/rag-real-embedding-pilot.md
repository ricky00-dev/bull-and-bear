# 실제 임베딩 모델 소규모 평가 — 2026-11-02

**후속 정정:** 아래 BM25의 `0/6`은 당시 지정된 한 경로의 선택만 검사한 값이다. 전체 반환 문단을 검사하도록 평가 코드를 수정해 같은 24개를 재측정한 결과 BM25도 **6/6**이었다. 아래 표는 당시 경로별 기록으로 보존하며, 전체 문맥의 답 없음 판정에는 [후속 평가](rag-selection-pilot.md)를 사용한다.

결론: **BM25를 기본 경로로 유지한다.** 실제 OpenAI 임베딩은 이 작은 집합의 정답 재현율을 높였으나, 근거가 없는 질문에도 문서를 반환했다. 운영 전환의 품질 조건을 충족하지 못했다. HTTP shadow만 선택적으로 사용할 수 있도록 구현했다.

## 자료와 재현성

- 문서: `ai-worker/knowledge/common-short-v1.json`의 6개 교육 문단. AI 작성·에이전트 검수이며 사람 검수는 아니다.
- 질문: 실행 전에 고정한 `ai-worker/knowledge/embedding-evaluation-v1.json`의 24개. 직접 표현 6, 바꿔 쓴 표현 12, 정답 없음 6이다. 질문·정답도 에이전트 작성으로 독립 평가셋이 아니다.
- 동일 generation/snapshot/정답에 BM25, cosine dense, RRF hybrid를 적용했다. common k=2/short k=3의 해당 경로 점수를 집계한다. 정답 없는 6개는 Recall/MRR/nDCG 평균에서 제외하고 별도 오류로 집계한다.
- [전체 요약·원장](embedding-quality-v1/summary.json), [small 개별 결과](embedding-quality-v1/text-embedding-3-small.json), [large 개별 결과](embedding-quality-v1/text-embedding-3-large.json), [고정 snapshot·정답](embedding-quality-v1/cases.json)에 입력 해시·버전·context ID를 남겼다. 개별 결과에는 전체 선택 묶음의 정밀도/불필요 문단 수도 포함한다.
- 모델은 실제 API 호출을 사용했다. 공급자가 고정 weight snapshot을 보장한다고 주장하지 않으며 application revision과 실제 응답 벡터 cache로 재현한다. 결과 JSON만으로 벡터가 재현되지는 않는다. 로컬 전용 pilot PostgreSQL과 archive/cache를 함께 보존했다.
- 평가 시점 뒤에 색인을 만든 오프라인 실험이므로 `reconstructed-v1`이다. 과거에 실제 서비스 가능한 상태였다는 증거가 아니다. HTTP shadow는 `observed-v1`만 허용한다.

## 결과

| 방식 | Recall | MRR | nDCG | 근거 없는 질문에 문서 반환 |
|---|---:|---:|---:|---:|
| BM25 | 0.8333 | 0.7778 | 0.7923 | 0 / 6 |
| small dense | 1.0000 | 0.8611 | 0.8975 | 6 / 6 |
| small hybrid | 0.9444 | 0.8611 | 0.8829 | 6 / 6 |
| large dense | 1.0000 | 0.9167 | 0.9385 | 6 / 6 |
| large hybrid | 1.0000 | 0.9167 | 0.9385 | 6 / 6 |

모든 검색 실행 오류와 금지 문단 선택 수는 0이다. 이는 품질 통과와 다르다. dense는 정답 존재 여부와 무관하게 가까운 문단을 반환하며 현재 hybrid도 이를 차단하지 않는다. 이 결과만 보고 large가 장기 운영에 더 적합하다고 판단할 수 없다. 여기서 '답변 반환'은 검색 문단 선택이며 LLM 최종 답변의 정확성을 평가한 것은 아니다.

전체 선택 묶음의 비어 있지 않은 결과별 정밀도 평균은 BM25 0.1771, small dense 0.1875/hybrid 0.1771, large dense/hybrid 0.1875다. 질문별 gold를 전체 묶음에 적용했을 때 불필요한 고유 문단 선택 합계는 각각 68/78/79/78/78개다. BM25도 문맥을 정밀하게 고른다고 보기 어렵다. 경로별 Recall만으로 이 과잉 선택을 숨기지 않는다. 이 판정 역시 에이전트 작성 gold에 의존한다.

캐시 준비 후 검색·context 저장 p95는 BM25 약 44~47ms, dense 약 127~140ms, hybrid 약 137~235ms였다. 24회 로컬 시험이며 API 지연·색인 구축을 제외한다. 운영 지연 수치로 사용하지 않는다.

## 비용

[small 공식 모델 페이지](https://developers.openai.com/api/docs/models/text-embedding-3-small)와 [large 공식 모델 페이지](https://developers.openai.com/api/docs/models/text-embedding-3-large)를 2026-11-02 확인했다. 각각 입력 100만 토큰당 $0.02/$0.13을 명시적으로 spec에 기록했다. small 1536차원, large 3072차원을 사용했다.

각 모델은 문서 6회+질문 24회, 입력 1,830토큰이었다. 공급자 usage×설정 단가로 계산한 비용은 small **$0.0000366**, large **$0.0002379**, 합계 **$0.0002745**다. 청구서 대조 결과는 아니다. 실행 전체 예산은 $0.05, 두 모델의 보수적 사전 상한은 $0.00068925였다.

첫 시도는 프로세스에 상속된 키 문제로 실패했다. 프로젝트에 저장된 키가 정상임을 별도 확인한 뒤 새 application revision으로 수동 재개했다. 최초 호출의 usage는 확정하지 못했으므로 **$0.00000524 예약 1건을 unknown으로 보존**했다. 키/.env는 복사하거나 변경하지 않았다. 실패 예약을 삭제하거나 자동 재시도하지 않았다.

## 다음 품질 조건

사람이 검수한 다종목·실제 문서 집합을 확장하고 평가용 holdout을 분리한다. 답 없음 판정·유사도 기준 또는 reranker를 학습/조정한 뒤 별도 holdout에서 과잉 검색과 재현율을 함께 평가해야 한다. 현재 24개 질문에 맞춰 임계값을 최적화하지 않았다. S3와 운영 트래픽 활성화는 이번 범위에 포함하지 않았다.

# RAG 평가 해석 후속 조사

2026-10-30. 실제 모델 반려와 검색 지표를 해석하면서 생긴 두 질문을 공식 논문·GitHub·문서로 확인했다.
검색 구현의 SQLite/BM25 조사는 [기존 조사](worker-rag-retrieval-research.md), 모델 단가는
[예산 조사](worker-model-budget.md), 금융 설명의 출처 검토는 [corpus 검토](worker-rag-editorial-quality.md)에 있다.

## LLM 검토의 반려를 정답 오류 개수로 셀 수 있는가

[Zheng 외, Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena, NeurIPS 2023](https://arxiv.org/abs/2306.05685)
원 논문 페이지의 초록·버전 정보를 확인했다. 논문은 LLM 평가자의 위치·장황함·자기 선호 편향과
추론 능력의 한계를 조사한다. 일부 강한 모델에서 인간 선호와 높은 일치를 보였다는 결과는
특정 벤치마크의 결과이며 이번 mini 금융 추론 검토의 정확도가 아니다.

이번 코드에 대한 적용 판단: `unsupported_inference` 등의 반려 건수는 **검토기 출력 통계**로
기록한다. 사람 또는 독립 검토자가 Fact·조건부 주장·기간·계산을 대조하지 않은 상태에서 이를
실제 개념 오류율로 승격하지 않는다. 실제 파일럿에서 정책 임계값을 근거 없는 숫자로 경고하거나,
조건부 주장에 조건 발생확률 자체를 요구한 사례가 있어 이 구분이 필요했다.
본문 수치 복사 검사, 표현 규칙, 의미 검토, 최종 모델 완료율을 따로 기록했다.
논문만을 근거로 현재 검토기를 정확하다고 선언하거나 반려를 통과로 바꾸지 않았다.

## recall이 높으면 불필요한 배경도 적은가

[Ragas GitHub](https://github.com/vibrantlabsai/ragas)와
[공식 Context Precision 문서](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)
를 열어 지표 정의·예시를 확인했다. 예전 explodinggradients 주소는 현재 위 저장소로 연결된다.
공식 문서의 Context Precision은 관련 문단의 순서를 반영하는 지표다. 생성 답변을 기준으로
관련성을 평가하는 경우와 reference를 사용하는 경우도 구분한다.

이번 `selected_precision`은 명시한 전체 정답 ID와 실제 선택 ID의 집합 비율이며 순위 가중치를
쓰지 않는다. 따라서 이를 Ragas 점수와 같은 이름의 동일 계산이라고 주장하지 않는다.
candidate recall/MRR과 선택 묶음의 불필요 문단 수는 서로 다른 질문에 답한다.

이번 구현 선택: synthetic 평가에서도 정답이 일부만 알려진 `subset`이면 불필요 문단을
판정할 수 없으므로 precision과 불필요 개수는 null이다. `exhaustive` 정답 집합에만 계산한다.
빈 선택은 precision 분모가 없어 null이며 불필요 개수는 0이다. 기존 fixture에는 exhaustive
선언이 없으므로 이 새 지표를 사후에 1.0이라고 채우지 않았다. 별도 회귀에서 정답 1개+불필요
1개를 선택했을 때 recall 1.0, precision 0.5, 불필요 1개를 확인했다.

새 평가 라이브러리나 추가 LLM judge 호출은 도입하지 않았다. 현재의 고정 ID 평가와 실제
실패 대조에 필요한 정의만 정리했으며 P2 위험 검토·LangGraph로 범위를 넓히지 않았다.

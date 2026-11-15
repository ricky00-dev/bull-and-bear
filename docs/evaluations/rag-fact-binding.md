# 질문 의도·Fact 연결 — 오프라인 구현 검증

**이 문서는 이전 v0.7 구현의 기록이다.** 이후 사용자 요청으로 정규식 의도 관문을 제거하고 `/rag/search`·`/rag/facts`로 분리했다. 현재 인터페이스는 [v0.8 계약 초안](../worker-api.md)을 따른다. 아래 의도 분류 성능을 현행 동작으로 해석하지 않는다.

2026-11-02. 외부 LLM/임베딩 호출 **0회**, S3 연결 없음.

자유 질의를 저장된 snapshot에 조회하는 `POST /rag/query`와 `rag retrieve --request`를 추가했다.
새 HTTP 경로는 인증을 요구하고 snapshot을 새로 수집하지 않는다. 기존 `/debates`는 자유 질문을 받지
않으므로 기존 토론 입력을 재해석하지 않았다. Spring/브라우저 연동은 아직 없으며 계약 추가는 v0.7 구현 초안이다.

수치 의도는 해당 종목 snapshot의 명시된 Fact ID로만 연결한다. 값/단위/기준일/출처와 입력 Fact 계보를 검사한다.
기준일 충돌, 다른 종목, 미래/장중 수치, 분기→TTM 대체, missing/None/NaN, 단위 오류,
누락·순환·미래 입력을 거부한다. 개념 문단을 수치 답변으로 대체하지 않는다.
Fact 자체를 knowledge item으로 넣지 않고 별도의 `evidence.facts`와 HTTP facts 배열에 보존한다.
Fact 조회에는 FTS/벡터 색인이 필요 없으며 context/감사 저장 성공은 필요하다.

규칙으로 판별할 수 없는 표현은 근거 부족이다. 모호한 이름을 ticker로 추정하지 않는다.
단일 snapshot이 해당 ticker의 Fact만 포함한다는 기존 수집 계약을 신뢰하며, Fact에 별도 issuer 필드는 없어
공급자 원본의 실제 기업 소속을 재검증하는 기능은 아니다. 파생값의 계보 검사 역시 수식 재계산이 아니다.

## 회귀 평가

[72개 재사용 사례 결과](rag-fact-binding-regression.json)는 기존 SQLite 원문/색인으로 BM25만 실행했다.
이전 holdout은 이번 단계에서 오류 분석에 사용했으므로 **새로운 독립 holdout 결과가 아니다**.
문서6개·사람 검수 전 gold라는 한계도 그대로다.

| 이전 검증용 48개 | 선택 개선만 | 의도/Fact 연결 추가 |
|---|---:|---:|
| 답 없음 문단 오선택 /18 | 9 | 4 |
| 전체 선택 micro precision | 66.7% | 75.0% |
| 양성 질문별 recall | 90.0% | 83.3% |
| 양성 완전 누락 /30 | 1 | 3 |
| 불필요 문단 합계 | 16 | 10 |
| 검색 실행 실패 | 0 | 0 |

개선은 오선택 감소와 누락 증가를 동반한다. 정확한 수치 요구는 Fact가 없어 거절할 수 있지만,
없는 종목 수치6개는 모두 거절했지만, 무관 질문1개·없는 금융 개념3개에 문단이 선택되는 문제는 남았다. 이 재사용 사례만으로 일반적인 수치 질문 실패율0을 주장하지 않는다. 기본 운영 정책을 바꾸지 않았다.
기존 development 24개에서도 recall55.6%/완전 누락7개로 보수적 표현 판별의 한계가 있다.

별도 오프라인 통합 테스트는 실제 값이 있는 snapshot을 넣어 값/단위/시점의 일치와 불일치,
파생 입력 계보, 동일 조회 재생, 인증·404·400, 모델/시장 수집 호출 금지, 실제 FTS 개념 검색을 검사한다.
기존72개는 EVAL.PROBE만 있어 수치 성공률을 평가할 자료가 아니며, 수치 성공 연결은 이 별도 테스트로 검증한다.

## 재현

`ai-worker/` 기준이며 기존 `data/selection-quality-v2` 로컬 archive가 필요하다.

```powershell
uv run python -m bullbear.rag.evidence_evaluation --cases data/selection-quality-v2/cases.json --archive data/selection-quality-v2/archive --generation G.<기존 generation> --output data/fact-binding-regression.json
```

`request.json`은 question/ticker와 선택 as_of/unit을 담는다. CLI는 snapshot JSON을 직접 받으며 HTTP는
동일 스키마에 snapshot_id를 추가해 저장된 snapshot만 사용한다.

```powershell
uv run bullbear rag retrieve snapshot.json --generation G.<세대> --request request.json --selection-policy policy.json
```

수치·거절 분기는 임베딩을 조회하지 않는다. 명시 질의의 dense/hybrid 개념 검색을 CLI에서 선택하면
`question` 문자열 그대로의 query cache가 필요하며 없으면 실패한다. 자동 모델 호출은 없다.
HTTP는 BM25를 사용한다. 상세 요청/응답과 제한은 [worker API 초안](../worker-api.md)을 따른다.

# 유료 호출 없는 실패 진단과 검수 준비

2026-10-30. 사용자가 실제 Claude 호출을 보류하고 나머지 작업 진행을 요청했다.
`python -m bullbear.diagnostics`는 기존 benchmark 조건 폴더의 `report.json`과
`events.jsonl`을 읽어 집계와 사람이 검토할 목록을 만든다. API·환경 파일을 읽지 않는다.

```powershell
cd ai-worker
python -m bullbear.diagnostics <기존 조건 폴더> --output data/offline-diagnostics/<새 폴더>
```

기존 출력 폴더는 덮어쓰지 않는다. 원본 파일 SHA-256과 이벤트 레코드 번호,
후보 해시를 저장해 검토 대상이 달라졌는지 확인한다. 원본 문장·공급자 오류 문자열은
집계/검수 목록에 복사하지 않는다. 원문은 해당 해시의 원본에서 대조한다.
현재 입력은 benchmark arm 형식이며 HTTP audit manifest나 선공 실험 JSON을 직접 받지 않는다.

## 개발용 기록 적용 결과

기존 `comparison-2-v3`의 4조건을 읽기 전용으로 처리했다. OpenAI로 실행됐던 과거 기록이며
이번 작업에서 OpenAI·Claude를 호출하지 않았다. 원본은 worker-rag-retrieval worktree에 있고,
새 산출물은 이번 worktree의 ignored `ai-worker/data/offline-diagnostics/v3/`에 있다.

| 조건 | 후보 시도 | 자동 통과 | 자동 반려 | 의미 검토 기록과 대응하지 않은 후보 |
|---|---:|---:|---:|---:|
| none / single | 3 | 0 | 3 | 1 |
| none / debate | 6 | 1 | 5 | 0 |
| common_short / single | 2 | 1 | 1 | 0 |
| common_short / debate | 3 | 0 | 3 | 0 |

후보 14건(통과 2·반려 12)을 모두 검수 목록에 넣었다. 오류로 분류된 자동 지적은
unsupported_inference 17건, horizon_mismatch 5건, argument_length 1건, concept_error 1건이다.
경고 unbacked_number 7건·unused_evidence 1건은 오류와 별도 집계했다.
같은 후보에 여러 지적이 있을 수 있어 지적 건수와 후보 수는 다르다.
4조건 모두 요청 대비 기록된 응답 누락은 0건이었다. 이것만으로 실패 원인을 확정하지 않는다.

## 사람이 검토할 때

1. 원본 report/events 해시를 확인하고 `event_record`의 후보, 해당 snapshot의 Fact,
   당시 이전 발언·출처·정보 시각을 대조한다. 이벤트 번호는 비어 있지 않은 JSON 레코드의 1-based 순번이다.
2. `semantic_reviews`의 역할과 0-based index로 모델 검토 의견을 확인한다.
   `quote_grounded`는 원문 인용 일치 여부일 뿐 판단의 정답 여부가 아니다.
3. `human_label`, `human_rationale`, `reviewer`를 작성한다. 분류는 후보 오류,
   검토기 오탐, 둘 다, 확인된 오류 없음, 근거 부족 중 하나다. 모델 오류와 검토기 오탐은 공존할 수 있다.
4. 자동 통과 후보도 검사해 검토기의 누락을 찾는다. 현재 목록은 전부 미라벨이며
   자동 지적을 실제 오류율·오탐률의 정답으로 사용하지 않는다.

같은 삼성전자 스냅샷의 재시도는 독립 표본이 아니다. 기존 개발 파일럿으로 만든 목록은
회귀/진단 자료이며 독립 최종 평가셋이 아니다. Claude 품질 개선 효과·예측 성과를 주장할 수 없다.
다음은 별도 스냅샷의 검수된 라벨·가격/정보 시각 정합성 평가와, 키 및 예산 확정 후 Claude 검증이다.

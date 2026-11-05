# 워커 오프라인 품질 평가 세션

> 2026-11-05 변경: 기존 순차 토론 엔진 및 전용 experiment/benchmark/diagnostics/quality_evaluation 실행기는 삭제됐습니다. 아래 관련 명령·측정값은 당시 구현의 이력입니다. 현재 토론은 HTTP 또는 `bullbear debate`의 LangGraph 경로를 사용하며, 단일 분석 HTTP 모드는 유지합니다.

2026-10-31. 기준 커밋 `5d2a8e53ce2f9d0f434a1e8567dbc6290091bda5`, 격리 브랜치
`fix/worker-quality-evaluation`. 작업 폴더는
`C:/Users/이장원/.codex/worktrees/worker-quality/bull-and-bear`다.
사용자가 후속 Claude 구성으로 **토론자 Haiku · 중재자 Sonnet**을 선택했다.
실제 모델 ID/접근 확인과 새 총비용 상한은 아직 없으며 이번 유료 호출은 0회다.

## 구현과 기존 도구의 경계

worker-integration의 미커밋 `diagnostics.py`, 테스트, 오프라인 진단 문서를 먼저 읽었다.
그 도구의 집계/검수 목록 생성을 복제하거나 다른 세션 변경을 이동하지 않았다.
새 `bullbear.quality_evaluation`은 기존 `review-queue.json`을 받아 다음을 수행한다.

- report/events 파일 해시, 비어 있지 않은 이벤트의 1-based 번호, 후보와 case ID 해시,
  저장된 자동 통과 여부를 검증한다. 중복과 누락을 거부해 자동 통과 사례도 보존한다.
- snapshot의 ID와 canonical JSON 해시를 benchmark report와 대조한다.
  검수 annotation은 별도로 snapshot 파일 바이트 해시에 묶는다.
- 미검수(`unreviewed`), 제안(`proposed`), 사람 검수(`human_reviewed`)를 구분한다.
  사람 검수는 reviewer/rationale/human_attested와 candidate/facts/history/review 확인 목록이 필요하다.
  이 필드는 검수자의 명시적 확인 기록이며 사람의 신원을 인증하는 기능은 아니다.
- `candidate_error`, `reviewer_false_positive`, `both`, `no_identified_error`,
  `insufficient_evidence`를 구분한다. 같은 모델의 검토 내용·인용 일치를 정답으로 사용하지 않는다.
- 사람 검수 중 `insufficient_evidence`를 뺀 사례만 분모에 넣는다.
  `candidate_error_fraction`은 candidate_error+both / 확정 검수 사례다.
  `false_rejection_fraction`은 자동 반려됐지만 후보 오류가 확인되지 않은 사례 /
  확정 검수된 자동 반려 사례다. 둘 다 오류인 경우는 잘못된 반려로 세지 않는다.
  이것은 개별 지적의 오탐률이나 모집단 false-positive rate가 아니다.
- 현재 기간 문자열 검사만 오프라인 재실행한다. 결과가 빈 목록이어도 저장된 자동 반려를
  통과로 바꾸지 않는다. 재실행 불가능한 후보는 null로 남긴다. 전체 의미 검토 재실행이 아니다.
- 원문/검토 사유/검수자 이름을 산출물에 복사하지 않는다. 구현·queue·annotation 해시와
  집계, 사례 상태, 빈 annotation 양식만 새 폴더에 저장하며 기존 출력은 덮어쓰지 않는다.

실행 예시(통합 후 ai-worker 폴더, 원본 경로는 로컬에서 지정):

```powershell
python -m bullbear.diagnostics <arm> --output <새-진단-폴더>
python -m bullbear.quality_evaluation <arm> `
  --queue <새-진단-폴더>/review-queue.json `
  --snapshot <고정-snapshot.json> --output <새-품질-폴더>
# annotation-template.json을 별도 파일로 복사해 사람이 검수한 뒤:
python -m bullbear.quality_evaluation <arm> `
  --queue <새-진단-폴더>/review-queue.json --snapshot <고정-snapshot.json> `
  --annotations <검수-파일.json> --output <다른-새-품질-폴더>
```

현재 입력은 benchmark arm이다. HTTP audit 전용 형식은 지원하지 않는다.
후속 HTTP 기록을 연결하려면 snapshot, 실패 후보, 각 역할 history, 검토 원문을 보존하는
변환 규약이 필요하다. 공개 API 변경 없이 별도 비공개 평가 입력으로 설계할 항목이다.

## 사례집과 오탐 수정

`tests/fixtures/quality/horizon-v1.json`: 9개 합성 회귀 사례.
`7 거래일`, `코스피  대비`, `코스피대비`는 띄어쓰기 차이인데 기존 문자열 검사에서 반려됐다.
`semantic.py`의 기간 검사만 공백을 허용하도록 수정했다. 동시에 기존 부분 문자열 검사로
통과하던 `17거래일`, `7.7거래일`은 거부한다. 달력 7일·코스닥·절대수익만 있는 주장도 거부한다.
이 검사는 여전히 문맥의 부정·가정·실제 기간 대체를 판정하지 못하므로 의미 검토가 필요하다.

`tests/fixtures/quality/semantic-proposals-v1.json`: 기존 파일럿 문서의 실패 유형에서 만든
6개 합성 검수 연습 사례이며 저장 원문 인용이 아니다. 모든 라벨은 **제안/사람 미검수**다.

| 사례 | 제안 분류 | 검수할 구분 |
|---|---|---|
| 조건부 기관 순매수 가설을 이미 발생한 사실로 읽음 | 검토기 오탐 | 가정과 관측 사실 |
| Fact 없이 기관 순매수가 발생했다고 단정 | 후보 오류 | 조건부 허용이 사실 날조 허용은 아님 |
| 양의 이익에서 PER 역수 관계를 뒤집음 | 후보 오류 | 산술 정의와 저평가 판단 |
| PER 정의를 잘못 읽은 검토 + 근거 없는 저평가 확정 | 둘 다 | 오탐과 후보 오류의 공존 |
| 변동성 크기에서 하락 확률 우위를 도출 | 후보 오류 | 변동 폭과 방향 확률 |
| history 없이 상대 발언 왜곡 판정 | 근거 부족 | 자료 누락을 오류 없음으로 바꾸지 않음 |

이 제안 fixture는 모델 점수의 정답이나 자동 통과/반려 규칙으로 사용하지 않는다.
의미 검토 프롬프트를 추가 완화할 근거는 확보하지 못했으므로 변경하지 않았다.

## 기존 저장 기록에 적용

worker-rag-retrieval의 `comparison-2-v3` 4조건을 읽기 전용으로 적용했다.
worker-integration의 기존 diagnostics를 파일 경로로 로드해 queue를 만들고 새 CLI로 검증했다.
원본 데이터/.env는 출력·수정·커밋하지 않았다. 출력은 임시 폴더
`C:/Users/이장원/AppData/Local/Temp/bullbear-quality-cxy9kym5/verified`에 있다.

| 조건 | 후보 | 사람 검수 | 기간 문자열 재실행 반려 |
|---|---:|---:|---:|
| none / single | 3 | 0 | 0 |
| none / debate | 6 | 0 | 0 |
| common_short / single | 2 | 0 | 0 |
| common_short / debate | 3 | 0 | 0 |

14개 모두 원본·snapshot 연결 검증을 통과했고 미검수로 유지했다. 두 품질 비율은 모두 null이다.
기간 표기 수정은 이 14개에서 반려를 제거하지 않았다. 과거 모델의 `horizon_mismatch` 지적과
현재 결정론적 기간 표기 검사는 다르다. 과거 의미 검토 오탐이 해결됐다고 주장하지 않는다.
같은 종목·snapshot의 재시도이며 독립 최종 평가셋이나 Claude 품질 평가가 아니다.

## 후속 Claude HTTP 실험표 — 미실행

| 단계 | 고정 조건/진행 조건 | 수집할 증거 |
|---|---|---|
| 사전 점검 | 사용자가 선택한 Haiku 토론자·Sonnet 중재자, 계정에서 실제 모델 ID 확인, 키 존재, 별도 총비용 상한 확정 | 실제 요청 모델과 응답 모델, retry/tool 제한, 예산 예약·미확정 처리 |
| 단일 HTTP smoke | RAG 비활성, frozen snapshot/코드/설정 고정, 먼저 1건 | 요청→완료/실패, 실제 모델별 토큰·비용·지연, 실패 단계, 공개 이벤트와 봉인 |
| 고정 후보 검토 | 성공·실패 후보 모두, 위 합성 사례는 개발용으로 분리, 사전에 사람이 독립 라벨 작성 | 후보 오류/오탐/둘 다/근거 부족, 원문 인용과 Fact/history 대조, 검토기 누락 |
| 반복 비교 | 예산 내 반복 수와 중단 규칙을 실행 전 결정, 순서 균형, 개발에 쓰지 않은 별도 snapshot | 생성 완료율과 검토 품질을 별도 계산, 분모·누락·재시도·실패 포함 |
| 전향 결과 | 별도 담당자의 가격 기준/정보 시각/기업행사 조건 충족 후 3·7거래일 성숙 | 실제 코스피 상대수익; 자동 검증 통과와 구분 |

의미 검토기는 현재 각 역할의 LLM을 재사용한다. 토론자 검토는 Haiku, 중재자 검토는 Sonnet이므로
별도 대화로 검토하더라도 같은 모델의 자기검증 한계를 가진다. 사람 정답과 교차 검토 없이
모델을 바꾼 것만으로 독립 검증으로 부르지 않는다. 월 크레딧/과거 OpenAI 예산은 이번 호출 승인이 아니다.

## 검증·통합

영향 범위 64 passed 후 snapshot 연결 검증과 테스트를 추가했다.
최종 전체 Python: **414 passed, 2 skipped (43.37초)**. git diff 공백 검사 통과.
기존 주 작업 폴더의 Python 가상환경 실행기를 읽기 전용으로 사용하고 `PYTHONPATH`는
이 격리 폴더의 `ai-worker/src`로 지정했다. 가상환경/의존성/원본 소스 변경 없음.
외부 Spring/실제 Claude/시장 공급자 검증은 이번 세션에서 실행하지 않았다.
session-brief는 저장소의 CRLF 때문에 실행 실패했고 WORKLOG/ROADMAP/develop 로그를 직접 확인했다.

변경 파일: `quality_evaluation.py`, `semantic.py`, `test_quality_evaluation.py`,
`tests/fixtures/quality/`의 JSON 2개, 이 문서, `docs/WORKLOG.md`.
server/data/snapshot/config/budget, 공개 계약, 배포, RAG 기본값은 수정하지 않았다.

통합 순서:
1. worker-integration 담당자가 기존 미커밋 diagnostics 모듈/테스트/기록을 먼저 검토·통합한다.
2. 이 세션의 새 평가 모듈·fixture·테스트와 semantic.py의 기간 검사 변경을 반영한다.
   WORKLOG는 다른 세션 항목을 덮지 않고 이 항목만 추가한다.
3. 전체 Python 회귀와 기존 4조건 해시 재검증 후 사람이 annotation을 작성한다.
4. 선택한 모델의 실제 접근과 새 비용 상한이 준비되면 별도 HTTP 실험을 시작한다.

범위 밖 제안: HTTP audit→평가 입력 변환, 독립 사람이 검수한 별도 종목/시점 평가셋.
해당 구현·사람 검수·실모델 효과 측정은 미완료다. push/merge·배포·전향 스케줄 활성화 없음.

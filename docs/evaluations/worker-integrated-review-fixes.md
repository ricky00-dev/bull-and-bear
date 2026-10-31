# 독립 검토 P1/P2 수정 및 통합 재검증

2026-11-01 KST. 기준 `a645226`(제품 소스 `27f6161`), 수정 코드
**`71af77bd5c0ae57ea384325496199f3ad1e6cf97`**, 브랜치 `fix/worker-integrated-validation`.
검토 원본은 worker-quality 폴더의 `docs/evaluations/worker-integrated-independent-review.md`와
`repro_integrated_independent_review.py`를 읽기만 했다. 그 폴더는 변경하지 않았다.

## 수정 전 재현과 이전 검사에서 빠진 범위

기존 전체451/영향115/Spring4 통과는 내부 structured 호출이 성공으로 끝나는 재시도의
사용량 완전성을 검사하지 않았다. Service는 structured 호출의 running/failure 상태만
알았으므로, SDK 파싱 실패를 내부에서 소비하고 재시도에 성공하면 부분 사용량을 확정치로
공개했다. 독립 검토의 지적을 HTTP TestClient 회귀로 옮겨 수정 전 실패를 확인했다.

새 코스피 Fact `MKT.KOSPI_RET_7D`는 price 도구 입력에는 들어갔으나 중재자 표시 검사
prefix 목록에는 없었다. 기존 가격 계산·표시 검사를 각각 통과해도 통합 누락을 잡지 못했다.

- 수정 전 최소 회귀: **5 failed / 2 passed** (4.98초).
  실패는 재시도 성공 시 usage 공개 1개, MKT reasoning/양측 comment/extra_question 검사 4개다.
  정상 완전 usage와 decisive_evidence의 MKT ID+[E#] 정상 인용 대조군은 이미 통과했다.
- 기존 판정 정책·assertion을 완화하지 않았고 위 대조군을 계속 유지했다.

## P1: 요청 관측과 미확정 상태 보존

- LLM은 애플리케이션의 각 SDK stream 시도에 단조 증가 request_id를 붙인다.
  실제 stream 진입 전에 감사의 running 요청 기록을 저장한다. 기록 저장 실패 시 SDK를 호출하지 않는다.
- 스트림/최종 응답 사용량을 회수하기 전에 예외가 발생하면 요청을 unknown으로 기록하고,
  LLM의 usage_complete=false를 유지한다. 내부 재시도 또는 다음 structured 호출 성공으로
  이 값을 다시 true로 만들지 않는다. 예외 원문 대신 종류만 기록한다.
- AuditedLLM은 각 요청의 running/unknown/received와 시각을 해당 structured 호출 아래
  requests 목록에 저장한다. 회수한 사용량은 즉시 감사의 전체·역할별 합계에 보존하며,
  structured 호출 종료 시 중복 합산하지 않는다. 기존 관측 hook 없는 fixture와의 호환도 유지한다.
- LiveRunner가 클라이언트의 완전성 상태를 Service에 전달한다. 미확정이면 기존처럼 공개
  usage를 생략하고 알려진 부분 합계는 감사에 보존한다. 정상 완전 사용량은 계속 공개한다.
- 회귀에서는 첫 stream 실패→재시도 성공→다음 structured 호출 성공을 확인한다.
  structured 2건 모두 success여도 requests는 unknown/received/received, 알려진 입력20/출력10,
  usage_complete=false이며 HTTP detail와 SSE에는 usage가 없다. 정상 대조군은 입력20/출력10을 공개한다.
- 감사 완료 후 SQLite 종료 이벤트 커밋 전 중단된 경계를 합성 DB 상태로 재현해 Store를
  다시 열었다. 원본 manifest 바이트, 알려진 합계와 미확정 복구 상태가 보존되고 공개 실패에
  usage가 없는지 확인했다. 기존 실제 프로세스 강제 종료/Spring 재구독 E2E도 다시 통과했다.

이 요청 기록은 애플리케이션의 SDK stream 시도 관측이다. SDK 내부 전송 계층의 자동 재시도
횟수·공급자 청구 내역을 모두 관측하는 원장은 아니며 정확한 청구액이나 지출 상한을 보장하지 않는다.
기존 미확정분을 0으로 바꾸지 않기 위한 보수적 정보 보존이며 예약·단가·계약 정책은 그대로다.

## P2: 기존 내부 ID 표시 정책 적용

presentation.py의 기존 내부 근거 이름 차단 목록에 MKT만 추가했다.
reasoning/양측 comment/extra_question에서 내부 이름을 금지하며,
decisive_evidence의 ID와 본문의 [E1] 등 정상 번호 인용은 계속 허용한다.
이 변경은 새 의미 판단 기준이나 판정 봉인 규칙을 도입하지 않는다.

## 검증 결과

| 검사 | 통과 | 실패 | 생략 | 비고 |
|---|---:|---:|---:|---|
| 최초 수정 후 영향 회귀 | 46 | 0 | 0 | 6.79초, retry/audit/presentation/HTTP LLM |
| 추가 저장 경계 회귀 포함 전체 Python | 460 | 0 | 4 | 45.80초, 외부 Spring 조건 미설정 4개 생략 |
| 실제 Spring/PostgreSQL fixture | 4 | 0 | 0 | 16.04초, 성공 봉인/공개/재사용/채점2 + 미확정 실패/강제 종료 복구2 |

전체 Python 증거: ignored `ai-worker/data/integrated-validation/python-review-fixes.xml`.
E2E 증거: ignored `ai-worker/data/spring-integration/run-76367bb77aff40caba7c1b3e51d36156/`.
result.json은 passed, processes_alive_after_cleanup=[]다. 재시작 프로세스 종료 후 관련
53707/53708/53709 포트의 LISTEN 없음도 확인했다. git diff --check 통과.
Java 제품/테스트 소스 변경이 없어 기존 검증된 bootJar로 실행했으며 Java 단위를 이유 없이 반복하지 않았다.

## 한계와 다음 작업

이 두 재현 결함은 수정 완료다. 새 테스트로 모든 공급자 오류나 표시 누락이 없음을 증명하지는 않는다.
실제 유료/외부 공급자 호출은 0회이며 모든 새 검증은 합성 client/시장/시계다.
키·실제 모델 접근·별도 총비용 상한·사람 검수·시장 관측/기업행사 정책은 여전히 후속 조건이다.
SDK 내부 전송 재시도까지 포함한 청구 대조는 미검증이다. 공통 예산 예약·가격표·공개 worker-api
계약·기본 RAG=false는 바꾸지 않았다. HTTP single/v0.6 구현도 이번 범위가 아니다.
원본 검토 폴더·기존 데이터·환경파일 보존, 로컬 커밋만 수행, push·배포·원격 병합 없음.
판정 기준 변경이나 불명확한 반복 실패가 필요하지 않아 사용자 판단 대기로 중지한 작업은 없다.

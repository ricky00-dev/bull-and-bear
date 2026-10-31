# 워커 HTTP 안정화 세션

2026-10-31. 기준 커밋 `5d2a8e53ce2f9d0f434a1e8567dbc6290091bda5`에서
이 채팅 전용 `worker-http-stability/bull-and-bear` worktree를 만들었다.
원본 작업 폴더와 다른 세션 worktree는 편집하지 않았다. 기존 integration 폴더의
오프라인 진단 문서·소스는 읽기 전용으로 확인했으며 그림과 staged 변경도 보존했다.
`session-brief.sh`는 기존 CRLF 때문에 실패하여 Git·WORKLOG·계약·로드맵을 직접 확인했다.

## 수정과 재현

- executor 제출이 거부되면 이미 저장된 토론이 영구 running으로 남았다. 실패 이벤트로
  종료하여 같은 request_id의 멱등성을 유지하고 새 요청에 동시 실행 슬롯을 돌려준다.
- SQLite 정수 범위를 넘는 Last-Event-ID가 스트림 내부 오류를 일으켰다. 0부터 signed
  64-bit 최댓값까지 요청 단계에서 검증하며 범위 밖은 기존 INVALID_REQUEST/400으로 응답한다.
- 상세 조회가 running 행을 읽은 직후 종료 이벤트를 읽으면 판정과 running 상태가 함께
  반환될 수 있었다. 종료 이벤트를 읽었으면 그 이벤트와 일치하는 최종 상태를 반환한다.
- 사용량 수집 예외를 빈 목록 또는 부분 사용량으로 반환하여 Spring이 비용 0 또는
  부분 비용을 확정할 수 있었다. 불완전 사용량은 공개 응답에서 생략하며 비공개 감사에
  이미 확인한 사용량과 usage_complete=false를 보존한다. 기존 계약의 usage 누락 시
  추정치 경로를 사용하고 공개 필드나 worker-api 문서는 변경하지 않았다.
- 감사의 running/failure 모델 호출은 사용량 미확정으로 다룬다. 하나의 structured 호출은
  도구 후속 요청을 포함할 수 있어 실패 시 비어 있지 않은 delta도 전체 결제액의 증거가 아니다.
  따라서 이 경우에도 부분 사용량을 확정 총량으로 보내지 않는다.
- 재시작은 기존처럼 실행 중 토론을 실패 종료한다. 새 비공개 SQLite `recoveries` 테이블에
  복구 시각·known_usage·unfinished_call_ids·usage_complete=false를 남긴다. 원본 manifest는
  수정하지 않으며 감사 파일 누락·손상도 복구를 막지 않는다. 공개 실패 이벤트에는 불확실한
  usage를 넣지 않고 모델 재실행도 하지 않는다. 복구 기록과 종료 이벤트는 함께 커밋한다.

인증에서는 결함을 발견하지 않았다. 빈 값·틀린 값·접두사·후행 공백 토큰이 POST/SSE에
접근하지 못하고 토론도 생성하지 않는 회귀를 추가했다. 기존 동시 멱등성·용량 제한·SSE
순번 재생·재연결·비공개 이벤트 필터·실패 종료 검증을 유지했다.

## 검증

- 수정 전 기존 server/audit: 26 passed (10.52초).
- 새 핵심 회귀 6개를 수정 전에 실행하여 모두 실패하는 것을 확인했다.
- 전체 Python: 399 passed, 외부 Spring 2 skipped (49.42초).
- 위 전체 실행 뒤 실제 하위 프로세스 `os._exit(23)` 강제 종료 회귀 추가:
  1 passed (10.74초). 소유 잠금 해제, 원래 이벤트 보존, 재시작 두 번에도 종료 이벤트 1개 검증.
- 마지막 부분 사용량이 있는 실패 호출까지 보수적으로 처리한 뒤 HTTP/audit/RAG HTTP 회귀:
  65 passed (19.69초). 전체 실행 수와 후속 실행 수를 합산하지 않는다.
- `scripts/test-worker-spring.ps1`: Java HttpWorkerClientTest 2개, ScoreRuleTest 5개 및 bootJar 통과.
  실제 임시 PostgreSQL/Flyway/Spring/HTTP 통합 2 passed (5.40초).
  판정 전 봉인·판정 후 공개·SSE·당일 재사용·3/7거래일 채점을 확인했다.
  시장·모델·시간은 synthetic fixture이며 RAG는 이 통합 fixture에서만 활성화했다.
- 통합 산출물은 ignored `ai-worker/data/spring-integration/run-c0d3ddeac1ea42e8b5094f24736a2e2b/`.
  `result.json`의 status=passed, processes_alive_after_cleanup=[] 확인.
- Python은 기존 프로젝트의 Python 3.12 venv 실행 파일을 읽기 전용으로 사용하고 PYTHONPATH를
  이 worktree의 src로 지정했다. 설치·환경 파일 복사·원본 데이터 변경은 하지 않았다.

## 변경 파일과 통합 순서

1. 같은 기준 커밋 위에 `ai-worker/src/bullbear/server/{app,service,store}.py`와
   `ai-worker/tests/{test_server,test_run_audit}.py` 변경을 함께 적용한다.
2. `test_run_audit.py`는 HTTP 사용량 누락 기대값 1곳만 수정했다. 타 감사 작업과 통합할 때
   빈 목록을 기대하던 예전 assertion이 되살아나지 않도록 확인한다.
3. 다른 목표의 공통 config/budget/LLM 변경을 반영한 뒤 server/audit/RAG HTTP 회귀와
   Spring fixture 통합을 다시 실행한다. 이 변경은 공통 config·budget·market·토론 엔진에
   의존하는 새 인터페이스를 추가하지 않는다.
4. 이 문서와 WORKLOG 항목을 통합한다. 로컬 런타임·DB·산출물은 포함하지 않는다.

## 남은 검증과 범위 밖 제안

- 실제 Claude·외부 데이터 호출·유료 호출은 0회. 모델 접근 권한, 키, 별도 승인 총비용
  상한이 있어야 유료 경로를 검증할 수 있다. RAG 기본 비활성, 배포·전향 운용 비활성 유지.
- Spring의 usage 누락 처리는 소스에서 확인했다: LlmUsage.parse는 Optional.empty를 반환하고,
  DebateRepositories.costOn은 비용 null에 estimate(현재 설정 $0.15)를 적용한다.
  이번 Spring E2E는 성공 fixture 경로이며 재시작 미확정 비용의 PostgreSQL 정산 E2E까지
  수행한 것은 아니다.
- 고정 추정치는 실제 지출 상한이 아니다. 범위 밖 후속 제안: 공통 예산 담당은 호출 전
  예약과 재시작 미확정 예약 유지, 알려진 부분 비용과 미확정분의 대조·해제 절차를 구현한다.
  Spring 담당은 필요하면 비공개 대조 절차를 마련한다. 공개 계약 변경은 양쪽 승인 후 별도 진행한다.
- SQLite 자체가 쓰기 불가능한 장애에서 종료 이벤트 영속화까지 보장하지 않는다.
  복구 기록은 청구액 확정 또는 토론 재개 체크포인트가 아니다.
- 커밋·push·merge·배포·다른 채팅 메시지 전송 없음.

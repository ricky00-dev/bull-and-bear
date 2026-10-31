# PR #23 단일 실행 비용·복구 수정

2026-11-01. 기준 `d431ce2`, 격리 브랜치 `fix/single-mode-recovery`.
작업 폴더 `C:/Users/이장원/.codex/worktrees/single-mode-recovery/bull-and-bear`.
기존 worker-quality 작업과 감독 통합 폴더는 변경하지 않았다.

## 변경

- V6는 유지하고 V7에서 `single_verdict_attempts`를 추가했다. debate/attempt별 요청키,
  worker_id, 상태, 비용, 최초 실행일을 보존한다. 성적표용 `single_verdicts`는 최신 결과로 유지한다.
- 전향 운용 비용 집계는 시도 원장을 사용한다. 알려진 비용은 합산하고 NULL은 기존 estimateUsd로
  센다. 새 하드 금액 상한이나 별도 예약 정책을 도입하지 않았다.
- 새 시도 생성과 최신 결과 행 변경, worker_id 저장, 종료 결과와 비용 확정은 각각 한 트랜잭션이다.
  비용 원장만 완료되고 결과 행은 RUNNING으로 남는 부분 저장을 방지한다.
- RUNNING도 복구 대상으로 조회한다. worker_id가 있으면 같은 SSE를 구독하며, 없으면 DB에
  먼저 저장한 같은 request_id로 POST를 반복해 응답 유실/ID 저장 전 중단을 복구한다.
- SSE 오류·종료 이벤트 없는 EOF·종료 저장 실패는 RUNNING으로 유지한다. 다음 poll에서
  같은 실행을 재구독하고 attempts를 늘리지 않는다. `debate_failed`를 받은 경우에만 다음
  모델 시도를 허용하며 기존 maxAttempts를 적용한다.
- 이미 기록된 RUNNING 복구는 새 실행 예산 검사를 통과할 필요가 없다. 새 시도만 기존 예산
  검사를 거친다. 복구를 먼저 처리하고, 서비스 인스턴스 하나 안에서는 runDue를 직렬화한다.
- SSE는 0부터 재생한다. 중간 이벤트를 저장하지 않고 최초 terminal 결과만 원자적으로 기록하므로
  새 cursor/worker 계약 변경 없이 복구된다. 재접속은 기존 poll 주기(기본 5분)에 수행한다.
- 성적표의 기간 토글을 빈 상태 분기 밖에 두어 7일 표본0/3일 표본 존재 시에도 3일을 선택할 수 있다.

## V6 이관의 한계

기존 행의 attempts 번호와 그 번호로 만든 요청키, worker_id, 상태, 날짜, 비용을 그대로 옮긴다.
V6에서 이미 덮어써 사라진 이전 시도의 비용은 복구할 수 없다. 이를 임의로 0 또는 새 추정 비용으로
만들지 않는다. 실제 비용 대조가 필요한 기존 데이터는 별도 공급자 기록이 필요하다.
V7 이후의 재시도에서는 각 시도의 확정/미확정 비용과 날짜가 보존된다.

## 검증

JDK17 `bullbear-tools/jdk-17.0.20.1+1`과 독립 임시 PostgreSQL을 사용했다.
Docker나 실제 워커·유료 모델은 사용하지 않았다. 새 테스트마다 UUID schema에서
Flyway V1→V6→V7을 실행하고 테스트 schema를 제거한다. 다른 DB/스키마를 사용하지 않았다.

| 검사 | 결과 |
|---|---|
| SingleVerdictRecoveryTest | 7 통과 / 실패0 / 생략0 |
| 기존 HttpWorkerClientTest | 2 통과 / 실패0 / 생략0 |
| 기존 StartDebateRequestTest | 2 통과 / 실패0 / 생략0 |
| bootJar | 성공 |
| 웹 `npm run build` (tsc 포함) | 성공 |
| 웹 `npm run lint` | 성공 |

총 11개 테스트. 새 회귀는 날짜를 넘는 확정·NULL 비용 보존/실제 DebateQuota 계산,
POST 응답 유실 뒤 같은 키 복구, 새 runner 인스턴스의 같은 worker_id 재구독,
SSE 오류·빈 EOF가 시도를 소진하지 않음, 실제 실패만 maxAttempts 소진,
V6 완료 비용·RUNNING ID 보존, 종료 저장 실패 시 원장/결과 동시 롤백을 확인한다.
worker는 scripted fixture이며 실제 HTTP single 또는 프로세스 강제 종료 E2E를 실행한 것은 아니다.
재시작 검증은 실제 DB를 유지한 채 runner 인스턴스를 교체하는 방식이다.

초기 테스트에서 package-private repository 접근 컴파일 오류를 test 전용 같은 package helper로
수정했다. 이후 Mockito inline agent가 Windows/JDK에서 로딩 실패했고 개별 subclass 설정도
초기 플러그인 로딩을 피하지 못했다. Mockito를 제거하고 Java 표준 Proxy repository·scripted
worker·Clock fixture로 대체했다. 제품 검증 조건을 줄이거나 실패 assertion을 생략하지 않았다.

재현 명령(테스트 전용 PostgreSQL URL을 지정):

```powershell
$env:JAVA_HOME = 'C:/Users/이장원/AppData/Local/bullbear-tools/jdk-17.0.20.1+1'
$env:BULLBEAR_TEST_JDBC_URL = 'jdbc:postgresql://127.0.0.1:<임시포트>/postgres'
# 선택: BULLBEAR_TEST_DB_USER, 기본 postgres. 테스트용 비밀번호 없는 로컬 DB만 사용.
cd api
./gradlew.bat test --tests '*SingleVerdictRecoveryTest' --tests '*StartDebateRequestTest' --tests '*HttpWorkerClientTest' bootJar
```

JDBC URL이 없으면 새 DB 테스트는 명시적으로 생략된다. 이번 실행에서는 실제 URL을 제공해
7개 모두 실행했다. XML 증거는 `api/build/test-results/test/`에 있으며 build는 커밋하지 않는다.
사용한 임시 PostgreSQL은 종료 완료했고 포트55268 LISTEN 없음 확인.
전체 Docker 기반 API 통합 테스트·브라우저 클릭 검증은 미실행이다.

## 통합 안내

제품 변경: SingleVerdictRunner, DebateQuota, V7 migration, ReportPage.
회귀: SingleVerdictRecoveryTest, SingleTestComponents. 문서: 이 보고서와 WORKLOG.
새 worktree의 로컬 커밋을 PR #23 브랜치에 반영한 후 감독이 최종 검증·push·병합한다.
HTTP 계약과 Spring 공개 응답, worker Python, V6, 예산 설정은 변경하지 않았다.
SINGLE_ENABLED 기본 false 유지. 실제 워커 v0.6 지원·양측 계약 승인 없이 활성화하지 않는다.
연결을 영구 복구할 수 없는 작업도 임의 새 실행으로 바꾸지 않으며 RUNNING/미확정으로 남는다.
운영자가 원인을 해결한 뒤 같은 ID로 복구할 항목이다. 다중 서비스 인스턴스 분산 실행은 범위 밖이다.

# 워커 완료 변경 통합 검증

2026-10-31. 로컬 브랜치 `fix/worker-integrated-validation`, 작업 폴더
`C:/Users/이장원/.codex/worktrees/worker-http-stability/bull-and-bear`.
검증한 최종 코드 revision은 **`27f61611fe7dec317e61b9ecb2104917b5eab784`**다.
이 문서와 완료 WORKLOG는 그 뒤 문서 전용 커밋으로 남긴다.

## 출처와 보존

| 출처 | 반영 내용 | 보존/통합 기준 |
|---|---|---|
| 공통 시작점 `5d2a8e53ce2f9d0f434a1e8567dbc6290091bda5` | RAG·Claude 정책·운영 준비 | 세 목표의 공통 기준 |
| HTTP 전용 작업 | 인증 회귀·SSE·실패 종료·재시작·사용량 미확정 처리 | 먼저 `4b27d93`으로 보존 |
| worker-integration `9176afc` | `0f9f295` 진단 도구·README 그림, `7e48f7c` 일정 변경, PR 등록 기록 | `70021d1` 로컬 merge, WORKLOG 양쪽 보존 |
| worker-quality `fix/worker-quality-evaluation` | quality_evaluation, semantic 공백 검사, 합성 fixture·테스트·보고서 | 기준 5d2a8e5의 완료된 미커밋 파일 6개만 읽어 반영 |
| worker-data-consistency `fix/worker-data-consistency` | KRX 캐시, snapshot, market, 테스트·보고서 | 기준 5d2a8e5의 완료된 미커밋 파일 6개만 읽어 반영 |
| 본 통합 작업 | 실제 Spring 미확정 사용량/재시작 fixture, JDBC 조회 도구, 검증 실행기 확장 | 위 두 목표와 함께 `27f6161`에 보존 |

다른 작업 폴더는 checkout·편집·stage·commit하지 않았다. 가져온 12개 파일의 원본 SHA-256을
ignored `ai-worker/data/integrated-validation/source-hashes.json`에 기록하고 통합 완료 시
원본 해시 불변을 다시 확인했다. `test_server.py`의 지수 fixture 보완 4줄과 HTTP 테스트를
모두 유지했다. 각 목표 WORKLOG의 새 항목만 가져왔고 기존 내용을 덮지 않았다.
worker-integration의 추가 미커밋 계약 검토 WORKLOG는 읽기만 했으며 임의로 가져오지 않았다.
원본 환경 파일·API 키·시장/실험 데이터·로컬 런타임은 복사하거나 커밋하지 않았다.

## 결과

| 검사 | 통과 | 실패 | 생략 | 범위/시점 |
|---|---:|---:|---:|---|
| 통합 후 전체 Python | 451 | 0 | 2 | 45.91초. 마지막 Spring 복구 fixture 추가 전; 외부 Spring 실행 조건 미설정으로 2개 생략 |
| 최종 영향 범위 Python | 115 | 0 | 2 | 19.35초. server/audit/RAG HTTP/data consistency/quality/diagnostics 및 새 복구 테스트; 복구 2개는 standalone 환경에서 생략 |
| 실제 Spring/PostgreSQL/HTTP | 4 | 0 | 0 | 13.61초. 성공 시나리오 2 + 미확정 실패/강제 종료 복구 2 |
| Java 관련 테스트 | 7 | 0 | 0 | HttpWorkerClient 2 + ScoreRule 5. 코드 변경 없는 Gradle UP-TO-DATE 결과 재사용, bootJar도 성공 |
| 기존 4조건 품질 입력 재검증 | 14 후보 | 0 | 0 | 원본 report/events/snapshot 해시 연결, 원본 파일 불변, 사람 미검수 유지 |

전체 실행과 최종 영향 범위 실행을 더해 전체 테스트 수로 표시하지 않는다. 최종 변경은
테스트 fixture·실행기뿐이며 제품 소스는 전체 451개 실행 때와 같다. 마지막 fixture 변경은
실제 4개 E2E와 영향 범위 115개로 확인했다. Java의 Docker 필요 전체 통합 테스트를
새로 실행한 것은 아니며 임시 PostgreSQL/Flyway와 실제 Spring bootJar E2E를 사용했다.

Spring 첫 확장 실행은 **2 통과 / 2 실패**였다. 로컬 PostgreSQL 배포본에 psql.exe가 없어
DB 조회 보조 도구 시작에 실패했다. 정확성 기준을 낮추지 않고 기존 Gradle 캐시의 PostgreSQL
JDBC 드라이버와 `scripts/FixtureSql.java`의 읽기 전용 SELECT로 바꾸어 위 최종 4개를 통과했다.
기존 성공 경로·생략 조건·사용량 assertion을 완화하지 않았다. 이 환경 문제는 해결 완료다.

## 새로 닫은 검증 공백

1. 정상 토론 2종목: 실제 HTTP 연결, RAG 비공개, 판정 전 봉인/공개 거부,
   판정 후 공개, 당일 재사용, SSE, 3·7거래일 채점 예약·성숙 시 계산을 확인했다.
2. 미확정 호출 실패: fixture는 모델을 만들지 않고 이전 사용량 123/7 토큰과 미완료 호출을
   감사에 저장한 뒤 실패한다. HTTP 실패 이벤트에 usage가 없고 Spring DB의 cost_usd와
   input/output_tokens가 NULL이며 coalesce(cost_usd, 0.15)=0.15임을 직접 조회했다.
3. 실제 프로세스 강제 종료: fixture가 저장 완료 후 os._exit(23)으로 종료한다. 같은 SQLite를
   사용하는 워커 프로세스를 다시 띄우면 Spring이 SSE를 재구독해 실패 이벤트를 저장한다.
   DB 실패 이벤트는 1개, 비용/토큰은 NULL, 추정치 $0.15이며 원본 감사 바이트는 불변이다.
   recoveries의 known_usage와 미완료 call_id=1, usage_complete=false도 확인했다.
4. 실패한 두 토론의 브라우저 스트림에는 실패만 있고 판정 원문은 없으며 reveal은 403이다.
5. diagnostics → quality_evaluation을 현재 통합 소스로 연결해 기존 4조건을 읽기 전용으로
   재실행했다. 후보 수 3/6/2/3 모두 연결 검증 통과, 전부 unreviewed, 오류/오탐 비율은 null이다.
   사람 라벨을 만들거나 과거 모델의 품질을 Claude 품질로 해석하지 않았다.

실패·재시작 fixture와 트리거는 tests 모듈에만 있다. 제품 API나 운영 설정에 제어 endpoint를
추가하지 않았다. 테스트 시장·모델·시계는 synthetic이며 유료/실제 공급자 호출은 0회다.

## 실행과 증거

- `scripts/test-worker-spring.ps1 -JavaHome <JDK17> -PostgresBin <bin> -Python <Python3.12>`.
  psql은 필요 없으며 Gradle 기본 캐시의 PostgreSQL JDBC jar를 사용한다.
- ignored `ai-worker/data/integrated-validation/python-initial.xml`, `python-final-affected.xml`.
- ignored `ai-worker/data/integrated-validation/quality-recheck/`에 원문 없는 집계.
- 성공 E2E: `ai-worker/data/spring-integration/run-3339e6c636f94d4597cc9659f498f75c/`.
  `integration.xml`, `result.json`, 재시작 로그를 보존한다.
- 실패했던 psql 실행: `run-a2f8b387ae6b4e73b93d171b749e605d/`에 원인 기록 보존.
- launcher의 processes_alive_after_cleanup=[]와 재시작 프로세스 terminate/wait 완료 확인.
  추가로 해당 PostgreSQL/worker/Spring 포트 51997/51998/51999의 LISTEN 및 재시작 PID가
  남아 있지 않음을 확인했다. git diff --check 통과.

## 남은 조건과 다음 작업

이번 통합에서 재현한 미해결 회귀는 없다. 명확한 환경 결함은 해결했고, 추가 예산이나
사람 판단 없이 가능한 비용 복구 E2E와 기존 품질 입력 연결 검증까지 완료했다.
통과 검사를 이유 없이 반복하거나 단일 모드 등 새 기능을 확대하지 않았다.

| 남은 항목 | 필요한 조건/결정 | 현재 상태 |
|---|---|---|
| 실제 Claude HTTP 지연·비용·완료율 | 실제 키, 계정 모델 ID/접근, 별도 승인 총비용 상한과 호출 전 예약 | 유료 호출 보류. Haiku 토론자·Sonnet 중재자 선택만으로 접근·예산이 확인되지는 않음 |
| 추정치가 아닌 지출 상한 | 공통 예산 담당의 예약·미확정분 유지·사후 대조 정책 | 이번 변경은 NULL/추정치 보존만 검증. $0.15는 최대 결제액 보장이 아님 |
| 후보 오류/검토기 오탐의 품질 지표 | 독립적인 사람 라벨과 별도 종목/시점 평가셋 | 14후보 미검수; 합성 제안은 정답이 아님 |
| 실제 시장 기준 정합성 | 공급자 관측 시각, 특별 거래시간/발표지연, 기업행사 보정 정책·실자료 | 오프라인 날짜/캐시 회귀만 확인, 실시장 효과 미확인 |
| HTTP 단일 모드 및 다른 PR의 v0.6 계약 | 양쪽 계약 승인과 별도 구현 범위 결정 | 이 통합에 포함하지 않음. 활성화 금지; mode를 지원한다고 보고하지 않음 |
| 배포·전향 운용 | 위 선행 검증 및 별도 사용자 승인 | 활성화하지 않음; 기본 RAG=false 유지 |

제품 API 계약·공통 config·budget·Spring 제품 소스는 바꾸지 않았다. 키/예산/사람 검수에
막힌 검증은 실행하지 않았다. 출처 불명 충돌이나 판정 기준 변경이 필요한 상황은 발생하지
않아 별도의 사용자 판단 대기로 중지한 작업은 없다. 위 단일 모드/운영 정책 결정은 별도
범위로 남기며 이 보고서가 자동 재개 또는 승인으로 해석되어서는 안 된다.
로컬 통합 커밋만 만들었으며 원격 push, develop/main 병합, 배포, 스케줄 활성화는 하지 않았다.

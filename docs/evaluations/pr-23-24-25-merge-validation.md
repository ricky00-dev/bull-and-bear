# PR #23·#24·#25 병합 평가

2026-11-01. 사용자가 현재 완료 작업과 이전 PR의 평가·검증·push·PR 생성·병합을 요청했다.
통합 제품 revision은 `9867a14`이며 이후 검사 실행기·문서 보완은 제품 코드를 변경하지 않는다.
기준 develop은 `7e48f7c`, 최초 감독 기준은 `5d2a8e5`이다.

## 평가 및 수정

- #23: 원본 `d431ce2` → 수정 `d8a5c27`. 시도별 비용이 덮어써지는 문제, RUNNING 복구 누락,
  SSE 연결 오류가 새 시도를 소진하는 문제를 V7 원장·같은 요청 재구독·원자적 저장으로 수정했다.
  7일 표본이 없어도 3일 성적표를 선택할 수 있게 수정했다. V6 migration은 유지했다.
- #24: 원본 `51cf34f` → 수정 `2e389e3`. 동일 snapshot_id 재시도에서 새 created_at과 저장본이
  달라지는 문제를 저장된 canonical snapshot 재로드로 수정했다.
- #25: HTTP 실패/재시작·사용량 미확정 보존, 확정 시점 데이터와 KOSPI 비교,
  검증기/평가 근거, RAG·single 결합 경계를 통합했다. executor 실패 처리와 mode 인자를 모두 보존했다.
- 확인된 재현 결함은 수정됐고 아래 검증 범위에서 develop 병합 가능으로 판단한다.
  실제 모델 품질·운영 활성화 승인으로 해석하지 않는다.

## 최종 검증

| 검사 | 통과 | 실패 | 생략 |
|---|---:|---:|---:|
| Python 전체 회귀 | 476 | 0 | 5 |
| 별도 Spring/PostgreSQL/HTTP fixture | 5 | 0 | 0 |
| Java HttpWorkerClient/ScoreRule/StartDebateRequest | 9 | 0 | 0 |
| Java SingleVerdictRecovery (실제 PostgreSQL) | 7 | 0 | 0 |
| 웹 build / lint | 모두 성공 | 0 | 0 |

Python 전체는 46.97초. 일반 실행의 외부 연결 5개 생략은 별도 통합 실행에서 모두 실행했다.
통합 5개는 59.13초, `ai-worker/data/spring-integration/run-f6bf49fdebae4b3a8c8673404d462dc4`에
로컬 증거가 있다. 판정 봉인/공개, SSE 재생, 당일 재사용, 미확정 사용량, 워커 프로세스 재시작,
단일 모드 저장/재사용 및 3·7거래일 채점을 확인했다. 실제 Spring과 임시 PostgreSQL을 사용하되
모델·시세는 합성 fixture, 채점 시각은 가상이다. 종료 후 잔존 프로세스 0.

`scripts/test-worker-spring.ps1`은 Java 9개와 bootJar 후 테스트 전용 DB에서 새 복구 검사7개도
실행한다. 테스트 URL이 없는 일반 Java 실행에서 생략될 수 있는 검사를 명시적으로 실행했다.
Python 전체 실행은 해당 worktree의 `ai-worker/src`를 PYTHONPATH로 지정해야 한다.
공유 venv의 editable 설치가 원본 checkout을 가리키므로 처음 경로 지정 없이 실행한 명령은
import 수집 오류20개를 냈다. 경로를 바로잡고 전체를 재실행하여 위 결과를 얻었다.

초기 single E2E는 fixture가 LiveRunner 경로를 상속하여 TypeError로 실패했다.
합성 run_single 라우팅과 실제 LLM 생성 차단을 추가한 후 통합 검사를 재실행했다.
해당 초기 오류에서 모델 응답/토큰 기록은 없으며 이를 실제 Claude 성공 또는 청구 확인으로
해석하지 않는다. 최종 fixture는 실제 LLM 생성 시 즉시 실패한다.

## 미검증 및 제한

- Docker 미설치로 Java Testcontainers 전체 검사는 미실행. 선택 Java 및 실제 PostgreSQL 검증과 구분한다.
- 실제 Claude 성공률·청구 대조, 독립 사람 품질 라벨, 실시장 성숙 성과는 미검증이다.
  #24의 기존 실제 Claude 실험은 판정 반려였으며 이번 합성 통과가 이를 대체하지 않는다.
- V6에서 이미 소실된 과거 비용은 복구할 수 없다. 다중 인스턴스 분산 실행·새 강제 금액 상한은 범위 밖이다.
- RAG와 SINGLE_ENABLED 운영 기본 false 유지. 유료 호출 추가, 배포, 운영 스케줄 활성화는 수행하지 않는다.
- 원본 작업 폴더·기존 미커밋 데이터·환경 파일을 보존했다. 키/.env/로컬 증거 데이터는 커밋하지 않는다.
- 병합 후에는 정확한 remote develop revision과 PR 상태를 감독 채팅에서 확인·보고한다.

# 실제 Spring ↔ RAG 워커 로컬 통합 평가

2026-10-30 KST. 현재 독립 worktree에서만 실행했다. 시스템 Java 설정·설치 서비스·운영 DB·기존
프로세스를 변경하지 않았다. 실제 PostgreSQL/Spring/HTTP/RAG 검색 경로를 사용했지만
시장 시세·LLM·지식 내용·시장 시계는 synthetic fixture다. **실제 예측 성과/유료 비용 평가가 아니다.**

## 환경과 출처

처음에는 PATH Java 8, JAVA_HOME 미설정, Docker/PostgreSQL/관련 포트 리스너 없음이었다.
아래 portable runtime을 ignored `ai-worker/data/spring-integration/runtime/`에만 준비했다.
Docker를 설치하거나 Testcontainers 테스트를 성공한 것으로 처리하지 않았다.

| 런타임 | 확인된 버전 | 다운로드 SHA256 |
|---|---|---|
| Eclipse Temurin JDK | 17.0.20.1+1, Windows x64 | `e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0` |
| Zonky PostgreSQL binary | 16.15.0 Maven artifact / postgres 16.15 | `51c7812dc1af47c9a2ccb64fe74efb88c515cff2da347ce72aab92b4cc8e1191` |

- JDK: [Adoptium 공식 API cookbook](https://github.com/adoptium/api.adoptium.net/blob/main/docs/cookbook.adoc)의
  API로 Windows JDK 17 asset을 조회했다. API 제공 SHA256과 실제 ZIP을 비교했다.
  [고정 ZIP](https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip).
- PostgreSQL: [Zonky binary 프로젝트](https://github.com/zonkyio/embedded-postgres-binaries)는 테스트 목적의
  경량 PostgreSQL 번들을 제공한다. [Maven Central 고정 JAR](https://repo.maven.apache.org/maven2/io/zonky/test/postgres/embedded-postgres-binaries-windows-amd64/16.15.0/embedded-postgres-binaries-windows-amd64-16.15.0.jar)과
  같은 경로의 `.sha256`을 비교했다. JAR의 txz를 Python tarfile `filter='data'`로 풀었다.
  PostgreSQL 프로젝트가 직접 서명한 배포물이라고 주장하지 않는다. 이 번들은 로컬 테스트에만 사용했다.
- Gradle wrapper 9.8.2, Spring Boot 4.1.1, Python 3.12.15, pytest 9.1.1.

## 구현과 실행 경계

- `scripts/test-worker-spring.ps1`은 매번 새 `run-<UUID>` 디렉터리·별도 PostgreSQL cluster와
  loopback 임시 포트 3개를 만든다. 시스템 설정 대신 프로세스 환경만 바꾸고 finally에서 복원한다.
- 임시 cluster만 `--auth=trust`를 사용하며 PostgreSQL/Spring/워커를 모두 `127.0.0.1`에 bind한다.
  운영 DB를 대상으로 실행하는 옵션은 없다. 테스트 목적으로만 사용한다.
- Spring production 코드/계약은 변경하지 않았다. 가짜 WorkerClient 대신 실제 HttpWorkerClient를
  사용하며 Flyway 5개 마이그레이션·DB 저장·SSE relay·봉인·공개·ScoringService를 실행한다.
- Python fixture의 `--rag`는 검수 상태를 모사한 synthetic knowledge → 실제 RagStore → v2 세대 →
  Retriever → 고정 KnowledgeContext → runner 연결을 요구한다. `PRIVATE_RAG_BACKGROUND` marker가
  runner에 도착하지 않으면 실행이 실패한다. 세대 발행 시각은 과거 fixture 시각으로 명시적 모사한다.
  이는 실제 과거 운영 세대가 존재했다는 증거가 아니다.
- `--clock-file`은 테스트 워커의 시장 시각만 전진시킨다. 시스템 날짜는 바꾸지 않는다.
  미래 weekday 종가 7개를 제공하되 요청 시각 뒤 가격은 Market 필터를 통과하지 못한다.
- Spring의 테스트 프로세스에만 scoring cron을 1초로 설정한다. 10/21에는 3일만 채점하고 7일은
  PENDING, 10/28에는 7일도 채점한다. 판단 기준일은 계속 2026-10-16이다.
- 종료 시 이 실행에서 만든 Spring/worker process handle만 종료하고 PostgreSQL은 해당 cluster의
  pg_ctl로 fast shutdown한다. PIDs·포트·결과·정리 후 생존 프로세스 목록을 `result.json`에 남긴다.
  이미 사용 중인 포트/서비스를 종료하거나 대체하지 않는다. 임시 포트 선택과 bind 사이 경합은
  가능하며 이 경우 시작 실패로 기록한다.

## 검증 결과

| 실행 | 결과 |
|---|---|
| Java HttpWorkerClientTest + ScoreRuleTest + bootJar | **7 passed, 0 skipped**, Gradle BUILD SUCCESSFUL 44초 |
| 최초 실제 Spring/PG/RAG HTTP + 3/7일 완료 채점 | **2 passed, 3.48초** |
| 3일 SCORED/7일 PENDING 중간 상태·7일 통계까지 확대 | **2 passed, 5.01초** |
| fixture require_context 분리 후 HTTP/RAG/server 회귀 | **44 passed, 18.24초** |
| 최종 require_context marker 검증 포함 실제 Spring 재실행 | **2 passed, 5.46초** |

Java 테스트 숫자는 생성된 JUnit XML의 ScoreRuleTest 5개와 HttpWorkerClientTest 2개를 확인했다.
전체 Docker/Testcontainers Java 테스트는 실행하지 않았다. 실제 Spring 앱을 별도 로컬 PostgreSQL에
연결한 외부 검증이므로 이를 Testcontainers 전체 통과로 바꾸어 쓰지 않는다.

확인한 외부 시나리오(삼성전자/하이닉스 각각):

1. 게스트 인증·초성 검색·종가 조회·토론 생성, 스냅샷 기준일 10/16·가격 399 저장.
2. 사용자 판정 전 reveal 403, detail에 verdict 없음, SSE에 `debate_sealed`만 있고
   `debate_completed`/`decisive_evidence`/PRIVATE/KCTX/PRIVATE_BACKGROUND_DATA 없음.
3. 사용자 HOLD 판정 후 중재자 HOLD와 점수 공개, 3/7일 채점 예약.
4. 같은 종목/날짜 재요청은 기존 토론 재사용.
5. 3번째 거래일 10/21 SCORED, 7일은 PENDING. 이후 7번째 거래일 10/27 SCORED.
6. 종목·KOSPI fixture 종가로 계산한 초과수익과 반환 값 일치(허용 오차 0.001%p),
   사용자 통계의 scored는 7일 본판정 기준 1건.

첫 실행 `run-927a02f8f21a4c85842360bd13d72a0f`, 확대 실행
`run-e49d96f35411491697f88932ed9aa9de`에 pytest/JUnit/서버 로그·감사 JSON이 보존되어 있다.
확대 실행의 PostgreSQL 51818·worker 51819·Spring 51820 리스너가 종료 후 없음을 확인했고,
`processes_alive_after_cleanup=[]`이다. 원시 DB·런타임·로그·키는 커밋하지 않는다.
최종 실행은 `run-ef5ca3c19a0b44759ce52665d85b7cce`이며 PostgreSQL 52234/PID 34868,
worker launcher 52235/PID 32528, Spring 52236/PID 36544를 사용했다. 종료 후 세 프로세스
모두 정리됐고 PostgreSQL 정상 shutdown 및 빈 생존 프로세스 목록을 확인했다.

총괄 세션에서 최종 v3 질의·import 보존·예산/감사 변경 통합 후 다시 실행했다:
`run-a6e589d50ac2499491e80569249596c9`, **2 passed, 4.85초**.
PostgreSQL/worker/Spring은 각각 포트 55346/55347/55348, PID 28584/35968/35540이었다.
`processes_alive_after_cleanup=[]`와 세 포트의 리스너 부재를 재확인했다.
API 소스는 바뀌지 않아 앞서 검증한 bootJar를 `-SkipBuild`로 사용했다.

초기 fixture 변경에서 정상 empty context까지 completed로 강제하는 회귀 1개가 발견됐다.
운영 의미를 바꾸지 않도록 standalone 통합에만 `require_context=True`를 적용하고 기존 정상
빈 결과 경로는 유지했다. 44개 회귀를 다시 통과했다.

Spring 로그의 `test-model` 비용 `$0.3`은 **기존 Spring의 모르는 모델 fallback 추정치**다.
유료 호출·실제 사용량/단가를 측정한 값도, 실제 비용 0달러의 증거도 아니다.
실제 공급자·운영 키·검수된 지식 corpus·실모델 품질·전향 3/7일 결과는 별도로 검증해야 한다.
RAG 운영 기본 false는 유지한다.

## 재실행

공식 출처에서 위 버전을 내려받아 checksum을 확인한 뒤, 저장 경로를 인자로 전달한다.
스크립트는 다운로드·시스템 설치를 자동으로 수행하지 않는다.

```powershell
./scripts/test-worker-spring.ps1 `
  -JavaHome ./ai-worker/data/spring-integration/runtime/jdk/jdk-17.0.20.1+1 `
  -PostgresBin ./ai-worker/data/spring-integration/runtime/postgres/bin `
  -Python <worker-venv/Scripts/python.exe>
```

이미 현재 소스로 bootJar/Java 단위 테스트를 완료했을 때만 `-SkipBuild`를 붙인다.
실행 아티팩트는 ignored `ai-worker/data/spring-integration/run-<UUID>/`에 남긴다.

## 실제 공급자 운용 전 별도 선행

원격 develop의 `38a4516`은 이 작업에서 적용하지 않았다. fixture 통합의 필수 선행은 아니지만,
냉시작 KRX 조회의 긴 지연·뉴스/DART 오류 응답·캐시 처리·종료 처리 보완을 포함하므로 실제
공급자 운용 전에 감사/RAG 변경과 충돌을 보존하며 별도 통합·회귀하는 것을 권한다.

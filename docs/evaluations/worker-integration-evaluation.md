# 워커와 Spring HTTP 연동 평가

2026-10-30 · 브랜치 `chore/worker-integration-evaluation` · 기준 `develop`의 `83247f2`

| 평가 | 결과 | 범위 |
|---|---|---|
| Python fixture·서버 타깃 | 11 passed | 후속 거래일 시세·입력 검증·기존 서버 회귀 |
| 해당 브랜치 Python 전체 | 93 passed, 2 skipped | 외부 Spring 환경 미지정 상태의 전체 워커 테스트 |
| 실제 Spring HTTP 연동 | 2 passed | 삼성전자·SK하이닉스 검색→토론→SSE 봉인→사용자 판정→공개→재사용→3/7거래일 채점 |
| Java HTTP·채점 단위 | 7 passed | HTTP 클라이언트 파싱과 판정 경계 |
| Docker 기반 Java 전체 | 23 passed, 0 failed, 0 skipped | 10개 suite, 판정·채점·전향 운용·차트·퀴즈·할당량 등 |

Java 전체는 원본 체크아웃에서 실행했다. 당시 Java 소스는 이 브랜치와 동일하며, 워커 안정화 변경은 이후 원격 `develop`의 `447cdf4`에 병합되었다. Python 브랜치별 테스트 수는 각 기준 소스와 추가 테스트 수에 따라 다르다.

## 연결 환경과 실제 확인

Windows, JDK 17.0.14, Gradle 9.8.2, Docker Engine 28.2.2, PostgreSQL 16을 사용했다. 평가 전용 빈 DB를 사용했으며 기존 개발 DB는 변경하지 않았다. Python fixture는 loopback 18000, Spring worker 프로필은 18080에서 실행했고 전향 운용은 비활성화했다.

스냅샷 기준일 2026-10-16·종가 399를 유지하고 테스트 전용 후속 평일 시세를 2026-10-30까지 제공했다. 실제 HTTP 결과의 3거래일 2026-10-21, 7거래일 2026-10-27 초과수익을 Decimal 독립 계산과 비교했다. 판정 전 AI 결론 비노출과 판정 후 공개·재사용도 확인했다.

`--settled-prices`는 `tests.http_fixture`에만 있다. 운영 앱에는 fixture 옵션을 추가하지 않았고, 옵션을 쓰지 않으면 기존 fixture 동작을 유지한다.

## 재현

각 체크아웃의 `ai-worker/src`를 `PYTHONPATH`로 지정해 다른 작업 공간의 editable 설치가 섞이지 않게 한다. 가상환경은 해당 컴퓨터에서 새로 구성한다.

1. 독립 PostgreSQL DB와 JDK 17 이상을 준비한다.
2. `ai-worker`에서 `python -m tests.http_fixture --port 18000 --data data/integration-evaluation --settled-prices`를 실행한다.
3. Spring에 `WORKER_TOKEN=integration-test-token`, `WORKER_BASE_URL=http://127.0.0.1:18000`, 평가 DB 접속값, `BULLBEAR_FORWARD_RUN_ENABLED=false`, `BULLBEAR_SCORING_CRON=*/1 * * * * *`를 설정한다. `./gradlew bootRun --args='--server.port=18080 --spring.profiles.active=worker'`로 실행한다. Windows는 `gradlew.bat`를 사용한다.
4. `BULLBEAR_TEST_API_URL=http://127.0.0.1:18080`, `BULLBEAR_TEST_EXPECT_SCORED=1`을 지정하고 `python -m pytest -q -p no:cacheprovider tests/test_spring_integration.py`를 실행한다.
5. API 폴더에서 `./gradlew test`로 Docker 기반 Java 전체 회귀를 실행한다.

고정 fixture의 채점 목표일 이후인 시스템 날짜와 격리된 빈 DB를 사용해야 한다. 짧은 채점 cron은 테스트 중에만 사용하고 평가 프로세스·컨테이너는 종료 후 정리한다.

## 남은 범위

실제 HTTP·DB·스케줄러·봉인·채점 연결은 검증했지만 시장 데이터와 LLM은 결정론적 테스트 자료다. 실제 공급자·유료 모델의 성공률·지연·비용이나 예측 적중률을 입증하지 않는다.

현재 원본 환경에는 데이터 공급자·OpenAI 키가 있으나 Anthropic 키는 없어 운영 Anthropic 경로의 유료 토론과 전향 운용을 켜지 않았다. 다른 컴퓨터에서는 키를 별도로 설정하고 실제 역할별 모델·예산을 맞춘 뒤 운영 검증을 진행해야 한다. 키·환경 파일·원문 데이터·임시 DB는 커밋하지 않는다.

# 로컬 백업·복원과 동시 요청 검사

2026-11-02. 외부 모델/임베딩·S3·실서비스 배포 없이 실행했다.
[복원 원자료](rag-recovery-local.json), [동시 요청 원자료](rag-load-local.json).

## 복원 범위와 결과

정지된 `ai-worker/data/rag-rollover-e2e`에서 SQLite backup API로 HTTP/아카이브/context DB3개를 백업했다.
색인 파일은 다시 만들지 않고 원본 바이트와 receipt를 함께 복사했다. 총19개 파일의 SHA-256 목록과 DB 스키마/행의
논리 해시를 저장했다. 새 디렉터리에 복원한 뒤 파일 목록·해시와 DB integrity/foreign-key/논리 해시를 검사했다.

복원한 실제 FastAPI 앱을 두 번 시작해 두 종목의 문서 검색/Fact 조회 총8개 응답을 이전 실제 브라우저 결과와
전체 비교했다. context ID를 포함해 일치했다. G2 설정에서도 기존 snapshot은 G1을 사용했다. 연결2개는 ready,
당시 문서 연결 근거가 없는 과거 원본2개는 unbound 상태를 유지했다.

별도 폐기 가능한 백업 복사본의 receipt에 손상을 넣었고, 복원 도구는 대상 디렉터리를 만들기 전에 거부했다.
원본/정상 백업은 변경하지 않았다. 백업 약0.148초, 복원 약0.085초는 이 작은 fixture에 대한 관측값이며 RTO 보장이 아니다.

스크립트는 테스트 fixture 전용이다. 모든 writer를 정지한 조건이며 운영 온라인 백업 도구로 사용하지 않는다.
HTTP owner lock으로 실행 중 워커는 배제하고, 데이터베이스는 backup 전후 논리 해시가 같음을 검사한다.
Windows asyncio 내부 loopback socketpair2개 외 접속은 없었다. 공급자/모델 runner는 호출하면 실패하는 경계를 뒀다.
최초 실행의 모든 socket 차단은 이 내부 socketpair까지 막았으므로 loopback만 허용한 뒤 새 출력 경로에서 재실행했다.

## 제한된 동시 요청 검사

복원된 저장소에서 실제 FastAPI·Retriever·SQLite를 사용했다. 문서/Fact 각각 동시 요청1·4·8, 각32건으로 총192건이다.
실행 전에 동시4 이하 전부200, 동시8에서는503 허용, 모든200은 기존 종목별 응답 전체와 동일,500/혼합 응답 금지를
통과 기준으로 고정했다. 실행 결과192개 모두200이고 응답도 모두 일치했다. 공급자/모델 호출은0이다.

| 경로 | 동시 요청 | 성공/전체 | p95 (초) |
|---|---:|---:|---:|
| 문서 | 1 | 32/32 | 0.056 |
| 문서 | 4 | 32/32 | 0.137 |
| 문서 | 8 | 32/32 | 0.429 |
| Fact | 1 | 32/32 | 0.032 |
| Fact | 4 | 32/32 | 0.174 |
| Fact | 8 | 32/32 | 0.541 |

프로세스 내부 TestClient HTTP 검사다. Spring/브라우저/실제 네트워크 전송, PostgreSQL backend, 대규모 corpus,
장시간 부하나 운영 하드웨어를 포함하지 않으므로 서비스 처리량/SLA나 대규모 부하 검증으로 해석하지 않는다.
005930 실제 수집 저장본과000660 모의 저장본, 종목 격리 문서 fixture라는 기존 한계를 유지한다.

## 재현

worktree 루트에서 PYTHONPATH=ai-worker/src, PYTHON_DOTENV_DISABLED=1을 지정한다. 출력 디렉터리는 없는 새 경로를
지정해야 하며 기존 데이터에 덮어쓰는 옵션은 없다. 아래 작업은 외부 모델 키를 필요로 하지 않는다.

```sh
python scripts/rag-recovery-drill.py ai-worker/data/rag-rollover-e2e ai-worker/data/new-recovery \
  --baseline docs/evaluations/rag-rollover-live.json --report recovery.json
python scripts/rag-load-probe.py ai-worker/data/new-recovery/restored \
  --baseline docs/evaluations/rag-rollover-live.json --report load.json
```

현재 결과는 `ai-worker/data/rag-recovery-drill-v2`에 보존한다. PostgreSQL 전체 백업 복원은 이후
[별도 검증](rag-recovery-postgres.md)으로 보완했다. Docker 이미지/compose 기동·클라우드 TLS/IAM·운영 부하·
사람 검수 다종목 품질 승인은 미완료다. 사용자 확인으로 사람 검수 corpus는
현재 없는 상태다. 에이전트 작성 자료를 사람이 검수한 것으로 표시하거나 이 결과로 품질 승인을 대체하지 않는다.

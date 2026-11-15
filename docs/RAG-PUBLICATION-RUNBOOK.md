# 색인 게시와 스냅샷 생성 순서

> 이전 워커의 설계·검증 기록이다. 2026-11-10에 워커 RAG 구현을 제거했으므로 아래 명령과 배포 설정은 당시 리비전에서만 적용된다.

저장소 설치·이관·generation push/fetch는 [RAG 실행 안내](RAG-OPERATIONS.md), 자료 작성·검수는 [자료 입력 안내](RAG-DATA.md)를 따른다.

## 고정할 순서

1. 문서를 적재하고 관측 시각·원문 해시·검수 이력을 저장한다. 실제 관측이 없는 archive 입력을 current로 속여 등록하지 않는다.
2. 검수 완료 문서로 `bullbear rag publish --as-of <timezone-aware-time>`를 실행한다. 출력 generation ID를 기록한다.
3. 아래 준비 점검으로 실제 색인 파일/receipt의 무결성·게시 완료 시각을 확인한다. member_count도 확인한다.
   빈 색인은 시간상 준비 완료일 수 있으나 문서 검색 성공을 뜻하지 않는다.
4. 해당 ID를 BULLBEAR_RAG_GENERATION_ID에 명시해 워커 실행 설정을 고정한다. 이후 새 스냅샷을 수집·저장한다.
5. 저장한 스냅샷을 다시 준비 점검에 넣어 적합성을 확인한 후 조회한다. 원본 Fact의 기준일(as_of)과
   관측/결정 시각(created_at)은 별개다. 데이터 기준일이 과거라는 이유만으로 created_at을 고치지 않는다.

```sh
bullbear rag --data-dir data check-generation --generation G.<hash>
bullbear rag --data-dir data check-generation --generation G.<hash> \
  --snapshot data/snapshots/first.json --snapshot data/snapshots/second.json
```

점검은 로컬 저장소를 읽으며 수집·모델·색인 게시·스냅샷 변경을 수행하지 않는다.
현재 시점의 ready_for_new_snapshot, 게시 시각, 문서 수와 각 스냅샷의 eligible/reasons를 JSON으로 반환한다.
준비 완료이며 지정 스냅샷이 모두 적합하면 exit0, 미래 게시/과거 스냅샷 등 부적합은 exit1이다.
없는 색인/해시 오류 등은 기존 CLI의 안전한 저장소 오류와 exit1로 처리한다.

조건은 `generation.as_of <= snapshot.created_at` 및 `generation.committed_at <= snapshot.created_at`이다.
이 점검은 **운영 준비 명령**이며 서버가 새 스냅샷 생성 요청을 자동으로 예약하거나 순서를 바꾸는 기능은 아니다.
기존 HTTP 검색은 동일한 시간 검사를 계속 수행한다. Fact 수치 조회는 색인을 요구하지 않는다.

## 색인 교체와 과거 자료

G1로 만든 스냅샷 S1이 있다고 해서, 나중에 게시한 G2가 S1에 적합해지는 것은 아니다.
G1/게시 receipt/스냅샷/context를 보존한다. HTTP는 `http/worker.sqlite3`의 불변 `snapshot_generations` 기록으로
라우팅한다. 최초 snapshot INSERT와 연결 INSERT는 한 트랜잭션이다. G2로 설정을 바꾸거나 재시작해도 S1은 G1을
사용한다. 동일 ID 재저장은 최초 시각과 연결을 유지한다. 스레드 간 최초 저장은 직렬화하고 데이터 디렉터리당
프로세스 하나만 허용한다. 다중 replica 지원은 아니다.

연결에는 snapshot 전체 해시, generation ID, 원본 색인 파일 SHA-256, as_of, committed_at, 연결 시각을 저장한다.
검색할 때 원본 해시·게시 receipt·관측 시점을 재검증한다. G1 파일/receipt가 없거나 바뀌면503이며 G2로 우회하지
않는다. 최초 저장 때 비활성/설정 오류/미래 게시/저장소 장애면 `unavailable` 연결을 남긴다. snapshot은 보존하고
RAG 활성 시 모델 실행 전에 실패한다. 뒤늦은 정상 설정으로 같은 snapshot을 새 관측처럼 만들지 않는다.
Fact 조회는 연결과 무관하다. 기존 context는 불변 보존하고 replay할 수 있다. 연결 메타데이터가 추가된 새 조회는
별도 context ID를 만들 수 있으며 이전 context를 덮어쓰지 않는다. 검색 정책 변경까지 같은 결과를 요구하면
원본 context를 replay한다. BULLBEAR_RAG_GENERATION_ID는 최초 저장할 스냅샷의 연결 후보에만 사용한다.

같은 내용의 snapshot ID가 기존 저장소에 있으면 최초 객체의 created_at이 유지된다. 날짜를 새로 찍어 과거
스냅샷을 최신 색인에 맞추지 않는다. reconstructed-v1은 명시적 오프라인 재구성 평가에만 쓰고 HTTP에는 적용하지 않는다.
개발 테스트에서 새 관측 시점 복사본을 만들 때는 새 ID와 integration_fixture 출처를 쓰고 원본도 보존한다.

## 기존 스냅샷 이관과 운영 점검

업그레이드 시 연결 테이블만 추가하고 기존 snapshot/context를 갱신하지 않는다. 연결 없는 기존 자료는 문서 검색503,
Fact 조회는 기존 동작을 유지한다. 현재 generation을 자동 적용하거나 최신 색인을 찾아 연결하지 않는다.
다음 명령은 워커를 정지한 유지보수 시간에 실행한다. 소유권 잠금이 있으면 실패한다. 유지보수 모드는 실행 중이던
토론의 실패 이벤트를 만들거나 상태를 바꾸지 않는다. 실행 중 토론은 먼저 정상 종료하도록 기다린다.

```sh
# 전체 snapshot 연결·색인/receipt 검사. 미연결/손상 하나라도 있으면 exit1.
bullbear rag --data-dir data check-bindings
# 기존 성공/empty observed-v1 문서 context로만 이관. 기본은 검증만, --apply 때 INSERT.
bullbear rag --data-dir data bind-snapshot --snapshot-id S1 --context-id KCTX.<hash>
bullbear rag --data-dir data bind-snapshot --snapshot-id S1 --context-id KCTX.<hash> --apply
```

snapshot ID/전체 해시, context의 generation 게시/as_of, 실제 receipt가 모두 일치해야 한다. reconstructed-v1,
Fact-only, 실패/timeout context로는 이관할 수 없다. 기존 연결을 다른 generation으로 바꾸는 옵션은 없다. 동일 이관은
멱등이다. 당시 context가 없으면 미연결을 유지하고 원본 Fact만 제공한다. 원본 생성 시각이나 receipt를 고치지 않는다.
`check-bindings`의 미연결 목록은 운영자가 의도한 Fact-only 범위인지 검토한다. 이 점검은 파일·연결 무결성 검사이며
검색 품질·전체 원문 객체·외부 DB 접근 권한·S3를 검증하지 않는다.

## 배포 준비와 교체/복구

- 이미지에 `rag-postgres` 의존성을 포함했다. `deploy/compose.rag.yml`을 기본 compose에 추가하면 RAG 설정을 전달한다.
  기본 RAG_ENABLED=false, 로컬 객체 저장, shadow/유료 query 비활성이다. PostgreSQL 선택 시 별도 RAG DB를 준비하고
  기존 Alembic 절차로 이관한다. Spring DB 스키마를 RAG용으로 재사용하지 않는다. S3는 계속 보류한다.
- 구성 검사 예: `docker compose -f deploy/compose.yml -f deploy/compose.rag.yml --env-file deploy/.env --profile worker config --quiet`.
  실제 배포는 별도 단계다. config 전체 출력은 비밀값이 포함될 수 있으므로 보관하지 않는다.
- 전달 변수: RAG_ENABLED, RAG_GENERATION_ID, RAG_ARCHIVE_BACKEND, RAG_CONTEXT_BACKEND, RAG_POSTGRES_DSN.
  DSN은 비밀 저장소로 제공한다. postgres backend 실행 계정 권한/TLS는 별도 검증한다.
- 교체 전 신규 생성을 차단하고 진행 중 토론/수집을 마친 뒤 워커를 정지한다. check-bindings 결과와 활성 설정을 보존한다.
  SQLite는 정지 상태에서 관련 WAL까지 일관되게 복사하거나 SQLite backup API를 사용한다. worker.sqlite3, snapshot 파일,
  audits, contexts DB, archive DB/객체, 사용 중인 모든 generation과 원본 receipt를 한 묶음으로 보존한다. PostgreSQL 사용 시
  DB 일관 백업과 로컬 파일 묶음의 대응 시점을 기록한다.
- G2를 게시/배포하고 준비 검사 후 새 스냅샷용 설정만 G2로 바꾼다. G1 파일을 지우지 않는다. 과거 S1과 새 S2의 문서/Fact,
  인증·판정 봉인을 검사한 후 요청을 연다. 설정을 G1로 되돌려도 이미 G2에 연결된 S2는 G2를 사용한다.
- 손상 복구는 연결을 수정하는 대신 백업한 동일 색인 바이트/receipt를 복원한다. 같은 manifest 재게시로 committed_at이
  달라지면 원본 복원이 아니다. 복구 뒤 check-bindings, 과거 context replay, 대표 snapshot 검색을 확인한다.
  worker DB만 과거 버전으로 되돌리면 새 연결을 잃으므로 대응 백업을 사용한다. 이전 라우팅 코드로 downgrade하지 않는다.
- 로컬 복구 경계는 검사했으나 Docker 미설치로 실제 이미지/compose 기동, 클라우드 TLS/IAM, 운영 백업 복원과 대규모 부하는
  미검증이다. 사람 검수 다종목 실데이터 corpus가 없으므로 운영 검색 품질 승인도 별도다.

## PostgreSQL 복원과 검증 근거

DB writer·워커·수집기를 정지하고 DB dump와 로컬 파일 backup의 대응 묶음을 기록한다.
pg_dump는 비밀값을 인자로 출력하지 않도록 PG서비스/환경으로 접속을 제공하고 custom format으로 보관한다.
새 빈 DB에 pg_restore --exit-on-error로 복원한 뒤 역할·권한·extension을 확인한다.
원본 receipt를 포함한 로컬 파일도 복원하여 check-bindings, context replay, 대표 검색을 실행한다.
로컬 검증의 no-owner/no-acl 옵션은 운영 권한 복원 검증을 대체하지 않는다. 운영 DB에 테스트 복원을 실행하지 않는다.

- [다종목 연결 검증](evaluations/rag-multistock-live.md): 실제 저장본 1종목·모의 저장본 1종목과 검증용 문단, 브라우저 검사 및 재현 환경.
- [색인 교체](evaluations/rag-rollover-live.md), [SQLite 복원·동시성](evaluations/rag-recovery-load-local.md), [PostgreSQL 복원·제한 계정](evaluations/rag-recovery-postgres.md).
- [운영 준비 감사](RAG-READINESS-AUDIT.md): 검증 완료 범위와 남은 조건. 로컬 검증을 배포·검색 품질 승인으로 해석하지 않는다.

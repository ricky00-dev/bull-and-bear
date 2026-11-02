# RAG 1주 구현 진행과 실행 안내

계획: [1주 범위와 장기 아키텍처](RAG-LONG-TERM.md). 기준: develop `2cca67f`, 구현 브랜치 `feat/rag-week-one`.

2026-11-02 운영 준비 추가: snapshot별 generation/원본 receipt를 HTTP 저장과 원자적으로 고정한다. 재시작·설정 교체 후에도
과거 연결로 조회하며 미연결 snapshot은 자동 보정하지 않는다. `bind-snapshot`과 `check-bindings`, 선택적 compose RAG 설정,
PostgreSQL 이미지 의존성을 추가했다. [이관·교체·복구 절차](RAG-PUBLICATION-RUNBOOK.md)가 현재 기준이다.
실제 배포·Docker 실행·클라우드 복원·사람 검수 다종목 검색 품질은 완료하지 않았다.

## 1일차 구현 범위

검색 컨텍스트와 검색 시도 감사 기록의 저장 인터페이스를 분리했다. 기본값은 기존 `rag/contexts.sqlite3`이며 PostgreSQL은 명시적으로 선택한다. HTTP와 CLI 검색은 선택된 저장소에 context와 검색 이력을 한 트랜잭션으로 저장한 뒤 결과를 반환한다. 저장 오류는 검색 성공이나 empty로 바꾸지 않고 모델 실행 전에 중단한다.

1일차에는 PostgreSQL `rag.contexts`, `rag.searches`를 구현했다. 2일차에는 원문·관측·검수 테이블과 generation 등록부, 로컬/S3 객체 저장을 추가했다(아래 실행 안내). HTTP 요청/SSE 상태는 여전히 로컬이다. 이후 4~5일차에 pgvector 검색·실모델 평가·HTTP shadow를 추가했으며 실제 클라우드 배포는 미완료다. PostgreSQL 스키마는 벡터 확장을 요구하지 않는다.

같은 context는 내용 기반 ID를 유지하고 각 검색 시도는 별도 ID로 기록한다. 같은 시도 ID/내용 재전송은 멱등하며, 같은 ID의 다른 내용은 전체 트랜잭션을 취소한다. DB trigger로 UPDATE/DELETE/TRUNCATE를 거부한다. 원문 텍스트로 저장하여 기존 canonical JSON과 해시를 그대로 보존한다.

## 설치와 스키마 생성

아래 명령의 작업 디렉터리는 `ai-worker/`다. 비밀값은 환경변수/비밀 저장소로 제공한다. DSN을 명령 인자·문서·로그에 넣지 않는다. 운영용 연결은 배포 공급자의 TLS 인증서 검증 설정을 사용한다.

```powershell
uv sync --extra rag-postgres
# BULLBEAR_RAG_POSTGRES_DSN을 별도 RAG DB의 migration 계정으로 설정한 뒤 실행
uv run python -m bullbear.rag.storage migrate
```

마이그레이션은 워커 Alembic이 소유한다. `public.rag_alembic_version`으로 이력을 관리하고 Spring Flyway 테이블은 변경하지 않는다. 배포 단계에서 별도 RAG DB를 지정해야 한다. 실행 프로세스는 스키마를 자동 생성하지 않으며, migration 실행은 advisory lock으로 직렬화한다. 데이터 삭제 downgrade는 제공하지 않는다.

운영 reader/writer에는 `rag` schema USAGE, 필요한 불변 테이블 SELECT·INSERT, identity sequence USAGE를 부여한다. 수집 writer만 `source_watermarks` UPDATE를 추가로 받는다. source_watermarks를 제외한 테이블에는 UPDATE가 필요 없다. 이관 도구의 table lock·sequence setval은 별도 유지보수 계정으로 실행한다. 검색 이력을 기록해야 하므로 검색 프로세스도 INSERT 권한이 필요하다. 일반 실행 계정에는 DDL·TRUNCATE·DELETE 권한과 테이블 소유권을 주지 않는다. migration 계정은 실행 계정과 분리한다. 계정과 GRANT의 실제 provisioning은 배포 작업이다.

## 기존 컨텍스트 이관

```powershell
# 먼저 읽기 전용 검증. DSN/선택 의존성이 없어도 dry-run 가능
uv run python -m bullbear.rag.storage import-contexts data/rag/contexts.sqlite3 --dry-run
# 새 PostgreSQL 스키마로 이관. 실제 소스 위치에 맞춰 경로 지정
uv run python -m bullbear.rag.storage import-contexts data/rag/contexts.sqlite3
```

- source DB는 읽기 전용의 하나의 snapshot transaction으로 읽는다. 없는 경로를 새 DB로 만들지 않는다.
- 모든 context ID/본문 해시, audit 참조/형식 검증 후 목적지에 쓴다. source_hash와 읽은 context/search 수를 반환한다.
- 이관은 목적지 테이블 쓰기를 잠시 잠근다. 운영 검색 writer를 정지한 유지보수 시간에 수행한다.
- 기존 목적지 이력은 소스 이력의 같은 순서 prefix여야 한다. 다른 live 기록이 이미 섞인 목적지로 과거 이력을 덧붙여 순서를 바꾸지 않는다.
- 충돌 시 이관 전체를 롤백한다. 동일 이관 재실행은 기록을 늘리지 않는다. 소스 파일은 삭제/수정하지 않는다.
- 첫 주 도구는 컨텍스트 DB 전체를 메모리에 읽는다. 대규모 이관용 streaming/staging은 아직 구현하지 않았다.
- `import-contexts`는 context 전용이다. 원문·검수는 아래 `import-archive`, generation은 `push-generation`으로 별도 이관한다.

## HTTP와 CLI 연결

```dotenv
BULLBEAR_RAG_CONTEXT_BACKEND=postgres
# BULLBEAR_RAG_POSTGRES_DSN은 실행 계정으로 환경에 주입
```

기존 RAG 활성화와 generation 설정은 그대로 필요하며 이 설정만으로 RAG가 켜지지 않는다. `BULLBEAR_RAG_CONTEXT_BACKEND=sqlite`가 기본값이다. 설정 오타/DSN 누락/DB 장애를 로컬 SQLite fallback으로 숨기지 않는다.

기존 `bullbear rag retrieve/replay`는 선택된 context 저장소를 사용한다. PostgreSQL의 context만 읽으려면 로컬 RagStore 생성 없이 아래 명령을 쓸 수 있다.

```powershell
uv run python -m bullbear.rag.storage replay KCTX.<저장된_해시>
```

기존 benchmark는 독립 평가 디렉터리의 SQLite를 계속 사용한다. 운영 PostgreSQL 설정을 자동으로 물려받아 평가 자료를 섞지 않는다. 원문/검수의 공유 저장과 검색 파일 배포는 아래 명령으로 가능하다. HTTP 요청/SSE 상태가 공유되지 않으므로 여러 토론 replica는 아직 켜지 않는다.

## 검증 방법

```powershell
uv run pytest tests/test_rag_context_repository.py -q
# BULLBEAR_TEST_RAG_POSTGRES_DSN을 별도 폐기 가능한 테스트 DB로 지정
uv run pytest tests/test_rag_postgres.py -q
uv run pytest -q
```

PostgreSQL 테스트는 명시한 테스트 DB에 migration과 fixture 기록을 생성한다. 운영 DB를 지정하지 않는다. DSN이 없으면 해당 테스트는 skipped이며 PostgreSQL 검증 완료로 보고하지 않는다. 테스트는 외부 시장/유료 모델을 호출하지 않는다. 실제 클라우드 연결·TLS·IAM·백업 복원과 Spring 외부 통합은 별도 검증 대상이다.

## 다음 구현

2026-11-01 검증: 관련 집중 검사 71개 통과, 최종 전체 Python 506개 통과/외부 Spring 5개 생략(61.61초). 실제 격리 PostgreSQL 16.4에서 migration 재실행, 동시 멱등 저장, ID 충돌 롤백, DB 변경 금지, 과거 검색 순서 보존, 실제 Retriever 저장/재생, HTTP 저장 실패 시 runner 미호출을 확인했다. HTTP 시장/LLM은 fixture이며 유료 호출은 없다. wheel 빌드와 migration 파일 포함, uv lock 일치·diff 공백 검사도 통과했다.

최초 전체 실행의 하위 프로세스 1건은 새 가상환경의 소스 경로 누락으로 실패했다. PYTHONPATH를 명시하여 전체를 다시 실행한 결과가 위 최종 수치다. 개발 검증은 기존 로컬 Python 의존성을 참조한 전용 venv에서 수행했으며, 완전히 새 환경의 전체 설치와 실제 클라우드 연결은 아직 검증하지 않았다. 테스트 DB는 이 작업 전용으로 생성하고 검증 후 종료했다.

2일차 구현은 아래와 같다. 다음은 3일차 증분 적재 작업 lease·재시도·다종목 검증이다. 위 이관 도구의 해시·순서·충돌·HTTP 실패 검사를 유지한다. 4일차 pgvector 구현 전에는 임베딩 모델·차원·한국어 평가셋·호출 예산을 고정한다. 실모델/클라우드 미준비 시 로컬 fixture 결과와 실제 운영 결과를 구분해 남긴다.


## 2일차: 원문·검수 이력과 객체 저장 (2026-11-02)

`PostgresArchive`는 기존 RagStore의 수집·정정·철회·청크·검수 규칙을 재사용한다. `rag.documents`, `document_revisions`, `collection_runs`, `collection_items`, `document_events`, `source_watermarks`, `chunks`, `chunk_annotations`, `chunk_horizons`를 Alembic 0002로 추가했다. 검수 결과는 덮어쓰지 않으며 승인→거절 이후 과거 승인이 다시 살아나지 않는다. PostgreSQL writer 간 advisory lock과 deferred FK로 수집 단위의 원자성을 유지한다. 읽기는 별도 repeatable-read snapshot을 쓴다.

원문 객체는 기존 canonical JSON 바이트의 SHA-256 키를 유지한다. 기존 source_payload/수집 원응답은 collection 입력 JSON에도 그대로 보존된다. 이 작업이 뉴스 전문이나 PDF를 새로 내려받는 것은 아니다. 로컬 저장은 원자적인 생성, S3는 조건부 생성과 SHA-256 검증을 사용한다. 이미 있는 키의 다른 내용은 덮어쓰지 않는다. 업로드 실패 시 DB 기록을 만들지 않으며, DB rollback 후 남을 수 있는 미참조 객체는 재실행에 재사용한다. 자동 삭제/GC는 구현하지 않았다.

### 설정

```powershell
uv sync --extra rag-postgres --extra rag-s3
uv run python -m bullbear.rag.storage migrate
```

```dotenv
BULLBEAR_RAG_ARCHIVE_BACKEND=postgres
BULLBEAR_RAG_CONTEXT_BACKEND=postgres
BULLBEAR_RAG_OBJECT_BACKEND=s3
BULLBEAR_RAG_S3_BUCKET=<이미 준비된 비공개 버킷>
BULLBEAR_RAG_S3_PREFIX=rag/objects
# BULLBEAR_RAG_POSTGRES_DSN: 환경/비밀 저장소로 주입
# AWS 인증: boto3 기본 credential chain (운영은 역할 권한 사용)
# S3 호환 서비스가 필요할 때만 BULLBEAR_RAG_S3_ENDPOINT 지정
```

기본값은 archive=`sqlite`, context=`sqlite`, object=`local`이다. 세 설정은 독립적이므로 공유 저장 전환 시 모두 확인한다. 버킷 생성·공개 ACL·운영 스위치 변경을 자동 수행하지 않는다. 필요한 객체 권한은 해당 prefix의 GetObject/PutObject이며, 버킷 버전 관리·암호화·보관 정책·백업과 IAM은 배포 단계에서 설정한다. S3 호환 서비스는 조건부 쓰기/체크섬 지원 여부를 실제 서비스에서 검증해야 한다. 구현 기준은 [AWS PutObject 문서](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)다.

### 기존 데이터 이전 순서

수집·검수 writer를 중지한 유지보수 시간에 수행한다. 아래 `source/rag`는 고정한 기존 아카이브 경로, `BULLBEAR_DATA_DIR`는 새 워커 캐시 디렉터리를 뜻한다. 소스 파일을 삭제하지 않는다.

```powershell
uv run python -m bullbear.rag.storage import-archive source/rag/rag.sqlite3 --dry-run
uv run python -m bullbear.rag.storage import-archive source/rag/rag.sqlite3
uv run python -m bullbear.rag.storage import-contexts source/rag/contexts.sqlite3
```

- dry-run은 PostgreSQL/S3 연결 없이 SQLite snapshot·FK·스키마·원문 해시·청크·검수 내용·관측 참조를 검증한다. 검수의 data_json과 검색용 상태/시각 열이 다르면 거부한다.
- 기존 document/revision/chunk/annotation/event ID, event_seq/annotation_seq, 원문·검수·관측 시각을 그대로 복사한다. 다음 새 이벤트/검수 sequence도 충돌하지 않도록 보정한다.
- 목적지 원문 테이블은 **비어 있거나 동일 이관 결과와 완전히 같아야 한다.** 운영 중인 별도 아카이브와의 병합은 지원하지 않는다. context 테이블은 별도이므로 미리 이관해도 된다.
- 객체 업로드를 먼저 완료하고 DB 이관을 한 트랜잭션으로 확정한다. 충돌/중간 실패 시 DB 전체 rollback, 동일 입력 재실행은 멱등이다.
- 소스 DB 전체와 원문 객체를 메모리에 보관한다. 대용량 streaming 이관은 후속이다. 이 명령은 기존 로컬 객체가 있는 SQLite에서의 최초 cutover 도구이며 PG→PG 또는 S3→S3 복원 도구가 아니다.
- SQLite 메타데이터를 유지하면서 원문만 옮기려면 `uv run python -m bullbear.rag.storage copy-objects source/rag/rag.sqlite3`를 사용한다. 목적지 object 설정을 미리 지정하고 복사 성공 후 reader 설정을 전환한다.

HTTP 토론, `bullbear rag import/sync/inspect/publish/retrieve`, corpus CLI는 선택한 아카이브를 사용한다. 독립 benchmark/evaluation은 기존 로컬 격리를 유지한다. 자동으로 운영 PostgreSQL 자료와 섞지 않는다.

### 검색 파일 배포와 새 워커 캐시 준비

FTS5는 PostgreSQL로 변환하지 않고, 기존 불변 파일을 파생 색인으로 사용한다. `rag.generations`에 파일/receipt의 해시와 원래 `committed_at`을 등록하고 객체 저장소에서 배포한다.

```powershell
# 기존 generation이 있는 워커의 BULLBEAR_DATA_DIR를 지정한 상태에서
uv run python -m bullbear.rag.storage push-generation G.<기존_해시>
# 새 워커의 BULLBEAR_DATA_DIR와 같은 PostgreSQL/S3 설정을 지정한 상태에서
uv run python -m bullbear.rag.storage fetch-generation G.<기존_해시>
```

`push-generation`은 이미 검증·봉인된 파일만 등록한다. `fetch-generation`은 파일 해시·manifest ID·receipt를 확인하고 staging 디렉터리에서 원자적으로 캐시에 게시한다. 원래 게시 시각을 보존하므로 옛 generation을 새로 만들며 가용 시점을 바꾸지 않는다. 같은 generation ID라도 파일/receipt가 다른 재빌드 결과로 덮어쓰지 않는다.

S3 원문은 `rag/cache/objects`에 해시 검증 후 캐시하고, fetch 단계에서 generation 소속 원문도 미리 받는다. 이후 검색은 캐시를 사용한다. 캐시가 손상되면 실패하며 검증 없이 원격본으로 덮어쓰지 않는다. 캐시는 불변 원문 바이트의 복제본이므로 원격 객체가 나중에 없어졌는지를 매 검색마다 확인하지 않는다. 철회/삭제/검수 변경의 효력은 PostgreSQL 이력으로 판단한다.

검색 요청 안에서 generation을 자동 다운로드하지 않는다. 운영 활성화 전에 fetch를 완료해야 하며, 새 generation 발행 뒤에도 push→각 워커 fetch→활성 ID 변경 순서가 필요하다. 작업 스케줄러/배포 자동화는 후속이다. PostgreSQL 메타데이터 조회에는 여전히 문단별 왕복이 있으므로 다량 문서의 클라우드 지연 목표 충족은 별도 측정·최적화가 필요하다.

### 확인 범위

실제 격리 PostgreSQL과 로컬 객체 저장을 이용해 전후 context ID/검색 payload 일치, 거절 검수 보존, generation을 새 워커로 복원, 원본 SQLite 불변, 동시 writer, 이관 실패 원자성, 기존 시점 규칙을 검사한다. S3는 botocore Stubber로 조건부 쓰기·409 재시도·412 중복 검증·403 오류 숨김·손상 바이트 거부를 검사한다. 실제 AWS/S3 호환 서비스·TLS·IAM·복구·대규모 지연 검증은 아직 수행하지 않았다. 아래 최종 검증 기록과 테스트 코드를 기준으로 판단한다.


2026-11-02 전체 검사: **532 passed / 외부 Spring 5 skipped (81.09초)**. 2일차 추가 26개 검사는 실제 PostgreSQL 도메인 규칙 14개와 이관·동시성·복원·S3 Stubber·캐시 검사를 포함한다. `uv lock --check`, wheel 빌드와 새 모듈/Alembic 파일 포함을 확인했다. 최초 개발 검사에서 드러난 Alembic version schema 경로와 SQLite 전용 busy_timeout 호환 문제를 수정한 뒤의 결과다. 최종 원문 누락 시 integrity_error 유지 보완 후 관련 아카이브·검색·HTTP 검사 **76 passed (38.39초)**, wheel 재빌드와 lock 일치 확인도 통과했다. 최종 신규 검사는 27개다. 전용 PostgreSQL은 검증 후 종료했다.


## 3일차: 캡처 기반 증분 적재·재시도·다종목 검증

S3 실제 연결은 후순위로 미루고 `BULLBEAR_RAG_OBJECT_BACKEND=local`로 검증했다. 이번 구현은 **이미 받은 공급자 응답을 안전하게 저장하는 작업 큐**다. 외부 NAVER/DART를 새로 호출하는 수집기, 공급자 HTTP 429 재시도, 자동 스케줄을 구현·활성화한 것은 아니다. 기존 공급자 응답을 `normalize_capture`로 정규화한 뒤 큐에 넣거나 정규화된 CollectionBatch를 직접 등록한다. 자료의 관측 시각은 원래 캡처 시각을 유지한다.

### 동작과 보장

- `ingest_jobs`는 작업 상태를, append-only `ingest_attempts`는 시작·재시도·성공·부분 성공·실패·lease 만료 이력을 저장한다. SQLite는 큐 최초 사용 시 부가 테이블을 생성하고, PostgreSQL은 Alembic `0003_rag_ingest_jobs`로 생성한다.
- 작업은 collection ID와 입력 fingerprint로 멱등 등록한다. 같은 collection ID의 다른 입력/종목/재시도 한도는 거부한다. 개별 작업 등록이 원자적이며 manifest 여러 항목 등록은 재실행 가능한 방식이다(전체 manifest 단일 트랜잭션은 아님).
- 범위 키는 공급자 + 6자리 종목 코드다. 이 단계는 `query_key=ticker`인 종목 캡처 전용이다. 문서에 종목 태그가 있으면 해당 종목을 포함해야 한다.
- 동일 공급자·종목은 수집 구간 순서대로 한 작업씩 처리한다. 앞 작업이 재시도를 기다리는 동안 뒤 구간이 추월하지 않는다. 다른 종목은 계속 진행한다. PostgreSQL의 짧은 DB 쓰기 트랜잭션은 기존 archive advisory lock으로 직렬화한다.
- claim 때 기본 60초 lease와 매 시도별 새 token을 발급한다. PostgreSQL은 DB 시계를 사용한다. 만료되거나 교체된 token은 뒤늦게 원문·watermark·완료 기록을 쓸 수 없다. 객체 쓰기 뒤에도 token을 다시 확인한다.
- 원문 업로드가 끝나면 원문 이력·수집 결과·watermark·작업 완료·시도 이력을 같은 DB 트랜잭션으로 확정한다. 완료 기록 실패 시 원문 DB 기록과 watermark도 함께 rollback한다. 객체만 남는 경우는 기존과 같이 멱등 재사용한다.
- 일시 저장 오류는 5초·10초·20초… 최대 300초 backoff를 적용한다. 기본 총 3회(최초 포함), 최대 10회다. 한도를 넘으면 failed로 종료한다. DB가 완전히 끊겨 실패 상태조차 저장할 수 없으면 실행은 실패하고, 복구 후 lease 만료를 통해 작업을 다시 확보한다.
- 잘못된 입력·동일 ID 충돌은 terminal failed다. 캡처 자체가 partial/failed이면 해당 상태와 원응답을 보존하고 같은 불완전한 응답을 반복 적재하지 않는다. 다음 수집 결과는 **새 collection ID**로 등록한다. partial/failed는 watermark를 전진시키지 않는다.
- complete-empty와 수집 실패를 구분한다. 수집이 완료됐더라도 기존 구간과 공백이 있으면 watermark를 건너뛰어 전진시키지 않는다. 작업 succeeded는 저장 성공을 뜻하며, 완전한 연속 수집 여부는 collection 결과의 `watermark_reason`/watermark를 함께 확인한다.
- `plan`은 기존 watermark에서 기본 1시간 겹치는 다음 구간을 계산한다. 겹친 캡처는 같은 내용이면 새 revision을 만들지 않고, 정정 내용이면 새 revision을 보존한다. 계획은 실제 수집 완료의 증거가 아니다.

### 실행

작업 디렉터리 `ai-worker/`. PostgreSQL을 선택한 경우 먼저 migration을 적용한다. 기존 환경의 S3 설정이 있다면 명시적으로 local로 바꾼다. 명령이 설정 파일을 자동 수정하지는 않는다.

```powershell
$env:BULLBEAR_RAG_OBJECT_BACKEND='local'
# PostgreSQL 사용 시 DSN을 환경에 주입한 상태에서
uv run python -m bullbear.rag.storage migrate

# 예: 종목별 다음 수집 구간 계획. 실제 운영 날짜로 바꿔 사용
uv run python -m bullbear.rag.jobs plan --source naver-news --tickers 005930,000660 --start 2026-10-30T00:00:00+09:00 --end 2026-11-02T18:00:00+09:00

uv run python -m bullbear.rag.jobs enqueue captures.json --max-attempts 3
uv run python -m bullbear.rag.jobs run --limit 30 --lease-seconds 60
uv run python -m bullbear.rag.jobs status
```

`captures.json`은 최대 1,000항목의 JSON 배열이다. 각 항목은 `ticker`와 `batch`(정규화된 CollectionBatch), 또는 `ticker`와 `capture`(기존 `bullbear rag sync` 입력)를 가진다. 캡처의 `query_key`도 같은 종목 코드여야 한다. 기존 sync와 동일하게 페이지 제한/불완전 응답을 complete로 표시하지 않는다. 여러 종목에 걸친 같은 문서는 일관된 원문/종목 태그로 정규화해야 같은 revision을 공유한다. 종목마다 태그가 다르면 기존 content hash 규칙에 따라 다른 revision이 되며, 같은 관측 시각의 상충 revision은 거부한다. 공급자 단위 기업 연결 정규화는 후속이다.

`run`은 현재 실행 가능한 작업을 최대 limit개 처리하고 종료한다. 대기시간이 남은 retry를 기다리며 무한 실행하지 않는다. backoff 이후 다시 run하면 이어서 처리한다. 자동 스케줄/상주 프로세스는 이 작업에서 활성화하지 않았다. 처리 결과에 partial/failed/retry/lease_lost가 있으면 종료 코드 1, 모두 succeeded 또는 당장 실행할 작업이 없으면 0이다. 큐 전체의 잔여 실패 여부는 status로 확인한다.

큰 캡처는 작은 수집 구간/페이지 단위로 나누거나 `--lease-seconds`를 늘린다(최대 3,600초). `heartbeat` 메서드는 살아 있는 token의 lease를 갱신하지만 현재 bounded CLI가 별도 heartbeat 스레드를 자동 실행하지는 않는다. lease보다 오래 걸리는 업로드는 commit이 거부되고 다음 시도에서 남은 객체를 재사용한다.

### 이관·운영 권한

`import-archive`는 큐 테이블이 있는 SQLite의 대기/종료 작업과 시도 이력도 함께 검증·복사한다. 예전 SQLite에 큐 테이블이 없으면 빈 큐로 취급한다. running lease가 남아 있으면 이관을 거부하므로 writer를 정지하고 작업을 정상 종료하거나 만료 회수한 뒤 이관한다. source 원본은 수정하지 않는다.

큐 worker 계정은 `ingest_jobs` SELECT·INSERT·UPDATE, `ingest_attempts` SELECT·INSERT와 기존 아카이브 수집 권한이 필요하다. 시도 이력의 UPDATE·DELETE·TRUNCATE는 DB trigger가 거부한다. 이관 계정의 테이블 lock 권한 범위에는 두 큐 테이블도 포함한다.

### 검증 기준

`tests/test_rag_jobs.py`는 SQLite와 실제 격리 PostgreSQL 양쪽에서 30종목×2구간 적재, 3종목 정정, 종목별 watermark·겹친 원문의 중복 방지, 같은 문서 공유, 병렬 claim, 재시도 간격·한도·다른 종목 진행, lease 만료/갱신/지연 writer 차단, 완료 기록 실패 rollback, partial/failed/empty 구분, 프로세스 재시작, SQLite→PostgreSQL 큐 이관과 실행을 검사한다. 자료·장애는 fixture이며 외부 공급자/유료 모델 호출과 실제 S3 연결은 없다.

다음 단계는 pgvector exact 검색과 임베딩 버전·비용 관리, BM25/dense/결합 평가다. 실제 공급자 연속 수집·자동 스케줄·S3 연결·대규모 성능/복원 검증은 별도 미완료 항목으로 유지한다.


2026-11-02 3일차 최종 검증: **전체 Python 564 passed / 외부 Spring 5 skipped (97.56초)**. 큐 신규 31개 검사에 SQLite/실제 PostgreSQL 양쪽 검증과 30종목 반복·정정 fixture가 포함된다. 상태 출력에 collection ID/구간을 추가한 뒤 CLI 검사도 다시 통과했다. `uv lock --check`, wheel 빌드·jobs 모듈/Alembic 0003 포함, diff 공백 검사를 확인했다. 실제 공급자·S3·유료 모델 호출은 없으며 기존 로컬 의존성 참조 venv로 검사했다. 전용 PostgreSQL은 검증 후 종료했다.


## 4일차: pgvector exact 검색·임베딩 원장·BM25 비교

S3 연결은 계속 후순위이며 로컬 원문/FTS 캐시와 PostgreSQL을 사용한다. `Retriever`는 기본 BM25를 유지하고 CLI에서 `dense`(cosine exact) 또는 `hybrid`(BM25+dense RRF)를 명시적으로 선택할 수 있다. HTTP 토론은 아직 기존 BM25 경로다. HTTP shadow 및 운영 선택 연결은 다음 단계다.

### 검색 경계

세 방식은 같은 봉인된 FTS generation, 같은 live 검수/활성 revision/관측 cutoff/시장/종목/기간 필터를 사용한다. 허용 집합을 정한 **후** 그 집합의 벡터만 PostgreSQL에서 cosine distance로 계산한다. ANN/HNSW는 아직 없으며 exact 기준선이다. 기간별 후보 20개, common 2개/short 3개, 문서·본문·duplicate-group 중복 제거와 기존 문맥 예산을 그대로 유지한다.

RRF는 raw BM25 점수와 cosine 점수를 더하지 않는다. 각 후보 순위의 `1/(60+rank)`를 합산하며, 기존 종목/시장 적합성 우선순위를 유지한다. 모든 방식은 같은 조건으로 비교한다. dense는 최소 유사도 cutoff가 아직 없어 허용 문단이 있으면 무관한 질의에도 결과를 낼 수 있다. 비교 평가의 negative case와 실제 사람 검수로 임계값/선택 정책을 정하기 전에는 품질 개선이나 운영 적합성을 주장하지 않는다.

`vector_generations`는 기존 generation ID, 임베딩 버전, 전체 chunk→embedding/hash 매핑과 실제 ready 시각을 고정한다. 전체 문단 벡터가 준비되지 않으면 ready를 만들지 않는다. 재실행은 cache/ready를 재사용한다. observed 검색은 vector ready 시각이 판단 시점 이후면 실패한다. 과거 자료를 나중에 임베딩한 비교는 `reconstructed-v1`로 명시한다. 검색 중 검수가 거절되거나 revision이 바뀌면 기존 벡터가 있어도 해당 문단은 제외한다.

검색은 **쿼리 임베딩 cache-only**다. 요청 스레드에서 유료 API를 시작하거나 timeout 뒤 추가 과금을 만들지 않는다. 쿼리 벡터는 snapshot에서 만든 기존 query_terms를 공백으로 연결한 같은 문자열로 사전 준비한다. 미준비/차원 불일치/ready 누락은 failed이며 empty로 숨기거나 BM25로 자동 전환하지 않는다.

### 버전·비용

`EmbeddingSpec`의 provider/model/애플리케이션 revision/차원/전처리/문서·질의 prefix가 의미 버전 ID에 포함된다. 문서와 쿼리 역할도 cache key에서 분리한다. 가격 revision·단가는 호출 원장에 기록하며 **단가 변경만으로 기존 벡터를 다시 생성하지 않는다.** 모델 alias의 애플리케이션 revision은 공급자 가중치 snapshot 고정을 보장하지 않는다. 공급자가 같은 alias를 변경할 가능성과 실제 모델 재현성은 별도 관리 대상이다.

벡터는 float32로 정규화하여 해시를 기록한다(길이 정규화가 아니라 저장 정밀도 통일). 잘못된 차원, NaN/Inf, zero vector를 거부한다. pgvector 값·cache hash·generation manifest의 대응도 조회 시 검증한다.

- `embedding_calls`: 입력 hash·역할·버전·단가 revision·단가·예약 금액·UTC 호출 시각.
- `embedding_receipts`: 공급자가 반환한 input token 수, 해당 단가로 계산한 금액, 결과 상태.
- `embeddings`: 검증된 벡터와 hash. 각 기록은 UPDATE/DELETE/TRUNCATE를 금지한다.
- 호출 전 PostgreSQL advisory lock으로 모든 버전의 당일 사용액+미확정 예약액을 합산하고, 명시한 일 예산 안에서만 예약한다. 예산 단위는 nano-USD이며 1 USD=1,000,000,000 nano-USD다. 실행 프로세스들은 같은 예산 정책 값을 사용해야 한다.
- UTF-8 바이트 수를 보수적인 token 상한으로 사용한다. 실제 토큰 수와 혼동하지 않으며 입력은 이 상한 8,191 이내만 허용하고 자동 truncation하지 않는다.
- SDK 자동 재시도는 끈다. timeout/프로세스 종료/응답 식별 불일치 등 사용량을 확정하지 못한 호출은 예약액을 유지하고 동일 key를 자동 재호출하지 않는다. 공급자 기록과 수동 대사 전까지 미확정으로 남는다. 자동 예약 해제·재시도·환불 추정은 없다.
- 사용량을 받은 응답의 벡터가 잘못돼도 비용은 기록한다. 기록 금액(`measured_cost_nano`)은 **측정된 token 수 × 설정 단가의 계산값**이지 공급자 청구서 확정액은 아니다. 월 예산·공급자별 영수증 대사 UI는 아직 없다.

OpenAI 어댑터는 기존 SDK를 이용하고 model·dimensions·float encoding 및 usage를 검증한다. [공식 embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)를 기준으로 구현했고, pgvector 연산·확장 설치 기준은 [공식 pgvector 문서](https://github.com/pgvector/pgvector)다. 실제 모델 선택·한국어 품질·현행 단가·계정 권한은 이번 fixture 테스트로 검증하지 않았다.

### 설치·준비·실행

아래는 `ai-worker/` 기준이다. 일반 `storage migrate`는 0004 원장/cache/manifest만 생성하며 기존 BM25 배포에 pgvector를 강제하지 않는다. `vector_cli install`은 migration 권한으로 실행하는 명시적 pgvector 설치 단계다. PostgreSQL 서버에 해당 버전용 vector 확장 파일이 먼저 설치돼 있어야 한다. 확장은 `public` schema를 사용하고 RAG 테이블은 `rag`에 둔다. 실행 계정에는 extension/DDL 권한을 주지 않는다.

```powershell
$env:BULLBEAR_RAG_OBJECT_BACKEND='local'
uv run python -m bullbear.rag.storage migrate
uv run python -m bullbear.rag.vector_cli install
```

`embedding-spec.json` 형식 예시다. **0 단가는 안전한 미설정 값이라 실제 API 호출을 거부한다.** 모델 채택과 현재 가격을 확인한 뒤 `price_revision`/`nano_usd_per_token`을 설정한다. 100만 token당 USD 단가에 1,000을 곱하면 token당 nano-USD다. OpenAI 키는 SDK의 환경변수로 제공하며 문서·인자·로그에 쓰지 않는다.

```json
{
  "provider": "openai",
  "model": "text-embedding-3-small",
  "revision": "application-embedding-policy-v1",
  "dimensions": 1536,
  "preprocessing": "identity-v1",
  "document_prefix": "",
  "query_prefix": "",
  "price_revision": "SET-VERIFIED-PRICE",
  "nano_usd_per_token": 0
}
```

다음 build/prepare-query는 캐시 미존재 시 유료 API를 호출할 수 있다. 이번 개발 세션에서는 실행하지 않았다. 숫자 예산은 실제 승인된 한도로 정한다.

```powershell
uv run python -m bullbear.rag.vector_cli build --spec embedding-spec.json --generation G.<해시> --daily-budget-nano 1000000000
uv run python -m bullbear.rag.vector_cli prepare-query snapshot.json --spec embedding-spec.json --daily-budget-nano 1000000000
uv run bullbear rag retrieve snapshot.json --generation G.<해시> --strategy dense --embedding-spec embedding-spec.json --reconstructed
uv run bullbear rag retrieve snapshot.json --generation G.<해시> --strategy hybrid --embedding-spec embedding-spec.json --reconstructed
uv run python -m bullbear.rag.vector_cli ledger --spec embedding-spec.json
```

문서 입력은 현재 chunk.text 전체이며 title을 추가하지 않는다. 긴 문단은 먼저 기존 청크 생성 단계에서 분할해야 한다. build는 개별 문단 단위로 재개 가능하지만 첫 주 구현은 공급자 batch API/대량 처리 최적화를 포함하지 않는다. 쿼리 준비 비용도 같은 원장/예산에 포함한다. standalone CLI cache 조회 결과는 기존 context 저장 설정을 따르며, compare는 PostgreSQL context 저장을 사용한다.

### 짝 비교 평가

`cases.json`은 `id`, `snapshot`(Snapshot 전체 JSON), `path`(common/short), `relevant`(정답 chunk ID 목록), `forbidden`(절대 선택하면 안 되는 chunk ID 목록), 선택적인 `expect_empty`를 가진 배열이다. 같은 snapshot/generation/검수 집합으로 BM25·dense·hybrid 세 조건을 실행하고 각각 context ID를 저장한다. 먼저 각 case의 쿼리 임베딩을 준비한다.

```powershell
uv run python -m bullbear.rag.vector_cli compare cases.json --spec embedding-spec.json --generation G.<해시> --output data/vector-comparison.json
```

compare는 검색 실패·금지 문단 선택·expect_empty 위반 중 하나라도 있으면 보고서를 저장한 뒤 종료 코드 1을 반환한다.

출력은 기간별 최종 선택 cap(common k=2/short k=3)의 Recall/MRR/nDCG, 금지 문단 선택 수, expect_empty 위반, 실패 수, context ID, 임베딩 원장과 p95를 포함한다. 실패한 검색의 relevance 점수는 null로 두고 실패 수를 따로 집계한다. 정답이 없는 case의 recall/MRR/nDCG도 null이다. p95는 **이미 준비된 검색+context 저장 시간**이며 API 임베딩·색인 빌드 시간을 포함하지 않는다. 작은 fixture의 속도를 운영 p95로 일반화하지 않는다.

합성 벡터·합성 정답 3개 case의 실제 pgvector 실행 결과는 [fixture 보고서](evaluations/rag-vector-fixture.json)에 남겼다. 이 결과는 연산·필터·평가 연결 검사다. dense가 긍정 사례를 맞혔지만 negative case 1개에 답을 반환했고 hybrid도 같은 문제를 보였다. **실제 임베딩 모델의 의미 검색 품질이나 BM25 대비 우월성을 입증하는 결과가 아니다.** 운영 기본값은 계속 BM25다.


2026-11-02 4일차 전체 검증: **581 passed / 외부 Spring 5 skipped (129.14초)**. 로컬 PostgreSQL16.4용 pgvector0.8.7을 공식 소스 `f37c13f68b57d2c3472b2214fbcff699d6d34876`에서 빌드하여 실제 extension/type/cosine 연산·테이블 불변성·무결성·cache·원장·ready/시점·짝 비교를 검사했다. 기존 Windows SDK 누락 헤더는 Microsoft SDK 패키지에서 작업용 경로로 보완했고, 빌드물·DB·다운로드는 ignored data/로 분리했다. 유료 임베딩 API 호출은 0회이며 OpenAI adapter는 가짜 client로 검증했다. `uv lock --check`, wheel 빌드·새 모듈과 Alembic0004 포함을 확인했다. 완전 신규 의존성 설치·실제 클라우드/실모델 품질/대량 지연은 미검증이다.

최종 compare CLI에 negative-case 위반 종료 코드 검사를 추가한 뒤 벡터 집중 **18 passed (30.58초)**. 패키지를 다시 빌드하고 전용 PostgreSQL을 종료했다.

## 5일차: 실제 모델 평가와 HTTP shadow

위 4일차의 실모델 미검증 상태에서 추가 진행했다. 실제 small/large API 평가 결과와 비용은 [평가 보고서](evaluations/rag-real-embedding-pilot.md)에 기록했다. 6문서·24질문에서 dense의 Recall은 1.0이었지만 답 없음 6개 모두 과잉 검색했다. 운영 기본값은 BM25이며 모델 품질 채택은 보류한다. S3 연결도 계속 미룬다.

실모델 평가 CLI는 다음과 같다. `--spec`은 여러 개 지정할 수 있다. DB migrate/vector install을 먼저 끝내고 API 키는 환경변수로 제공한다. 아래 명령은 캐시가 없으면 비용이 발생한다. 저장한 사례·입력 해시·관측 시점을 고정하며 같은 output에 변경한 자료를 넣으면 거부한다. 예산 초과는 첫 API 호출 전에 거부한다. 공급자 오류의 미확정 예약은 자동 재시도하지 않는다. 종료 코드 0은 평가 실행 완료를 뜻하며 품질 채택을 뜻하지 않는다.

```powershell
uv run python -m bullbear.rag.embedding_pilot --corpus knowledge/common-short-v1.json --cases knowledge/embedding-evaluation-v1.json --spec ../docs/evaluations/embedding-quality-v1/small-spec.json --spec ../docs/evaluations/embedding-quality-v1/large-spec.json --output data/embedding-quality-v1 --budget-nano 50000000
```

HTTP에서는 기존 RAG 활성화/세대 설정을 유지하고 다음 선택 설정을 추가한다. **기본 shadow는 꺼져 있다.** 설정 파일의 embedding version에 맞춰 같은 generation의 문서 벡터를 미리 build해야 한다. shadow는 요청 snapshot의 결정 시각보다 generation 게시/벡터 준비 시각이 늦으면 실행하지 않는다. 과거 snapshot으로 새 색인을 평가하려면 HTTP 대신 오프라인 reconstructed 평가를 사용한다.

```powershell
$env:BULLBEAR_RAG_SHADOW_ENABLED='true'
$env:BULLBEAR_RAG_SHADOW_SPEC='embedding-spec.json'
$env:BULLBEAR_RAG_SHADOW_PREPARE_QUERY='false'
$env:BULLBEAR_RAG_SHADOW_DAILY_BUDGET_NANO='0'
```

PostgreSQL DSN과 migration/pgvector도 필요하다. 기본은 준비된 query cache만 사용하고, 없으면 `shadow_unavailable`로 기록한다. 새 HTTP 질의를 임베딩하려면 `PREPARE_QUERY=true`와 양수 예산을 명시해야 한다. 예를 들어 `50000000`은 $0.05이며 문서/질문이 공유하는 기존 PostgreSQL 일일 원장에 적용된다. 프로세스 시작 때 spec을 고정하므로 설정 변경 후에는 재시작한다. 키는 SDK의 `OPENAI_API_KEY`를 사용한다.

debate/single 양쪽에서 BM25 검색 완료 후 단일 별도 작업 슬롯에 제출한다. 슬롯이 차면 `skipped_capacity`로 끝내고 대기열을 쌓지 않는다. shadow 검색은 전용 reader semaphore를 사용한다. 주 응답은 shadow 완료를 기다리지 않으며 runner에 전달되는 context, 공개 detail/SSE 및 기존 run fingerprint를 바꾸지 않는다. 같은 DB/CPU/디스크 자원을 공유하므로 대규모 부하에서 성능 간섭이 전혀 없다는 보장은 아니다.

비공개 `data/rag-shadow/<run_id>.json`에 원래 context ID, snapshot 해시/결정 시각, generation/embedding version, dense/hybrid context ID·선택 청크·BM25와의 중복/추가/제외·시간·실패 유형을 저장한다. 비교 context와 검색 감사는 PostgreSQL에 보존한다. 설정/캐시/DB/기록 실패는 주 응답을 실패시키지 않는다. 기록 파일을 웹으로 서빙하지 않는다. 프로세스 비정상 종료 시 실행 중 shadow는 유실될 수 있고 자동 재처리하지 않는다. 정상 종료는 제출된 shadow가 끝나기를 기다린다. 운영 서비스 활성화와 유료 HTTP query 호출은 이번 세션에서 수행하지 않았다.


5일차 최종 검증: 실제 PostgreSQL/pgvector 포함 **592 passed / 외부 Spring 5 skipped (139.96초)**. shadow/pilot 신규 10개는 HTTP 응답 비대기·실패 격리·single의 저장 snapshot 계약·슬롯 제한·시점·캐시·예산 거부를 검증했다. lock/diff 검사와 wheel 빌드·새 모듈 포함 확인 완료. 전용 PostgreSQL은 종료하고 실모델 pilot DB와 cache는 로컬에 보존했다.

## 6일차: 답 없음과 선택 문단 개선

`focused-evidence-v1`을 opt-in 선택 정책으로 추가했다. 기존 기본 정책은 보존하며 운영 설정은 자동으로 바꾸지 않는다. 이 정책의 `abstain`은 **RAG 배경 문단을 제공하지 않는다는 뜻**이다. 시장 Fact로 답할 수 있는 질문까지 LLM 전체 응답을 거부하는 장치는 아니다.

- 임베딩 질의는 뉴스·공시 제목을 제외한 fact label을 원래 어순으로 사용한다. 종목명·코스피·거래일 등의 고정 검색어를 자동으로 덧붙이지 않는다. 종목·시장·검수·시점 필터는 그대로 적용한다.
- BM25는 제목/본문에 의미 있는 질의 토큰이 실제로 겹치는 후보와 전체 후보의 최고 점수 대비 일정 비율 이상인 후보만 선택한다. 점수는 같은 질의·같은 generation 안에서만 비교한다.
- dense/hybrid는 모델별 최대 cosine distance와 최선 후보 대비 거리 차이 기준을 모두 통과해야 한다. RRF 순위만 높아서는 선택되지 않는다. 기본 전체 최대 2문단으로 제한하며 기존 중복/경로/문맥 예산 제한도 유지한다.
- 빈 질의나 통과 문단이 없으면 정상 `empty`와 비공개 `answerability=abstain`/사유를 남긴다. 검색/무결성/저장 실패를 답 없음으로 바꾸지 않는다. 각 후보에는 관련성 미달·최선 후보와 거리 차이·본문 불일치·점수 비율·전체 선택 제한 등의 제외 사유를 남긴다.
- 정책 JSON 전체와 내용 해시를 context에 기록한다. 벡터 정책의 `embedding_version`이 실제 모델 버전과 다르면 거부한다. BM25에서는 벡터 거리 필드를 사용하지 않는다. 새 모델·새 자료에서 임계값의 품질이 유지된다고 보장하지 않는다.

평가셋은 `knowledge/embedding-evaluation-v2.json`의 72개다. 기존 24개 development에서만 사전 고정 grid로 dense 기준 `(양성 macro F1 + 음성 specificity)/2`를 최대화하고, 정책을 파일로 고정한 뒤 새 48개 holdout을 실행한다. holdout 입력을 calibration 함수에 넘기면 거부한다. 문서/질문은 여전히 사람 검수 전 자료이며 독립 외부 평가셋이 아니다. 문서는 기존 6개로 유지했다. 비교는 같은 generation/snapshot에 기존 BM25/dense/hybrid와 개선된 세 경로를 각각 실행한다.

```powershell
uv run python -m bullbear.rag.selection_evaluation --corpus knowledge/common-short-v1.json --cases knowledge/embedding-evaluation-v2.json --spec ../docs/evaluations/embedding-quality-v1/small-spec.json --spec ../docs/evaluations/embedding-quality-v1/large-spec.json --output data/selection-quality-v2 --budget-nano 50000000
```

문서·질의 캐시가 없으면 실제 유료 호출을 한다. 사용 모델·가격·키·PostgreSQL 설정은 이전 단계와 같다. 정책 튜닝과 평가 결과는 output에 남고, 같은 output에서 자료 해시/고정 정책이 바뀌면 거부한다. 기존 query cache와 focused query cache는 입력 해시로 분리된다. 답 없음 오류는 이제 지정된 한 경로뿐 아니라 **전체 선택 묶음**으로 검사한다. bundle precision/recall·불필요 문단 수를 함께 보고하며 empty의 precision은 null, 정답이 있는데 비었으면 recall은 0이다.

선택적으로 적용하려면 해당 모델의 생성된 `*-policy.json`을 사용한다. 주 HTTP는 계속 BM25이며 다음 설정으로 BM25 문단 선택 정책만 바꿀 수 있다. shadow 설정은 주 응답과 별개다. 두 파일 모두 프로세스 시작 때 읽고 고정한다.

```powershell
$env:BULLBEAR_RAG_SELECTION_POLICY='data/selection-quality-v2/text-embedding-3-small-policy.json'
$env:BULLBEAR_RAG_SHADOW_SELECTION_POLICY='data/selection-quality-v2/text-embedding-3-small-policy.json'
```

shadow를 쓰려면 이전 절의 활성화·spec·generation·query 준비/예산 설정이 별도로 필요하다. CLI `rag retrieve`, `vector_cli prepare-query`, `vector_cli compare`에도 `--selection-policy <파일>`을 같은 값으로 전달해야 focused 질의를 재사용한다. 미지정 시 기존 질의/정책을 사용한다. 정책 선택만으로 S3나 유료 query 생성이 자동 활성화되지 않는다.


실제 실행 결과와 이전 음성 지표 정정은 [문단 선택 평가 보고서](evaluations/rag-selection-pilot.md)에 기록했다. 평가 CLI 종료 코드 0은 실행 완료이며 품질 통과가 아니다. 48개 holdout에서 개선 BM25는 정밀도 66.7%/재현율 90.0%/음성 오류 9/18, large는 68.9%/90.0%/8/18이었다. 정책 자동 활성화나 운영 전환은 하지 않았다.


6일차 검증: 실제 PostgreSQL/pgvector 포함 전체 **601 passed / 외부 Spring 5 skipped (156.64초)**. 최종 집계 필드 보완 후 selection/vector **29 passed (38.35초)**. lock/diff/wheel 포함 검사 통과. 전용 PostgreSQL은 종료하고 평가 DB/cache를 보존했다.


## 7일차: 명시 질문과 snapshot Fact 연결

`rag.evidence`의 결정적 의도/Fact 검증을 `Retriever.retrieve(request=EvidenceRequest(...))`와
인증된 `POST /rag/query`에 연결했다. 수치/예측/혼합/모호한 요청에는 문단을 대체 답변으로 제공하지 않는다.
지원하는 실제 수치는 종가·PER·PBR·ROE·TTM 영업이익률·시총이며 종목, 날짜, 단위, 유한 값,
출처, 입력 Fact 존재/단위/시점/순환을 확인한다. 다른 기간을 TTM으로 바꾸거나 새 값을 계산하지 않는다.
일치한 값과 Fact ID·출처·계보를 facts 배열로 반환한다. 개념 질문은 질문 자체로 BM25 검색을 수행한다.
신규 HTTP에서는 기본 focused 선택 정책을 적용하고, 기존 토론 경로 기본값은 바꾸지 않는다.

HTTP는 저장된 snapshot_id만 받고 수집/LLM/임베딩/shadow를 시작하지 않는다. 요청·판정·연결 근거는
불변 context/검색 감사에 저장한다. CLI는 `--request request.json`으로 같은 검증을 사용한다.
수치 조회는 FTS generation 없이도 처리하며 조회 감사 저장은 필수다. 개념 검색에만 generation이 필요하다.

구체 요청/응답은 [worker-api v0.7 추가 구현 초안](worker-api.md), 오프라인 재검사와 제한은
[Fact 연결 보고서](evaluations/rag-fact-binding.md)를 따른다. 기존 v0.6 호환이며 Spring/웹 연동·공동 승인·배포는
별도 미완료다. 외부 모델0회, S3 연결 없음. 이전72개는 재사용 회귀 자료이며 독립 holdout이 아니다.
검증용48개 오선택9→4/18, precision66.7→75.0%, recall90→83.3%, 완전누락1→3으로 보수적 판별 비용이 남았다.


7일차 검증: 실제 PostgreSQL/pgvector 포함 전체638 passed/외부 Spring5 skipped(153.05초), 최종 표현 보완 후 evidence37 passed(8.77초). lock/diff/wheel 검사 통과. 실제 모델 호출0, S3 연결0. 전용 PostgreSQL 종료.


## 후속 수정: 의도 분류 제거·명시적 조회 분리

사용자 요청으로 자연어 의도/종목/날짜/단위 추정용 정규식을 삭제했다. 기존 토큰 정규화·티커 형식 검사와
문서 관련성 기준은 유지한다. `/rag/search`는 질문을 문서 검색으로 보내며 수치를 검증했다고 표시하지 않는다.
`/rag/facts`는 ticker/metric/as_of/unit으로 Fact를 조회하며 question을 받지 않는다.
혼합 `/rag/query`는 인증 후410으로 새 경로를 안내한다. 계약은 [v0.8 구현 초안](worker-api.md)이다.

CLI의 `--request` JSON도 mode를 명시해야 한다. 예를 들어 다음 두 형태를 사용한다.

```json
{"mode":"documents","ticker":"005930","question":"PER 뜻과 현재 값의 차이"}
```

```json
{"mode":"facts","ticker":"005930","metric":"per_ttm","as_of":"2026-11-02","unit":"x"}
```

문서 요청에는 `--generation`이 필요하고 수치 요청에서는 생략할 수 있다. 추가/혼합 필드나 mode 미지정은
거부한다. 기존 저장 context는 수정하지 않으며 새 context는 explicit-evidence-v2와 명시된 요청을 기록한다.
HTTP는 저장 snapshot만 사용하고 자동 수집·LLM·임베딩·shadow를 호출하지 않는다. 기본 토론 경로는 유지한다.
새 문서 회귀 자료는 [분리 이후 결과](evaluations/rag-document-search-regression-v2.json)에 보존했다.
기존72개를 재사용한 문서 검색 검사이며 Fact 답변 정확성이나 독립 holdout 평가가 아니다.
이전48개 질문의 검색 recall은90%, 완전누락1개로 의도 관문 이전 수준으로 돌아왔다. 수치 질문에 문단이
반환되더라도 그것은 문서 검색 결과이며 수치 답변 성공으로 해석하지 않는다. 수치는 /rag/facts로 별도 요청한다.

검증: 실제 PostgreSQL/pgvector 포함 전체638 passed/외부 Spring5 skipped(150.99초),
집중73 passed(15.74초). lock/diff 검사와 wheel 빌드·새 모듈 포함 확인. 외부 모델 호출0, S3 연결0.
Spring/웹 연동·공동 계약 승인·배포는 아직 완료하지 않았다.

## 후속 연동: Spring·웹 명시적 문서/수치 조회

토론 화면의 `자료 찾아보기` 패널에서 문서 검색 또는 수치 조회를 선택한 뒤 제출한다.
Spring `/api/debates/{id}/rag/search`와 `/facts`가 해당 토론의 저장 snapshot/ticker를 찾아 워커에 전달한다.
수치 지표6개·선택 날짜·지표별 고정 단위를 전송한다. 문서는 관련 문단과 적용 범위/한계를, 수치는 값/기준일/출처를
표시한다. 자동 의도 분류·자동 조회·새 토론 생성·시장 수집·모델 호출은 추가하지 않았다.
기존 토론/판정 봉인 흐름을 유지하고 DTO에서 미정의 필드 및 다른 조회 방식의 결과를 제외한다.

실행에는 기존 HTTP 워커 설정과 `BULLBEAR_RAG_ENABLED=true`, 저장 snapshot이 필요하다.
문서 검색은 게시된 generation이 필요하며 수치 조회는 저장 Fact만 사용한다. fake 모드에서는503 안내를 반환한다.
자료가 없다고 토론을 새로 만들지 않는다. 스냅샷이 아직 없으면409, 정상 근거 부족/문서 없음은200이다.
계약/오류는 [worker-api v0.8 Spring·웹 연동](worker-api.md)에 기록했다.

검증: Spring MockMvc + 로컬 HTTP 워커 stub의8개 검사와 기존 워커 클라이언트4개 검사 통과,
웹 build/lint 통과. `web/tests/rag-smoke.mjs`는 Playwright와 로컬 Vite 서버로 실행하며 API를 전부 가로챈다.
문서/수치 요청 분리, 결과 초기화, 근거 부족, 빈 검색,503, 스냅샷 미준비,390px 화면 가로 넘침을 확인했다.
`PLAYWRIGHT_MODULE`에 설치된 Playwright index.mjs의 file URL, 필요하면 `PLAYWRIGHT_EXECUTABLE_PATH`에
Chromium 실행 파일을 지정할 수 있다. 기본 서버는127.0.0.1:5173이며 `WEB_TEST_URL`로 바꿀 수 있다.
Spring 검사는 `./gradlew test --tests '*RagIntegrationTest' --tests '*HttpWorkerClientTest' --tests '*StartDebateRequestTest'`.
Docker 미설치로 전체 DB 통합 검사는 실행하지 않았다. 실제 Python 워커+Spring+웹 전체 연결/공동 승인/배포는 미실행.
외부 모델 호출0, S3 연결0. 이는 위 이전 단계의 'Spring/웹 연동 미완료' 상태를 대체한다.

후속 실제 연동 검증도 완료했다: [실제 워커·Spring·웹 연결 보고서](evaluations/rag-live-e2e.md).
종가 단위 정의를 원본과 같은 KRW/share로 정정했으며 저장 종가/PER 화면 표시와 문서 검색을 확인했다.
문서는 게시 이후 별도 검증 snapshot을 사용했고 과거 snapshot의 시간 검증은 유지했다.
브라우저15개 검사·워커74개 회귀·웹 build/lint 통과, 외부 모델/S3 호출0. 운영 배포는 미실행.

다음 운영 순서와 다종목 연결 검증은 [색인 게시·스냅샷 운영 안내](RAG-PUBLICATION-RUNBOOK.md)에 정리했다.
`rag check-generation`으로 게시 무결성/시점과 여러 저장 스냅샷의 적합성을 읽기 전용으로 확인한다.
005930 실제 저장본·000660 기존 모의 저장본의 원본을 보존하고 게시 이후 새 테스트 복사본으로 종목 격리를 확인했다.
이후 운영 준비 작업에서 스냅샷별 generation 고정/라우팅을 구현했다. 과거 미연결 자료는 당시 observed context를
근거로 명시적으로 이관하며, 상세 정책은 [운영 안내](RAG-PUBLICATION-RUNBOOK.md)를 따른다.

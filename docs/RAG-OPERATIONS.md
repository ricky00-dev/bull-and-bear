# RAG 저장소 설정·이관·평가

2026-11-02 코드 기준. 현재 기본은 SQLite 아카이브/컨텍스트, 로컬 객체 저장, BM25 검색이며 RAG는 기본 비활성이다.
PostgreSQL·S3 어댑터·pgvector와 HTTP shadow는 선택 기능이다. 구현됐다는 사실은 운영 배포·품질 채택을 뜻하지 않는다.

- 자료 작성·검수: [RAG-DATA](RAG-DATA.md).
- 색인 게시, snapshot 연결, 교체·복구: [게시·복구 안내](RAG-PUBLICATION-RUNBOOK.md).
- 준비 상태와 검증 한계: [준비 감사](RAG-READINESS-AUDIT.md), [평가 기록](evaluations/README.md).
- 일차별 변경과 당시 시험 결과: [보관된 구현 일지](archive/RAG-WEEK-ONE.md).

명령은 `ai-worker/`에서 실행한다. `<해시>` 등 자리표시자는 실제 값으로 바꾼다.
아래 설정 예시는 운영 활성화나 유료 호출을 자동으로 수행하지 않는다.

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
- 현재 이관 도구는 컨텍스트 DB 전체를 메모리에 읽는다. 대규모 이관용 streaming/staging은 아직 구현하지 않았다.
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


## 객체 저장과 아카이브 이관

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

## 캡처 작업 큐

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

## 선택적 벡터 검색과 비교 평가

아래는 `ai-worker/` 기준이다. 일반 `storage migrate`는 원장/cache/manifest를 포함한 RAG 스키마를 이관하며 기존 BM25 배포에 pgvector 확장을 강제하지 않는다. `vector_cli install`은 migration 권한으로 실행하는 명시적 pgvector 설치 단계다. PostgreSQL 서버에 해당 버전용 vector 확장 파일이 먼저 설치돼 있어야 한다. 확장은 `public` schema를 사용하고 RAG 테이블은 `rag`에 둔다. 실행 계정에는 extension/DDL 권한을 주지 않는다.

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

다음 build/prepare-query는 캐시 미존재 시 유료 API를 호출할 수 있다. 숫자 예산은 실제 승인된 한도로 정한다.

```powershell
uv run python -m bullbear.rag.vector_cli build --spec embedding-spec.json --generation G.<해시> --daily-budget-nano 1000000000
uv run python -m bullbear.rag.vector_cli prepare-query snapshot.json --spec embedding-spec.json --daily-budget-nano 1000000000
uv run bullbear rag retrieve snapshot.json --generation G.<해시> --strategy dense --embedding-spec embedding-spec.json --reconstructed
uv run bullbear rag retrieve snapshot.json --generation G.<해시> --strategy hybrid --embedding-spec embedding-spec.json --reconstructed
uv run python -m bullbear.rag.vector_cli ledger --spec embedding-spec.json
```

문서 입력은 현재 chunk.text 전체이며 title을 추가하지 않는다. 긴 문단은 먼저 기존 청크 생성 단계에서 분할해야 한다. build는 개별 문단 단위로 재개 가능하지만 현재 구현은 공급자 batch API/대량 처리 최적화를 포함하지 않는다. 쿼리 준비 비용도 같은 원장/예산에 포함한다. standalone CLI cache 조회 결과는 기존 context 저장 설정을 따르며, compare는 PostgreSQL context 저장을 사용한다.

### 짝 비교 평가

`cases.json`은 `id`, `snapshot`(Snapshot 전체 JSON), `path`(common/short), `relevant`(정답 chunk ID 목록), `forbidden`(절대 선택하면 안 되는 chunk ID 목록), 선택적인 `expect_empty`를 가진 배열이다. 같은 snapshot/generation/검수 집합으로 BM25·dense·hybrid 세 조건을 실행하고 각각 context ID를 저장한다. 먼저 각 case의 쿼리 임베딩을 준비한다.

```powershell
uv run python -m bullbear.rag.vector_cli compare cases.json --spec embedding-spec.json --generation G.<해시> --output data/vector-comparison.json
```

compare는 검색 실패·금지 문단 선택·expect_empty 위반 중 하나라도 있으면 보고서를 저장한 뒤 종료 코드 1을 반환한다.


## HTTP shadow

기본은 비활성이다. 같은 generation의 문서 벡터와 embedding spec을 준비한 뒤 선택적으로 설정한다.

```dotenv
BULLBEAR_RAG_SHADOW_ENABLED=true
BULLBEAR_RAG_SHADOW_SPEC=embedding-spec.json
BULLBEAR_RAG_SHADOW_PREPARE_QUERY=false
BULLBEAR_RAG_SHADOW_DAILY_BUDGET_NANO=0
```

기본은 준비된 query cache만 사용하며 캐시가 없으면 shadow_unavailable로 기록한다.
새 질의 임베딩은 PREPARE_QUERY=true와 명시적 양수 예산이 필요하다. PostgreSQL의 임베딩 원장을 사용하며
토론 모델의 비용 장부와 별개다. spec은 시작 시 고정하므로 바꾼 뒤 재시작한다.
실모델 평가 결과와 채택 보류 근거는 [임베딩 파일럿](evaluations/rag-real-embedding-pilot.md)에 보존한다.

## 문서 검색과 수치 조회

HTTP는 저장된 snapshot에 대해 `/rag/search`와 `/rag/facts`를 분리한다. 혼합 `/rag/query`는 410을 반환한다.
문서 검색 결과를 검증된 수치로 취급하지 않는다. 수치 조회는 metric/as_of/unit을 명시하고 generation 없이도 가능하다.
두 경로 모두 자동 수집·LLM·임베딩·shadow를 호출하지 않는다. 정확한 요청/응답은 [워커 계약](worker-api.md)을 따른다.
CLI `rag retrieve`의 `--request`에도 mode를 명시한다.

```json
{"mode":"documents","ticker":"005930","question":"PER 뜻과 현재 값의 차이"}
```

```json
{"mode":"facts","ticker":"005930","metric":"per_ttm","as_of":"2026-11-02","unit":"x"}
```

```powershell
uv run bullbear rag retrieve snapshot.json --request request.json --generation G.<해시>
# mode=facts인 request.json이면 --generation 생략 가능
```

HTTP의 과거 snapshot은 최초 연결된 generation을 사용한다. CLI의 `--reconstructed`는 오프라인 재구성 평가용이며
운영 HTTP의 시점 검증을 우회하는 옵션이 아니다. 게시·연결 순서는 게시·복구 안내를 따른다.

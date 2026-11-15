# 최소 RAG 원문·관측 이력 수집 평가

2026-10-30 · `feat/worker-rag-ingest` · 기준 `develop` 83247f2

## 구현 범위

기존 FastAPI·토론·스냅샷·Spring 계약을 유지하고, `ai-worker/src/bullbear/rag/`에 별도의 로컬 원문 아카이브를 추가했다. 실제 뉴스 API 호출, 본문 크롤링, 스케줄러, 검색 색인, 임베딩, LLM, LangGraph는 이 변경에 포함하지 않는다. 현재 공급자의 `NewsArticle` 제목·요약과 `Disclosure` 제목·제출인·접수일을 가져오며 제목만 받은 자료를 본문으로 표시하지 않는다.

저장 위치는 `Settings.data_dir/rag/rag.sqlite3`와 `objects/<SHA256>`이다. 의미 있는 원천 필드의 canonical JSON으로 내용 해시를 계산하고 관측 시각·수집 작업 ID·원본 응답의 부수 필드는 내용 해시에서 제외한다. 원본 항목과 수집 응답은 `collection_items.input_json`과 `collection_runs.input_json`에 보존한다. 내용 메타데이터 정정은 새 revision이 된다.

## 공개 내부 API

| API | 계약 |
|---|---|
| `DocumentInput` | 안정적인 `source/source_item_id`, 종류, 제목·텍스트, `source_ref/url`, 단위, 발행·수정·관측 시각, 정밀도, 제공 텍스트 수준, 공개 확인 여부 |
| `CollectionBatch` | 고유 작업 ID, 공급자·질의·수집 구간, 시작/완료 시각, `current/archive`, 결과·coverage·페이지 수, 원본 항목, 안전한 오류 코드, 선택적 완료 watermark |
| `RagStore(directory)` | 별도 SQLite WAL DB와 원문 objects 생성, schema v1 마이그레이션, 상위 버전 거절, context manager 지원 |
| `import_collection(batch)` | 작업·문서·revision·활성화·원본 관측·watermark를 한 트랜잭션에 기록; 같은 작업 ID와 같은 입력은 재사용하고 다른 입력은 거절 |
| `document_at(document_id, decision_at)` | 그 시점까지 관측한 최신 활성화/철회 상태를 먼저 선택; 당시 공개·관측·원문 무결성이 확인되는 현재 버전만 반환, 이전 안전 버전으로 조용히 폴백하지 않음 |
| `revision(revision_id)` | archive 버전도 조회 가능; DB canonical 내용과 파일의 해시·경로 무결성 검사 |
| `record_event(...)` | 공급자에서 확인한 `withdrawn/deleted`만 명시 기록; 검색 목록에서 빠진 것을 삭제로 추정하지 않음 |
| `add_chunk(ChunkInput)` | 저장된 원문에 실제 존재하는 문단을 원문 위치·분할 정책 버전과 함께 불변 저장; 자동 분할·색인은 하지 않음 |
| `annotate(AnnotationInput)` | 문단의 `common/short/medium/long` 복수 태그, 주제·종목·시장·적용 범위·제한, 표본/예측/보유 기간과 단위, 검수 이력을 불변 추가 |
| `annotation_at(chunk_id, decision_at)` | 당시 최신 검수 결과가 승인되고 유효 구간을 통과할 때 반환; 최신 거절/만료 뒤 과거 승인으로 폴백하지 않음 |
| `open_reader()` | 호출자가 닫는 독립 read-only 연결; `BEGIN`으로 여러 조회를 하나의 WAL 스냅샷으로 묶을 수 있음 |
| `news_document(...)`, `disclosure_document(...)` | 기존 공급자 자료형 → `DocumentInput`; 한국 공시는 날짜만 보존하고 공개 시각을 만들어 넣지 않음 |
| `sync_payload(store, payload)` | 로컬에 캡처한 공급자 항목을 변환; 일부 잘못된 항목은 정상 항목과 구분해 partial/failed 및 거절 수·원본을 보존 |

`annotation_at`은 검수 이력 조회 API다. 후속 검색기는 먼저 `document_at`으로 최신 공개 버전과 시점을 확정한 다음 해당 버전의 문단과 주석만 조회해야 한다. 아카이브의 모든 revision을 직접 검색 후보로 사용하면 안 된다. 원문이 변경된 뒤 새 버전 검수가 끝나지 않았더라도 과거 버전이 자동으로 최신 버전을 대신하지 않게 구성한다.

## SQLite v1

실행 가능한 DDL과 마이그레이션은 `rag/store.py`의 `SCHEMA`, `SCHEMA_VERSION=1`, `schema_migrations`, SQLite `PRAGMA user_version`에 있다.

- 원문: `documents`, `document_revisions`, `document_events`
- 수집: `collection_runs`, `collection_items`, `source_watermarks`
- 후속 검색 입력: `chunks`, `chunk_annotations`, `chunk_horizons`

원문·관측 사건·수집 작업·문단·주석은 UPDATE/DELETE 방지 트리거로 보호한다. watermark만 완료 구간을 따라 갱신한다. 각 Store 연결의 쓰기는 잠금과 `BEGIN IMMEDIATE`로 직렬화하며 여러 연결은 SQLite의 writer 직렬화에 따른다. reader는 별도 read-only WAL 연결을 쓴다.

원문 파일은 writer 잠금을 잡기 전에 임시 파일·fsync·원자적 이름 변경으로 준비하고, 참조와 수집 상태는 DB 커밋으로 함께 공개한다. 실패하면 참조 없는 content-addressed 파일이 남을 수 있지만 완료 DB 행이 없는 파일은 검색 입력이 아니다. 이번 범위에 자동 정리·백업 기능은 없다.

## 시점·증분 정책

- `source/source_item_id`가 문서 정체성이고 내용 해시가 버전 정체성이다. URL은 scheme/host 소문자와 fragment 제거만 적용한다. 기사 ID를 담을 수 있는 query는 제거하지 않는다.
- revision의 최초 저장 관측값은 덮어쓰지 않고 `first_recorded_observation_at`으로 감사 조회한다. 조회용 `first_observed_at`은 current 수집 항목에 보존된 실제 관측 증거의 최솟값으로 계산하므로 늦게 도착한 과거 캡처에도 시점 재생이 맞는다. A→B→A에서는 A 행을 재사용하고 새 `revision_activated` 사건으로 현재 버전을 표시한다.
- 오래된 캡처를 가져오는 기본 모드는 `archive`다. 현재 자료로 확인한 공급자 응답만 명시적으로 `current`로 가져온다. archive 행은 현재 활성화와 온라인 watermark를 변경하지 않는다.
- 같은 문서의 다른 버전을 같은 관측 시각에 활성화하는 모호한 입력은 거절한다. 모든 시각은 timezone-aware로 받고 UTC로 비교한다. 관측 시각은 수집 생산자가 실제 확인한 시각이어야 하며 이번 로컬 importer가 과거 관측 사실을 인증하지는 않는다.
- 날짜만 있는 한국 공시는 공개일을 보존하고 첫 관측 이후부터 쓴다. 미래 공개일·미래 공개/수정 시각·공개 미확인·공개 시점 미상은 보존하되 해당 관측을 격리한다. 활성화 사건은 정확한 수집 항목과 연결되며 같은 내용이 나중에 정상 공개 시점에 재확인되면 새 활성화로 사용할 수 있다. 늦게 가져온 잘못된 과거 캡처는 당시 입력에 들어가지 않는다. 날짜 경계는 현재 한국 공급자 기준 KST이며 타 국가의 날짜만 있는 자료는 공급자별 날짜 해석을 추가한 뒤 연결해야 한다.
- `completed/empty`는 확인된 응답과 complete coverage를 요구한다. 입력 없이 시작한 작업, 페이지 상한, 오류, 부분 성공은 `empty`로 바꾸지 않는다. 잘못된 항목과 원본은 수집 감사 기록에 남긴다.
- watermark는 current의 complete/empty, 확정 구간의 `completed_through`가 있을 때만 전진한다. 기존 완료 끝과 새 시작 사이에 공백이 있으면 유지하며, 과거 구간 재수집으로 뒤로 이동하지 않는다.
- 현 NAVER `.search()`의 고정 페이지 상한과 반환 목록만으로 전체 아카이브 coverage를 보장할 수 없다. 생산자가 페이지 범위를 확인하지 못하면 `partial`, `safe_error=provider_coverage_unverified` 등으로 입력해야 한다. 이 importer는 기사가 모두 수집됐는지 추정하지 않는다.

## 로컬 명령

`python -m bullbear.rag.cli`와 기존 `bullbear rag` 진입점이 같은 코드를 사용한다. `--data-dir`에는 worker 데이터 디렉터리를 지정하며 `rag/`는 내부에서 추가한다. 명령은 JSON 파일만 읽고 공급자 API를 호출하지 않는다.

```powershell
python -m bullbear.rag.cli --data-dir data import capture-normalized.json
python -m bullbear.rag.cli --data-dir data sync capture-provider.json
python -m bullbear.rag.cli --data-dir data inspect
python -m bullbear.rag.cli --data-dir data inspect --collection capture-20261030-005930
python -m bullbear.rag.cli --data-dir data inspect --document D.<hash> --at 2026-10-30T16:40:00+09:00
```

`import`는 `CollectionBatch` JSON을, `sync`는 아래처럼 현재 공급자 자료형을 캡처한 JSON을 받는다. 캡처에는 공개된 응답 항목만 넣고 API 키·인증 헤더·요청 정보는 넣지 않는다. 이 예시의 partial 상태는 현재 공급자 목록의 전체 범위를 보장하지 않는다는 뜻이며, partial/failed 명령은 기록을 보존한 뒤 종료 코드 1을 반환한다. 정상 confirmed-empty는 items=[], status=empty, coverage=complete, pages>=1로 명시해야 한다.

```json
{
  "collection_id": "capture-20261030-005930",
  "source": "naver-news",
  "query_key": "005930",
  "kind": "news",
  "ticker": "005930",
  "window_start": "2026-10-29T16:00:00+09:00",
  "window_end": "2026-10-30T16:00:00+09:00",
  "started_at": "2026-10-30T16:00:00+09:00",
  "observed_at": "2026-10-30T16:00:01+09:00",
  "finished_at": "2026-10-30T16:00:02+09:00",
  "observation_mode": "current",
  "status": "partial",
  "coverage": "partial",
  "pages": 1,
  "safe_error": "provider_coverage_unverified",
  "items": [
    {
      "source_ref": "https://example.com/news/1",
      "url": "https://example.com/news/1",
      "title": "삼성전자 기사 예시",
      "summary": "공급자가 제공한 요약만 보존한다.",
      "published_at": "2026-10-30T15:50:00+09:00"
    }
  ]
}
```

## 검증

전용 worktree `BAB/.worktrees/worker-rag-ingest`의 `ai-worker`를 cwd로 사용했다. 루트 `.venv`의 Python 실행 파일을 사용하되 `PYTHONPATH`를 해당 worktree의 `ai-worker/src`로 명시했으며, `bullbear.rag.__file__`이 그 경로임을 확인했다. 루트 checkout의 코드를 테스트한 것이 아니다.

```powershell
$env:PYTHONPATH = 'C:\Users\weun2\OneDrive\문서\ChatGPT\BAB\.worktrees\worker-rag-ingest\ai-worker\src'
& 'C:\Users\weun2\OneDrive\문서\ChatGPT\BAB\ai-worker\.venv\Scripts\python.exe' -m pytest tests/test_rag_ingest.py -q
& 'C:\Users\weun2\OneDrive\문서\ChatGPT\BAB\ai-worker\.venv\Scripts\python.exe' -m pytest -q
```

새 아카이브 테스트 27개 통과(7.89초). 최종 전체 Python 테스트는 **118개 통과·외부 Spring 연동 2개 건너뜀(44.51초)**이다. 건너뛴 테스트는 실행 중인 Spring/PostgreSQL/HTTP fixture 환경을 명시해야 한다. `git diff --check`도 통과했다.

| 검증 대상 | 확인 내용 |
|---|---|
| 멱등·정정 | 같은 collection 재생, 새 collection의 동일 내용, A→B→A, 의미 있는 메타데이터 정정 |
| 시점 | 미래·미확인 자료 격리, 정정본을 과거에 소급하지 않음, archive 비활성, 철회 전후 재생, 당일 관측 공시 사용 |
| 수집 감사 | 정상 빈 응답/입력 누락/전체 오류/부분 오류 구분, 원본 보존·거절 수, watermark 공백·역행 차단 |
| 정합성 | 원문 파일 손상 fail-closed, collection 전체 rollback, 불변 행 보호, 동시 관측 충돌 거절 |
| 후속 검색 경계 | 문단 원문 대조, 복수 태그·기간 단위, 승인/거절/만료 이력과 과거 승인 비부활 |
| 운영 기반 | WAL reader 스냅샷, document_at의 다중 조회 중 동시 정정에도 같은 read 스냅샷 유지, 여러 Store 동시 멱등 쓰기, 스키마 재개방·상위 버전 거절 |
| CLI | 실제 worktree 진입점, local sync/import/inspect, 네트워크 금지 stub, 오류에서 입력 비밀값 비노출 |

## 미확인과 다음 작업

실제 공급자 호출·실제 파일 장기 축적·외부 Spring/PostgreSQL 통합은 실행하지 않았다. 현재 공급자 API의 완전 수집 여부, 기존 오래된 기사의 정정 탐지, source timestamp 신뢰도는 생산자 구현과 실제 운영에서 확인해야 한다. 손상 원문은 자동 복원하거나 이전 버전으로 대체하지 않는다.

후속 검색기는 이 스키마를 재사용하고, 별도 세대별 색인·검색 기록·불변 KnowledgeContext를 추가한다. DB 연결이나 LLM 객체는 저장 상태에 넣지 않는다. 검색 전에 현재 공개 revision과 검수 결과를 확정하고, 과거 시점 전용 corpus에서 순위를 계산하며, 기존 토론의 입력은 새 수집으로 바꾸지 않는다. 기사·공시 본문 확보와 토론 Fact 투영은 별도 작업이며 현재 HTTP 응답/필드와 워커 계약은 변경하지 않았다.

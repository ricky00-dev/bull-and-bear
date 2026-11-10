# 공통·단기 RAG 실제 검색 경로 평가

2026-10-30 KST. `feat/worker-rag-retrieval`, 독립 worktree에서 구현했다.
이 기록은 검색·연결 구현의 검증이며 **P1 운영 활성화 또는 예측 성과 승인 기록이 아니다.**
`BULLBEAR_RAG_ENABLED=false` 기본값을 유지한다.

## 이관 확인과 범위

- AGENTS.md를 읽고 Git Bash로 `scripts/session-brief.sh` 실행. 기본 WindowsApps bash 실행은 실패했으나
  `C:/Program Files/Git/bin/bash.exe`로 성공했다. PR 요약은 없음/로그인 필요로 표시되어 별도 확인하지 않았다.
- `git fetch origin` 성공. 원격 `feat/worker-rag-context` HEAD는
  `2f6af9fcc779352580d2a4d3f1c026cc490826d8`, 이후 커밋 없음. 원격 설계 브랜치의 `9c91086`도 확인했다.
- 원본 develop 체크아웃은 변경하지 않았다. 이관 HEAD에서 새 기능 브랜치를 만들어
  `bff5e8c/1f96a6c/639fd15/0791ff5` 선행을 그대로 보존했으며 중복 cherry-pick하지 않았다.
  새 develop의 안정화 `38a4516`과 머지 `447cdf4`는 이 작업에 적용하지 않았다.
- 체크포인트·WORKLOG·설계·ROADMAP·worker-api를 확인했다. Spring 계약, 시장 Fact,
  7거래일 KOSPI 초과수익 본판정/3거래일 보조, 날짜별 토론 재사용을 변경하지 않았다.
- 구현·통합 검증은 이 세션, 공식 문서·논문·GitHub 조사는 별도 세션에서 수행했다.
  [조사 근거와 적용/보류 판단](worker-rag-retrieval-research.md).

## 구현 동작

`Retriever(store).retrieve(snapshot, generation_id=...)`는 snapshot을 복사하고 질의를 고정한다.
knowledge/research만 허용하며 당시 활성 revision·공개/실제 관측·최신 검수·유효 기간을 재확인한다.
세대 이후 새 검수나 정정으로 구성원이 달라졌으면 이전 자료로 대체하지 않고 제외한다.
시점 뒤에 관측된 정정·검수는 과거 검색에 영향을 주지 않는다.

시장 KR/KOSPI/global 명시 문단만 허용하고, 종목 지정 문단은 ticker 일치를 요구한다.
시장 태그가 없는 문단은 보수적으로 제외한다. common/short를 따로 검색하되 필터를 먼저
SQL 후보 집합에 반영한다. 각 경로 후보 20개, common 2개/short 3개, 동일 문단·문서·사건 그룹
중복 제거, 본문 합계 6000자와 렌더링 UTF-8 byte 보수 상한 2000 중 먼저 도달하는 제한을 적용한다.
문단을 자르지 않는다. UTF-8 byte 수는 실제 사용 토큰이 아니며 모델별 실사용량은 미측정이다.

정렬은 종목 지정/KR/global 적합성 등급 → 해당 경로 BM25 → chunk_id이며 출처 우선순위는
검수 통과 출처끼리 동일하다. 질의·별칭·정책·실제 점수·후보·선정/제외 사유를 기록한다.
배경 역할은 `background_only`이고 공개 [E#] 또는 새 시장 근거로 투영하지 않는다.

세대는 별도 FTS5 DB와 ready 기록을 임시 디렉터리에서 완성·동기화한 뒤 디렉터리 rename으로
함께 공개한다. 준비 중 파일은 검색하지 않는다. 동시 발행은 기존 완성 세대를 검증·재사용한다.
전체 DB SHA256으로 members/FTS 변경을 검출하고, 원문 객체는 검색 시에도 검증한다.
SQLite·정규화·인덱스 버전과 고정 corpus로 과거 BM25를 보존한다.
**이관 v1 색인은 v2로 재발행해야 한다.** 기존 색인을 조용히 변환하거나 삭제하지 않는다.

기본 `observed-v1`은 세대 cutoff뿐 아니라 실제 `committed_at <= decision_at`을 요구한다.
과거 자료로 지금 구성한 평가는 명시적 `reconstructed-v1`으로만 가능하며
`historical_reconstruction` 경고를 남긴다. HTTP 운영 경로는 이 우회를 사용하지 않는다.
생산자가 기록한 공개·관측·검수 시각의 진실성까지 증명하지는 않는다.

검색은 monotonic 1초 deadline과 SQLite progress handler, 최대 4개 reader를 사용한다.
호출자가 timeout을 확정하면 부분/늦은 결과는 버리고 빈 timeout 컨텍스트를 저장한다.
정상 무관/필터 탈락은 empty, 손상/누락은 failed, 시간 초과는 timeout으로 구분한다.
HTTP는 기존 보수적 계약대로 failed/timeout이면 runner를 시작하지 않는다.
지식 필수 benchmark는 empty/failed/timeout을 RAG 추가 성공으로 집계하지 않는다.

검색 감사와 컨텍스트는 `rag/contexts.sqlite3`에 원자적으로 저장한다. 지연은 시도별 감사에,
결정론적 내용은 context_id에 포함한다. `load_context`/CLI replay는 검색 없이 해시 검증된
원래 JSON을 반환한다. 기존 HTTP RunAudit의 고정 입력과 날짜별 캐시를 유지한다.
기록 실패 시 저장되지 않은 성공을 반환하지 않는다. RAG 저장/재생 소스도 실행 fingerprint에 포함했다.

## 실행과 실제 결과

Python 3.12.15, pytest 9.1.1. 원본 체크아웃의 `.venv/Scripts/python.exe`를 실행하되
`-o pythonpath=src`로 **독립 worktree 소스**를 검증했다. 키·.env·원본 데이터 복사와 유료 호출은 없다.
worktree의 임시 파일 쓰기는 sandbox 권한으로 차단되어 승인 후 실행했다.
초기 테스트 디렉터리 부모 누락과 Windows 읽기 전용 fsync 오류를 확인·수정한 뒤 재검증했다.

| 검증 | 실제 결과 |
|---|---|
| 세대/컨텍스트 기존 회귀 | 4 passed, 0.53초 |
| 최초 실제 검색·HTTP/benchmark | 17 passed, 12.82초 |
| 별칭/NFC·CLI·장애 포함 집중 회귀 | 27 passed, 12.77초 |
| 동시 발행·반복 검색까지 집중 회귀 | 29 passed, 14.93초 |
| 발행 원자성 최종 보완 전 전체 | 223 passed, 2 skipped, 24.62초 |
| 발행 원자성·감사 fingerprint 보완 후 최종 전체 | **225 passed, 2 skipped, 25.39초** |

위 묶음은 중복을 포함하므로 합산하지 않는다. `git diff --check`도 통과했다.
외부 Spring 테스트 2개는 별도 환경이 없어 건너뛴다.

검증한 시나리오: 경로/후보/예산 상한, 정확한 원문 보존, 외국 문서 25개가 있어도 적격 문단 검색,
종목/시장/자료형/기간·미래 공개 필터, 미래 정정·늦은 관측·미래 검수 제외, 최신 반려/만료/철회,
세대 뒤 새 자료 추가의 BM25·context 불변, 원문/members/FTS/ready 손상, 무관한 검색 empty,
미래 세대와 당시 미발행 세대 구분, 1초 정지 I/O 모사·긴 SQLite 질의 중단,
저장 실패·발행 실패·동시 발행, CLI 저장/재생, 검색 후 변경에도 HTTP 당일 재사용과 비공개 경계.

### 50문서·30회 반복 검색

아래는 당시 실측 기록이다. 현재 회귀 테스트는 검색 재생의 일관성과 시간 제한을 별도로 검증한다.

고정된 synthetic corpus(common 25/short 25), 한 snapshot/세대, 같은 프로세스에서 순차 실행했다.
모든 검색은 실제 SQLite/원문/저장 경로이며 네트워크·LLM은 없다.

| 지표 | 실측 |
|---|---:|
| 완료 | 30/30 |
| 고유 context_id | 1 |
| 검색 p95 (nearest-rank, 29번째/30) | 0.031초 |
| 검색 최대 | 0.032초 |
| 저장 포함 호출 p95 | 0.047초 |

이는 작은 로컬 corpus의 warm 반복 측정이다. 운영 동시 부하·대량 corpus·스토리지 장애의 SLA를
증명하지 않는다. caller wait 제한은 OS I/O 강제 종료가 아니며 정확한 실시간 1초 보장도 아니다.
검색 감사 저장은 검색 한도 밖이다. 늦은 reader는 저장하지 않고 가능한 시점에 중단하며 최대 4개다.

### 실제 검색 → 비교 실행기

`test_real_archive_search_benchmark_and_saved_report`에서 원문 수집·문단·검수·세대·검색을 거쳐
얻은 컨텍스트를 `run_rag_comparison`에 전달했다. 모델만 fixture이며 검색기는 대체하지 않았다.
실측 원본은 로컬 `.pytest_cache/retrieval-final/test_real_archive_search_bench0/comparison/rag-comparison.json`.
원시 실행 데이터는 커밋하지 않는다. 실행 당시 HEAD는 이관 커밋+dirty이며 report에 모듈 해시를 보존한다.

| 조건 | 완료 | fixture 요청 | 셀 전체 | single 생성 | debate 생성 |
|---|---:|---:|---:|---:|---:|
| none | 2/2 | 16 | 0.125235초 | 0.005803초 | 0.028903초 |
| common_short | 2/2 | 16 | 0.126132초 | 0.003819초 | 0.029902초 |

4/4 완료, 최대 요청 상한 480, `usage_status=fixture_no_real_usage`, `cost_usd=null`,
`cost_status=not_priced_use_recorded_actual_usage`, `accuracy=null`이다.
비용 0달러나 예측 정확도 100%가 아니다. fixture HOLD/0.5는 예측 결과나 보정 확률이 아니다.
실제 검색은 성공했지만 이 문단을 사람이 검수한 운영 금융지식 정답 집합으로 주장하지 않는다.

HTTP 평가는 실제 RagStore/GenerationIndex/Retriever/replay와 FastAPI TestClient를 사용한다.
시장 데이터와 runner만 fixture이고, 과거 NOW에 대한 발행 시계는 테스트에서 명시적으로 모사했다.
컨텍스트가 runner에 전달되고 실행 중 corpus 변경 뒤에도 같은 날짜 요청은 기존 토론을 재사용한다.
HTTP/SSE에 지식 본문·context_id가 추가되지 않음을 확인했다. 실제 Spring 봉인 동작은 외부 통합 미검증이다.

## 재현 방법

```powershell
cd ai-worker
python -m pytest -o pythonpath=src tests/test_rag_retrieval.py tests/test_rag_context_index.py -q -s
python -m pytest -o pythonpath=src -q
```

검수한 로컬 자료를 기존 ingest API로 준비한 뒤 사용할 내부 CLI:

```text
bullbear rag --data-dir data publish --as-of 2026-10-30T16:00:00+09:00
bullbear rag --data-dir data retrieve <snapshot.json> --generation <G.id>
bullbear rag --data-dir data retrieve <past-snapshot.json> --generation <G.id> --reconstructed
bullbear rag --data-dir data replay <KCTX.id>
```

replay 출력은 비공개 전체 문단이다. 공개 HTTP 엔드포인트는 추가하지 않았다.
판단 시각 뒤 발행한 세대를 기본 retrieve로 사용하면 failed가 정상이다.

## 남은 P1 운영 검증과 한계

1. 실제 검수 corpus와 자연 질문 정답 집합의 Recall@K/MRR, 한국어 조사·복합명사 누락 평가.
2. 명시 공급자/모델·실제 tokenizer·기존 대화/출력 여유·가격표·호출 상한을 고정한 실모델 비교.
   이번에는 실제 모델·미산정 가격을 임의 선택하거나 유료 호출을 하지 않았다.
3. 실제 Spring/DB·시장 공급자·운영 키 연결, 전향 완료율·p95·비용 허용 기준을 정하고 검증.
4. 성숙한 7거래일/3거래일 결과·확신도 보정. 기존 시세 기업행사·재무 정정본 한계는 별도 유지.

이 조건들이 충족되기 전 RAG는 기본 비활성이다. P2 위험 검토·LangGraph·벡터·자동 개선으로
범위를 늘리지 않았다. push·PR·develop 병합은 하지 않는다.

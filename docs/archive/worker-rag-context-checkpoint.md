# 공통·단기 RAG 이관 체크포인트 (WIP)

> 보관 기록: 작성 당시 계획·구현·검증 상태를 보존합니다. 현재 실행 절차는 [문서 안내](../README.md)를 따릅니다.

2026-10-30 KST. 브랜치 `feat/worker-rag-context`, 작업 공간 `.worktrees/worker-rag-context`.
사용자의 현재 작업 푸시·다른 컴퓨터 이관 요청에 따라 구현을 중단하고 보존한다.
**P1 완료나 운영 활성화 승인 기록이 아니다. `BULLBEAR_RAG_ENABLED=false`를 유지한다.**

## 선행 커밋과 보존 범위

`develop` 83247f2에서 새 브랜치를 만들고 다음을 명시적으로 적용했다.

| 원본 선행 | 이 브랜치 적용본 | 내용 |
|---|---|---|
| dc4040f | bff5e8c | HTTP 실행 감사 |
| e66c062 | 1f96a6c | 동일 스냅샷 단일/토론 비교 |
| 6edd8ec | 639fd15 | 비교 실행 안내·평가 |
| c7eb1a7 | 0791ff5 | 원문/revision/관측/검수 저장 |

WORKLOG 충돌은 모든 항목을 보존해 해결했다. 원본 체크아웃과 다른 작업 공간을 수정하지 않았다.
38a4516 안정화 커밋은 이 브랜치의 선행으로 적용하지 않았다. 상세 설계는
`docs/worker-rag-design` 브랜치 9c91086의 `docs/worker-rag-design.md`를 참조한다.
이 채팅은 push·PR·develop 병합을 수행하지 않는다. 원격 보존은 부모 채팅이 맡는다.

## 현재 구현과 실제 동작 경로

- `rag/context.py`: canonical JSON 문자열을 가진 불변 KnowledgeContext, 결정론적 context_id,
  별도 렌더링, 최대 5문단/본문 6000자/렌더링 2000 UTF-8 byte 보수 상한.
  byte 상한은 실제 모델 토큰 측정값이 아니다. 실제 모델별 계산기 검증은 남아 있다.
- `rag/index.py`: 오프라인 GenerationIndex.publish(as_of), 당시 활성 revision/검수 주석,
  knowledge/research 허용, 원문 객체 무결성 검사, 세대별 별도 FTS5 corpus와 고정 BM25 통계.
  세대 파일 완성 후 공개하며 검색 중 인덱스를 갱신하는 API는 없다.
- `agents.py`, `semantic.py`, `presentation.py`: 동일한 사전 고정 배경을 토론자·중재자·검토자에
  한 번 주입. 시장 Fact/[E#]/미사용 근거 계산 경계를 유지하고 공개 K·내부 자료 ID 인용을 반려한다.
  배경은 검사 대상 데이터이며 없는 종목 지표를 생성하면 안 된다는 지침을 공유한다.
- `server/service.py`, `config.py`, `audit.py`: 기본 비활성. 활성 시 명시 세대·프로필을 요구하고
  스냅샷 뒤 검색 한 번→전체 묶음/설정/코드/정책/프롬프트/스키마 fingerprint 감사→LiveRunner 연결.
  HTTP/SSE allowlist·종목/종가 날짜 재사용·Spring 판정 봉인 계약은 유지한다.
- `benchmark.py`: run_pair의 정식 KnowledgeContext 연결과 run_rag_comparison 추가.
  같은 Snapshot/모델/effort/순서로 none/common_short 각각 single/debate를 실행한다.
  비교는 HTTP 운영 재사용과 분리한다. legacy dict 배경 입력도 기존 호환 경로를 유지한다.

**실제 Retriever는 아직 없다.** `BULLBEAR_RAG_ENABLED=true` 경로는
`from ..rag.retrieval import Retriever`에서 실패하고 runner 호출 전에 일반 오류로 종료한다.
HTTP 연결 검증은 주입한 검색기이며 실제 검색 성공 증거가 아니다.

## 검증 조건과 실제 결과

원본 `ai-worker/.venv/Scripts/python.exe`를 쓰고 작업 공간 `ai-worker`에서
`PYTHONPATH=<이 작업 공간>/ai-worker/src`를 지정했다. 공급자 키·원본 데이터 복사나 유료 호출은 없다.

| 검증 | 결과 |
|---|---|
| 새 context/index 불변성·FTS 통계·과거 검수 | 4 passed, 0.95초 |
| 에이전트·의미·표현 회귀 | 71 passed, 11.61초 |
| benchmark 기존/신규 회귀 | 19 passed, 20.40초; 마지막 조정 후 신규 4개 재통과 |
| HTTP/감사/서버 회귀 + 상태 구분 | 31 passed, 21.24초 + 신규 상태 3 passed, 17.53초 |

독립 테스트 묶음에는 중복 회귀가 있으므로 위 숫자를 합산하지 않는다.
초기 context/index 검사에서 테스트 상대 import와 Windows SQLite 연결 미종료가 발견되어 수정했고
마지막 4개가 통과했다. 전체 최종 회귀는 **200 passed, 2 skipped, 43.99초**다.
건너뛴 2개는 별도 외부 Spring 통합이다. `git diff --check`도 통과했다.

주입 fixture의 실제 비교 산출물 `rag-comparison.json`에서 읽은 결과:

| 조건 | 완료 | fixture 요청 수 | 비교 셀 전체 경과 | single 생성 경과 | debate 생성 경과 |
|---|---:|---:|---:|---:|---:|
| none | 2/2 | 16 | 0.211380초 | 0.006188초 | 0.054688초 |
| common_short | 2/2 | 16 | 0.268008초 | 0.010290초 | 0.111345초 |

완료율은 4/4, 이번 설정의 최대 요청 수는 4×120=480이다. `usage_status=fixture_no_real_usage`,
`cost_usd=null`, `cost_status=not_priced_use_recorded_actual_usage`다. 실제 비용 0달러라는 뜻이 아니다.
시간은 로컬 fixture·파일 감사까지 포함한 연결 측정이며 실제 LLM·운영 성능으로 일반화할 수 없다.
fixture의 입력 문단은 검색된 정답 집합이나 실제 검수된 운영 corpus가 아니다.
실제 7거래일 결과는 성숙하지 않았고 accuracy는 null이며 raw confidence는 보정 확률이 아니다.

## 미완료와 다음 작업

1. `rag/retrieval.py`의 `Retriever(store).retrieve(snapshot, generation_id=...)` 구현이 최우선이다.
   common 2/short 3, 각 후보 20, 중복 문단·문서/사건 처리, 시장·종목 필터,
   1초 deadline, 빈 결과/장애/시간 초과 구분, 온전한 문단 단위 예산 적용이 필요하다.
   현 context는 전체 5개만 제한하며 경로별 2/3 규칙은 아직 강제하지 않는다.
2. 검색 시점에 최신 활성 revision/annotation을 다시 검증하되 세대 고정 통계를 유지한다.
   미래 세대 컷오프·실제 공개 시각과 회고 재구성의 차이를 명시하고 과거 검색 누출을 회귀 검증한다.
   index.open은 manifest 해시만 검사한다. FTS/member 변조 일치 검사·발행 장애/동시성·세대 상태 수명주기는 남아 있다.
3. 검색 후보/선정/제외 사유/상태/지연 감사와 context 저장/load_context·debate 불변 연결 구현.
   현재 HTTP audit에는 전체 묶음이 있으나 검색 감사 저장소·재생 API는 없다.
4. 정답 검색 fixture·필터/정정/시점/빈 결과/장애/시간 예산 회귀 후 저장층→실제 검색→HTTP/benchmark
   통합 평가. 현재 HTTP 테스트는 주입 Retriever이므로 통합 완료로 해석하지 않는다.
5. 실제 모델 tokenizer/가격표/입력 여유/추가 배경 비용·실제 모델을 반영한 실행 식별 확정과
   허용된 작은 호출 상한의 실제 비교가 필요하다. 현재 fingerprint는 선택 모델 설정을 고정하며
   실행 중 fallback의 실제 모델 목록은 기존 감사 usage에 따로 기록된다.

P2 위험 검토·LangGraph, 벡터, 중장기 예측, 자동 가중치 개선, 실행 재개는 시작하지 않았다.
P1 품질·운영 완료율/비용/지연 활성화 기준과 11/16 프리즈 일정을 충족하기 전 필수로 확대하지 않는다.

다른 컴퓨터에서 브랜치를 받은 뒤 기본 확인 명령(PowerShell):

```powershell
git switch feat/worker-rag-context
git status --short
git log -5 --oneline
Get-Content docs/archive/worker-rag-context-checkpoint.md
cd ai-worker
uv sync --group dev
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
uv run pytest -q
```

키는 별도로 준비하며 레포 밖에서 공유한다. Anthropic HTTP LiveRunner와 현재 로컬 OpenAI 키만 있는
환경의 불일치는 해결하지 않았다. RAG 실제 경로·운영 키 검증 전 기능을 활성화하지 않는다.

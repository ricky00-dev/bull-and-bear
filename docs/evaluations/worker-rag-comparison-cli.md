# RAG 4조건 CLI 실행

> 2026-11-05 변경: 기존 순차 토론 엔진 및 전용 experiment/benchmark/diagnostics/quality_evaluation 실행기는 삭제됐습니다. 아래 관련 명령·측정값은 당시 구현의 이력입니다. 현재 토론은 HTTP 또는 `bullbear debate`의 LangGraph 경로를 사용하며, 단일 분석 HTTP 모드는 유지합니다.

2026-10-30. `python -m bullbear.benchmark`에 `--rag-comparison`을 추가했다.
기본 동작은 기존 `run_batch`이며, 플래그를 명시했을 때만 RAG 4조건 비교를 실행한다.

```powershell
python -m bullbear.benchmark `
  --rag-comparison `
  --snapshot-file <고정-snapshot.json> `
  --context-file <KnowledgeContext-payload.json> `
  --output-dir <존재하지-않는-출력폴더>
```

- 기본 provider는 fixture이며 이 명령은 수집·검색·유료 모델 호출을 하지 않는다.
- snapshot은 정확히 1개여야 한다. 같은 snapshot과 연결된 정식 `knowledge-context-v1` /
  `knowledge-short-v1` payload JSON을 context-file로 전달한다.
  `rag retrieve`의 콘솔 wrapper(`context_id`/`payload`) 전체가 아니라 `payload` 객체를 저장해야 한다.
- none/common_short 각각 single/debate를 실행해 총 4조건을 생성한다.
  출력은 `rag-manifest.json`, `rag-comparison.json`, `context.json` 및 조건별 디렉터리다.
- context 누락·여러 snapshot·legacy context·null은 출력 폴더를 만들기 전에 setup 오류로 종료한다.
  empty/실패 context를 RAG가 추가된 조건으로 집계하지 않는다.
- 종료 코드: 전 조건 완료 0, 조건 실패 포함 1, 입력/설정 오류 2.
- 실제 provider 실행에는 별도의 `--allow-paid`, 명시 모델, 영속 `--budget-ledger`,
  `--authorization-id`, `--max-total-usd` 및 기존 입력·출력/요청 상한 조건이 그대로 적용된다.
  이 CLI 추가 작업에서는 실제 모델 호출을 하지 않았다.

검증: `pytest -o pythonpath=src tests/test_benchmark.py tests/test_rag_benchmark.py -q` →
**24 passed, 6.79초**. 신규 CLI 4조건 정상 실행·context 누락·여러 snapshot·legacy/null 거절과
기존 기본 batch 출력 유지 확인. fixture 완료는 예측 성과가 아니며 비용·accuracy는 null이다.

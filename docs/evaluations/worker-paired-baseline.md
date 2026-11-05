# 동일 스냅샷 단일 분석가·토론 비교 실행기

> 2026-11-05 변경: 기존 순차 토론 엔진 및 전용 experiment/benchmark/diagnostics/quality_evaluation 실행기는 삭제됐습니다. 아래 관련 명령·측정값은 당시 구현의 이력입니다. 현재 토론은 HTTP 또는 `bullbear debate`의 LangGraph 경로를 사용하며, 단일 분석 HTTP 모드는 유지합니다.

2026-10-30 · 내부 연구용 · `paired-baseline-v1`

`python -m bullbear.benchmark`는 저장된 시장 스냅샷을 한 번 읽고 같은 입력으로 단일 분석가와 기존 매수·매도 토론을 실행한다. 운영 HTTP API·당일 토론 재사용 키·Spring 판정 봉인·기존 선공 비교 `experiment.py`는 변경하지 않는다. 실제 채점 결과를 수집하는 백테스트나 포트폴리오 시뮬레이터는 아니다.

## 비교 조건

| 항목 | single | debate |
|---|---|---|
| 역할 | 중립 분석가가 BUY/HOLD/SELL 직접 예측 | 기존 3라운드 매수·매도 토론 뒤 중재자 판정 |
| 최종 모델 | `final_model` | 같은 `final_model`로 중재 |
| 최종 생성 effort | `final_effort` | 같은 `final_effort` |
| 자료 | 저장된 Snapshot의 동일 JSON | 같은 JSON에서 독립 복원한 Snapshot |
| 검증 | Fact ID/원값, 발언 길이, 7거래일·코스피 기준, 개념, SemanticReviewer | 기존 Debater/Moderator 검증 전체 |
| 재작성 | 최대 3회, 의미 검토도 요청 수에 포함 | 기존 최대 3회, 추가 질문 라운드 0회 |

단일 분석가는 단일 역할이라는 뜻이며 유료 호출 한 번이라는 뜻은 아니다. 도구 조회·의미 검토·재작성은 추가 요청을 사용한다. 토론자 모델은 `debater_model`로 별도 지정할 수 있지만 기본은 최종 모델과 같다. 이 경우 모델 구성까지 실험 조건으로 기록해야 한다.

공통 판정은 스냅샷 종가에서 이후 **7거래일 종가까지 종목 수익률 − 코스피 수익률**이다. BUY는 +2%p 초과, SELL은 −2%p 미만, HOLD는 두 경계를 포함한 사이 구간이며 3거래일은 보조 채점이다. 결과에 저장하는 `confidence`는 **보정되지 않은 모델 자신감**으로, 적중 확률·Brier score·보정 성능을 뜻하지 않는다.

## 호출 예시

아래 명령은 `ai-worker/`에서 실행한다. 입력은 기존 스냅샷 JSON이며 이 실행기는 뉴스·시세를 새로 수집하지 않는다. 출력 디렉터리는 새 경로여야 하며 기존 결과를 덮어쓰거나 자동 재개하지 않는다.

```powershell
# 기본 fixture: 외부 데이터·LLM 호출 없음
python -m bullbear.benchmark --snapshot-file data/snapshots/example.json --output-dir data/benchmarks/example-fixture

# 여러 입력 또는 같은 입력 반복: 최대 쌍 수를 넘기면 실행 전 거부
python -m bullbear.benchmark --snapshot-file data/snapshots/a.json --snapshot-file data/snapshots/b.json --max-pairs 2
```

fixture는 운영 토론·검증 경로의 연결을 확인하는 정해진 출력이다. SemanticReviewer의 fixture 결과도 미리 정해져 있으므로 사실·논리·예측 품질을 검증했다는 의미가 없다. Python API로 `llm_factory`를 주입한 테스트는 `injected_test_double`, 기본 fixture는 `fixture`, 실제 공급자 경로는 `live`로 구분한다. 테스트 더블 사용 결과를 live 결과로 승격하지 않는다.

실제 유료 호출은 환경의 공급자 키, 명시적 모델, `--allow-paid`가 모두 필요하다. 아래는 **유료 실행 예시이며 이번 작업에서 실행하지 않았다**.

```powershell
python -m bullbear.benchmark --snapshot-file data/snapshots/example.json --provider anthropic --model YOUR_MODEL --allow-paid --max-pairs 1 --max-requests-per-condition 40
python -m bullbear.benchmark --snapshot-file data/snapshots/example.json --provider openai --model YOUR_MODEL --allow-paid --max-pairs 1 --max-requests-per-condition 40
```

모델 폴백과 SDK 자동 재시도는 끈다. 공급자 장애·거절·파싱 실패를 fixture로 대체하지 않는다. 애플리케이션의 도구·재작성·의미 검토는 조건별 공통 요청 예산을 사용하며, 다음 SDK 호출 **전에** 상한을 검사한다. 기본 조건별 120회, 설정 가능 범위 1~256회, 도구 루프 기본 4회·최대 8회, 배치 기본 최대 10쌍·설정 가능 최대 20쌍이다. 쌍마다 두 조건을 실행하므로 총 요청 상한은 `쌍 수 × 2 × 조건별 요청 상한`이다. 금액 상한을 보장하지 않으므로 실제 호출 전 토큰 한도와 모델 가격을 별도로 확인해야 한다.

`--first-side bull|bear`, `--final-effort`, `--debater-effort`, `--max-tool-turns`도 기록한다. 배치의 조건 순서는 single→debate, debate→single을 교대로 사용한다. 첫 발언 측은 별도 설정이며 조건 실행 순서와 혼동하지 않는다.

## 결과와 실패 보존

```text
batch/
  batch.json                     셀별 완료·부분 실패·입력 오류
  pair-001/
    snapshot.json                두 조건의 고정 입력
    context.json                 선택적 동일 배경 입력
    manifest.json                코드·정책·모델·설정·프롬프트·스키마·입력 해시
    comparison.json              두 조건 결과와 미채점 상태
    single/
      events.jsonl               검증 시도·반려·실패
      generations.jsonl          생성/검토 프롬프트·원출력·공급자 응답
      report.json                상태·사용량·시간·모델 자신감·원문
    debate/
      events.jsonl               기존 6발언의 모든 시도·검증·중재 기록
      generations.jsonl          생성/검토 프롬프트·원출력·공급자 응답
      report.json                상태·전문·사용량·시간·검증 통계
```

한 조건이 실패해도 반대 조건과 다음 셀을 실행한다. 손상된 입력 파일도 해당 셀의 입력 실패로 기록하고 다음 파일로 진행한다. 실패 예외의 메시지는 키·요청 정보가 섞일 수 있어 저장하지 않고 타입만 기록한다. 모델이 만든 원문과 공급자의 정상 응답은 재검토를 위해 로컬 데이터 디렉터리에 보존하며 키·원문 결과를 Git에 넣지 않는다.

`usage`는 기존 어댑터가 제공한 **실제 응답 모델**별 입력·출력·캐시 토큰이다. 실제 응답을 얻지 못한 요청은 `partial_unconfirmed_requests`로 표시하고 비용이 0이었다고 간주하지 않는다. 가격표는 구현하지 않았으므로 `cost_usd=null`, `cost_status=not_priced_use_recorded_actual_usage`이며 달러 비용을 추정해서 채우지 않는다. 단일/중재자의 실제 응답 모델 집합이 다르면 `comparable=false`다.

스냅샷 전체 해시를 별도로 저장해 같은 `snapshot_id`라도 다른 입력을 구별한다. 조건은 독립적으로 복원한 입력을 받으며 실행 중 입력이 변경되면 실패로 기록한다. manifest에는 HEAD·dirty 여부·관련 모듈 파일 해시가 함께 있으므로 작업 중 실행과 커밋 후 실행을 구별할 수 있다.

`accuracy=null`, `forecast_scoring=pending_no_realized_returns`가 기본이다. 두 조건의 판정 일치율은 예측 적중률이 아니다. 실제 평가에는 확정 종가·거래일·기업행사와 자료 시각의 정합성을 검토하고 같은 쌍의 3/7거래일 결과를 나중에 연결해야 한다. 실패를 예측 실패나 HOLD로 바꾸지 않고 전체 시도·완료·실패를 함께 세어야 한다. 반복 실행·겹치는 예측 기간의 상관과 전향 표본이 없으면 성능 개선을 주장하지 않는다.

## 후속 지식 묶음 연결

Python API는 `run_pair(snapshot, config, directory, context_bundle=None)`와 `run_batch(snapshots_or_paths, config, directory, context_bundle=None)`다. 선택적 `--context-file`은 동일한 JSON 배경 묶음을 두 조건의 모든 생성·검토 역할에 제공하며 원본과 해시를 저장한다. 묶음의 `snapshot_id`가 있으면 입력 스냅샷과 같아야 한다.

후속 `KnowledgeContext`는 검색을 조건별로 다시 하지 않고 **한 번 선택한 고정 묶음**의 `model_dump(mode="json")`를 전달한다. 이 모듈은 기간/시장 적합성·원문 버전·시점 검증을 대신하지 않는다. 검색 모듈이 이를 통과시킨 뒤 연결해야 하며 `K.*`는 기존 Fact 검증을 통과할 수 없으므로 공개 종목 근거를 대신하지 않는다. 배경 유무 비교는 별도 출력 디렉터리와 context 해시로 실행하고 기존 선공 실험 결과와 합치지 않는다.

## 이번 검증 범위

네트워크 없는 fixture와 SDK 테스트 더블로 동일 입력·6발언 완료·검증 재작성·실패 보존·요청 상한·원출력·실제 모델 토큰 집계·폴백 비활성 경로를 검증한다. 유료 모델, 실제 공급자, Spring/PostgreSQL 전체 통합, 실제 3/7거래일 성과는 실행하지 않았다. 이 문서는 구현과 검증 범위를 설명하며 성능 개선 보고서가 아니다.

# 모델 입력·비용 예산 구현과 검증

2026-10-30. 사용자가 명시한 모델은 **OpenAI `gpt-5-mini`**, 이번 작업 전체 API 상한은 **USD 3**다.
조건별·재실행별로 USD 3을 새로 배정하는 뜻이 아니다. 실제 호출은 부모 총괄 세션에서 수행하며
이 문서의 모듈 검증은 네트워크 없는 테스트다.

## 공식 자료 확인

[GPT-5 Mini 모델 문서](https://developers.openai.com/api/docs/models/gpt-5-mini)와
[가격 문서](https://developers.openai.com/api/docs/pricing)를 검색한 뒤 실제 페이지를 열어 확인했다.
Standard USD 텍스트 단가는 입력 $0.25/1M, 캐시 입력 $0.025/1M, 출력 $2/1M이다.
context는 400,000, 출력 최대는 128,000토큰이다. 요청 별칭과 허용 실제 모델은
`gpt-5-mini`, `gpt-5-mini-2025-08-07`로 제한했다. 문서에 deprecated 표기가 있지만
사용자 지정 모델을 다른 모델로 대체하지 않는다. 계정 접근 가능 여부는 실제 요청 전에는 미확인이다.

[추론 모델 문서](https://developers.openai.com/api/docs/guides/reasoning)는 reasoning tokens가
context를 차지하고 출력 단가로 과금되며 `max_output_tokens`가 reasoning·보이는 출력 등을
함께 제한한다고 설명한다. reasoning token을 output에 다시 더하지 않는다.

가격 버전은 `openai-standard-usd-2026-10-30-v1`, 전체 가격/한도/출처 설정 SHA256을
authorization ledger와 manifest에 기록한다. 가격표 변경은 기존 authorization에 묵시적으로 반영하지 않는다.
세금·환율·Azure/Bedrock·우선 처리·호스팅 도구 과금은 이 단가표의 범위가 아니다.
현재 live benchmark는 이 OpenAI 모델만 지원하고 미가격 Anthropic/다른 모델은 실행 전에 거부한다.
기존 HTTP Anthropic 경로는 이 모듈로 변경하지 않았다.

## 입력 검사와 비용 예약

- 전체 요청 JSON(시스템 지시·대화·도구 정의·schema 포함)의 UTF-8 byte 수에 envelope와
  재전송 reasoning 여유를 더해 사전 입력 상한을 계산한다. 이는 실제 tokenizer 측정값이 아니다.
- 숨은 서버 대화/previous_response_id, 이미지·파일·오디오, hosted tool, background 요청을 거부한다.
  service tier는 `default`, truncation은 `disabled`로 고정한다.
- 입력 검사값+출력 예약량이 모델 context를 넘으면 요청하지 않는다. 출력 한도는 설정 가능하고
  기본 16,000을 유지한다. reasoning이 이 한도에서 소진되면 실제 실패로 기록한다.
- **금액 예약은 입력 추정값을 사용하지 않는다.** 모델 context 전체에서 출력 한도를 뺀 입력이
  모두 일반 입력 단가로 청구되는 최악 조건을 예약한다. 16,000 출력 기준 호출당 예약은 $0.128이다.
  따라서 로컬 토큰 추정의 오차가 USD 한도를 느슨하게 만들지 않는다. 이 보수 정책은 실제 필요보다
  남은 금액을 많이 요구하며 한도 근처에서는 저렴하게 끝날 가능성이 있어도 다음 호출을 거부한다.
- 사용량을 받은 뒤 일반 입력/캐시 입력/출력을 분리해 실제 단가로 정산한다. OpenAI의
  input_tokens에는 cached_tokens가 포함되므로 캐시는 한 번만 과금한다.
- 응답 미확정/usage 없음은 예약액을 남기고 `cost_usd=null`, 미확정 건수를 기록한다.
  시간 초과·실패·재시작 뒤 임의 환불이나 0달러 전환을 하지 않는다.
- 알려지지 않은 실제 모델·비정상 사용량은 authorization을 halt하고 후속 호출을 차단한다.
  공급자 사용량이 문서상 한도/예약액을 넘는 경우에도 기록하고 중단한다.

`SpendLedger`는 SQLite `BEGIN IMMEDIATE`와 synchronous FULL로 호출 **전** 예약을 커밋한다.
조건·비교·배치·재실행이 동일 ledger 파일과 authorization ID를 공유한다. 모듈이 진행 중 프로세스를
자동 재개하지는 않는다. 별도 결과 폴더에서 다시 실행해도 authorization 예산은 이어진다.
원장 파일 삭제·다른 authorization ID 생성은 새 승인이 아니므로 수행하지 않는다.
이 로컬 원장은 OpenAI 계정 전체 지출이나 다른 프로그램의 API 사용을 통제하지 않는다.

## 사용 방법

총괄 세션은 동일한 경로와 ID를 모든 실행에서 유지한다. 아래는 예시이며 실제 파일은 로컬 데이터다.

```python
config = BenchmarkConfig(
    provider="openai", final_model="gpt-5-mini", debater_model="gpt-5-mini",
    allow_paid=True, max_total_usd="3",
    budget_ledger="data/rag-p1-live/authorization.sqlite3",
    authorization_id="rag-p1-20261030-user-approved-3usd",
    max_output_tokens=16000, max_requests_per_condition=40,
)
```

위 경로는 이번 실제 파일럿의 원장 경로(ai-worker 기준)와 같다. 후속 비교도 이 파일과 ID를
계속 사용해야 하며, 다른 원장이나 ID를 만들어 USD 3 한도를 다시 시작하면 안 된다.

CLI에서도 `--budget-ledger`, `--authorization-id`, `--max-total-usd`, `--max-output-tokens`를 받는다.
기존 fixture/injected test-double 결과의 비용은 계속 null이며 실제 사용량이라고 표시하지 않는다.
실모델 조건 보고서에 `spend`/`budget_scope`, 전체 비교에 `authorization_budget`을 기록한다.
run_rag_comparison의 4개 조건과 run_batch의 모든 쌍은 같은 authorization을 사용한다.
각 조건 결과의 cost는 해당 scope만, authorization_budget은 이전 실패·재실행까지 포함한다.

## 로컬 검증

원본 `.venv/Scripts/python.exe`, worktree `ai-worker`에서 `-o pythonpath=src` 사용.
초기 신규 테스트의 응답 fixture dict/객체 혼동과 기존 Anthropic factory 테스트의 전제 변경을
확인했다. 전자는 fixture를 수정했고 후자는 미가격 Anthropic live 실행 전 거부를 검증하도록 바꿨다.

예산·benchmark·OpenAI adapter·RAG 비교 회귀: 최초 **47 passed, 9.47초**,
service_tier/truncation 고정 후 **47 passed, 7.77초**.
실제 네 조건 및 재실행의 공유 예산과 미가격 응답 원문 보존 회귀를 추가했다.
이 과정에서 schema의 `type: ["number", "null"]`를 입력 유형으로 검사할 때 발생하는
리스트 해시 오류를 발견·수정했다. 최종 집중 회귀는 **49 passed, 9.16초**다.
테스트는 캐시 단가 이중 계산 방지, 정산 내구성, 미확정 예약 보존, 조건/재시작 공유,
모델/가격/한도 변경 거부, 입력 초과, 비텍스트·유료 도구 거부, 동시 예약 초과 방지,
실제 응답 한도 위반 halt, 네트워크 호출 전에 예약이 보이는지, 출력 상한 전달,
fixture 비용 null 유지 등을 확인한다.

실제 요청 성공·실제 지출·예측 품질·전체 모델 입력 여유는 이 단위 테스트 결과로 주장하지 않는다.
공식 단가로 계산한 API 비용은 청구서 확정치와 구분하며, 미확정 요청이 있으면 알려진 비용과
예약 상한을 함께 보고한다. 실제 비교 결과는 별도 평가 문서에 연결한다.

총괄 세션의 실제 결과: [gpt-5-mini 파일럿](worker-rag-live-pilot.md).
두 실행의 총 61회 사용량 가격은 $0.49036, 미확정 요청 0건이며 같은 USD 3 원장을 유지했다.
최종 모델 조건은 1/4 완료여서 비용 상한 준수와 모델 품질 통과를 구분한다.

## 독립 리뷰 후 사용량 보고 보완

정산이 미가격 모델이나 출력 한도 위반으로 거절되면 응답은 수신했어도 어댑터 집계에는
전달되지 않는다. 기존 보고서는 이 경우에도 `usage_status=reported`를 표시할 수 있었다.
`provider_observations`에 모델·원시 usage·정산 상태를 먼저 보존하고, 공급자 관측 건수와
`adapter_usage_requests`를 분리했다. 정산 거절은 `partial_unpriced_or_rejected_usage`,
시도하지 않은 조건은 `no_requests`로 표시한다. 원장과 원시 응답 로그는 그대로 유지한다.
알려진 모델의 한도 위반 비용은 실제 보고 사용량으로 기록하고, 미가격 비용은 null로 유지한다.

미가격 모델·출력 한도 위반·정상 정산 후 refusal 회귀를 추가했다. 다음 네트워크 없는 검증은
**57 passed, 9.17초**다: `pytest -o pythonpath=src tests/test_budget.py tests/test_benchmark_budget.py
tests/test_benchmark.py tests/test_rag_benchmark.py tests/test_openai_llm.py -q`.
독립 리뷰에서 추가 예산 상한 우회는 확인하지 못했으며, 이는 임의 공급자 과금 오류까지
보장한다는 뜻은 아니다. 금액 예약의 근거는 고정 가격표와 제공자의 모델 한도 준수다.

# 워커 예비 운용 점검

현재는 배포 완료 상태가 아니다. 실제 모델 검증과 로컬 통합/복구 결과는
[최신 인계 기록](evaluations/worker-goal-readiness-20261102.md)에 구분해 기록한다.
Docker가 없는 Windows에서는 기존 `scripts/test-worker-spring.ps1`로 임시 PostgreSQL·Spring·워커를
검증할 수 있다. 이 스크립트는 가짜 시장/모델을 사용하며 실제 예비 운용 서버를 상시 설치하지 않는다.

## 실제 HTTP 워커 시작 전

1. Spring과 워커에 같은 비개발용 `WORKER_TOKEN`을 공급한다. 비밀값은 저장소에 커밋하지 않는다.
2. `BULLBEAR_DATA_DIR`은 재시작 후에도 유지되는 경로를 사용한다. 같은 디렉터리는 워커 프로세스
   하나만 소유할 수 있다. Uvicorn은 `--workers 1`로 실행한다.
3. 한 프로세스의 동시 작업 수는 `WORKER_MAX_CONCURRENT`로 제한한다(기본 2).
   초기 예비 운용에서 1로 줄일 수 있다. 이 값은 토론/단일 모드가 공유한다.
4. 아래 비용 장부를 설정하고 `python -m bullbear.preflight`로 설정 오류를 확인한다.
   preflight는 네트워크/모델을 호출하지 않으며 키의 존재만 검사한다. `configuration_ready`가
   실제 모델 접근·원천 데이터·배포 준비 완료를 뜻하지 않는다.
5. 실제 완주와 오류 처리 검증 전에는 전향 자동 실행을 켜지 않는다. 운영 HTTPS, 백업 위치,
   접근 권한과 외부 노출 포트는 배포 대상에서 별도로 검증한다.

## 영속 비용 장부

선택적 설정이다. 두 값을 함께 지정하면 기본 `Service → LiveRunner → LLM` HTTP 실행 경로에 적용된다.

```dotenv
# 예시다. 실제 사용 승인을 받은 총액/식별자로 바꾼다.
BULLBEAR_WORKER_BUDGET_USD=3
BULLBEAR_WORKER_BUDGET_ID=approved-pilot-20261102
```

Compose에서는 `deploy/.env`의 `WORKER_BUDGET_USD`, `WORKER_BUDGET_ID`를 위 변수로 전달한다.
실제 `.env`는 이번 작업에서 변경하지 않았다. 설정이 없는 새 데이터 폴더에는 이 장부가 적용되지 않으며,
preflight에 `worker_provider_budget_not_configured` 경고가 나온다.

장부는 `BULLBEAR_DATA_DIR/http/provider-budget.sqlite3`에 저장된다.

- 총액은 **날짜나 서버 재시작으로 초기화하지 않는다**. 같은 데이터 폴더의 역할·토론·단일 분석이 공유한다.
- 모델 요청마다 SQLite 트랜잭션으로 최대 비용을 먼저 예약한다. 동시에 요청해도 같은 잔액을 중복 사용하지 않는다.
- 현재 가격 정책은 Anthropic 직접 API의 Haiku 5.5/Sonnet 5.5, 표준 처리·global 지역, 텍스트 입력,
  출력 최대 16,000토큰이다. 로컬 도구를 허용하며 기사 본문은 워커의 `fetch_news`가 조회한다.
  본문을 모델에 보내는 비용은 기존 입력 토큰 단가로 정산한다. 명시적인 5분 캐시 쓰기를 지원한다.
  SDK 자동 재시도는 0이며, 애플리케이션 재시도와 도구 후속 호출도 각각 예약한다.
- 입력량 추정 대신 전체 1M 컨텍스트를 최고 단가로 예약한다. 5분 캐시를 사용하는 요청은 읽기 적중을
  가정하지 않고 첫 쓰기 단가(일반 입력의 1.25배)로 예약한다. 출력 16,000 기준 Haiku **$0.665**,
  Sonnet **$2.66**의 여유가 필요하다. 캐시 없는 요청은 기존 $0.54/$2.16이다.
  응답의 일반 입력·출력·캐시 읽기·5분 쓰기를 각각 정산하며 요금 구간과 문맥 한도에는 모든 입력 토큰을 포함한다.
  따라서 **잔액이 남아도 다음 호출의 예약액보다 작으면 중단**한다.
- 타임아웃·사용량 누락·비정상 사용량은 예약액을 유지하고 장부를 중단 상태로 만든다.
  캐시 쓰기 사용량에 TTL별 내역이 없거나 합계가 맞지 않는 경우도 같은 방식으로 처리한다.
  프로세스 중단 당시 예약도 새 워커가 독점 잠금을 얻은 후 미확정으로 기록하며 자동 재호출하지 않는다.
- 기존 장부의 ID/금액과 알 수 없는 가격 정책 변경을 거부한다. 알려진 v1·v2 정책은 v3으로
  이관하며 기존 사용액·예약·미확정 내역·중지 상태를 그대로 보존한다. 환경변수를 지워 제한을 없애는 것도 거부한다.
  기존 장부를 지우거나 다른 폴더로 옮겨 미확정 비용을 0으로 취급하면 안 된다.
- 요청 전 거부는 모델 호출 실패와 구분한다. 이미 확인된 사용량은 유지하며,
  완료된 현재 실행의 정확한 비용을 기존 계약의 선택 필드 `usage.cost_usd`로 보낸다.
  Spring은 이 값을 사용한다. 미확정 비용이 있으면 확정 비용을 보내지 않는다.

읽기 전용 상태 확인(파일이 없으면 생성하지 않음):

```powershell
# ai-worker에서, 실제 데이터 경로로 바꾼다.
./.venv/Scripts/python.exe -m bullbear.anthropic_budget data/http/provider-budget.sqlite3
```

`known_cost_usd`는 확인된 사용량의 단가 환산, `reserved_unconfirmed_usd`는 미확정 예약,
`accounted_upper_usd`는 둘의 합계다. 청구서 대조/환율/세금까지 확인한 값은 아니다.
`halted=true`이면 미확정 요청과 공급자 사용량을 대조해야 한다. 자동으로 예약을 해제하는 명령은 제공하지 않는다.

이 장부는 해당 HTTP 워커의 공급자 요청 비용을 집계한다. 별도 CLI 실험과 다른 데이터 폴더나 서비스에서 발생한 지출은 각 실행에서 관리한다.
기존 실측 스크립트의 $3 승인/누적 기록은 `--prior-run` 체인으로 계속 관리하며, 이를 새 $3 승인으로
초기화하지 않는다. 이 문서의 예시 설정은 추가 비용 사용 승인이 아니다.

`scripts/worker-http-live-pilot.py`는 별도 실측 장부를 사용하므로 운영용 비용 환경변수 둘 중 하나라도
설정돼 있으면 서버·자료 폴더 생성 전에 거부한다. 실측은 운영 설정을 지우지 말고 별도의 셸/작업
환경에서 실행하며, 그 환경의 `.env`에도 운영용 비용 설정을 넣지 않는다. 기존 승인 누적은
반드시 최신 `--prior-run`으로 이어야 한다.

단가/캐시 정책 출처(2026-11-10 확인):
[Anthropic 가격](https://platform.claude.com/docs/en/about-claude/pricing),
[모델 사양](https://platform.claude.com/docs/en/models/overview),
[프롬프트 캐시](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
[후행 시스템 메시지](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages).

## 중단과 복구

완료된 결과는 HTTP SQLite와 스냅샷/감사 파일에서 재조회한다. 재시작 전에 진행 중이던 토론은
실패로 정리하며 모델 작업을 이어서 생성하지 않는다. 미확정 비용은 그대로 보존한다.
같은 request_id의 재전송과 Last-Event-ID 기반 SSE 재생은 새 모델 호출을 만들지 않는다.

백업에는 PostgreSQL뿐 아니라 **worker_data 전체**가 필요하다. `deploy/backup.sh`는 현재 PostgreSQL만
백업하므로 그 스크립트만으로 워커의 스냅샷·감사·비용 장부까지 복구할 수 없다.
워커와 관련 쓰기 작업을 멈추고, SQLite는 WAL을 포함한 일관성을 확보한 뒤 backup API로 복사한다.
복원은 새 경로에 수행하고 무결성·원본 해시·HTTP 결과·SSE 재생을 확인한다.

이번 검증에서는 종료된 실제 v7 실측 자료를 새 폴더에 백업/복원하고 워커를 두 차례 시작했다.
성공한 단일 분석과 실패한 토론의 결과·스냅샷·재사용·SSE가 동일했고, 인증 없는 조회 및 손상된 백업은 거부됐다.
원본은 보존했고 신규 시장/모델 호출은 없었다. 이는 **로컬 정지 상태의 복구 검증**이며 운영 서버,
원격 저장소, 전체 PostgreSQL+워커 동시 복구 또는 복구 시간 보장은 아니다.

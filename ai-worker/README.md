# 불앤베어 AI 워커

Spring API 서버가 호출하는 Python 서비스. API 계약은 [`../docs/worker-api.md`](../docs/worker-api.md).

매수 에이전트와 매도 에이전트가 실제 시장 데이터를 근거로 토론하고, 사용자가 먼저 판정한 뒤
AI 중재자의 판정과 실제 주가로 채점받으며 투자 근거 읽는 법을 배우는 모의투자 교육 서비스.

현재 단계: **CLI + HTTP/SSE 서버**. Spring·웹과 연결해 검색 → 토론 → 판정 봉인·공개 → 채점 예약을 실행한다.
HTTP는 계약 v0.4의 엔드포인트·이벤트와 v0.5의 비동기 스냅샷 응답을 지원한다.

## 시작하기

```bash
brew install uv            # 또는 https://docs.astral.sh/uv/
cd ai-worker
uv sync                    # Python 3.12 + 의존성 설치
# 아래 데이터 소스 설정을 참고해 .env 생성 (기존 .env는 덮어쓰지 않음)

uv run bullbear universe           # 대상 30종목
uv run bullbear snapshot 삼성전자   # 데이터만 확인 (LLM 호출 없음)
uv run bullbear debate 005930      # 토론 → 내 판정 → 중재자 판정 공개
uv run bullbear replay <debate_id> # 기록 재생
uv run pytest                      # 테스트 (네트워크·API 키 불필요)
```

## Spring과 실제 워커 연결

`.env`에 API 키와 `WORKER_TOKEN`을 설정하고, 워커 폴더에서 실행한다. `.env`는 서버 시작 시 읽는다.

```bash
uv run uvicorn bullbear.server:app --host 127.0.0.1 --port 8000 --workers 1
```

별도 터미널에서 루트의 `docker compose up -d`로 PostgreSQL을 띄우고 Spring을 시작한다 (Java 17 이상).
PowerShell 예시:

```powershell
cd api
$env:WORKER_TOKEN = 'dev-worker-token' # 워커 .env와 동일한 값
./gradlew.bat bootRun --args='--spring.profiles.active=worker'
```

Linux/macOS: `WORKER_TOKEN=dev-worker-token ./gradlew bootRun --args='--spring.profiles.active=worker'`.
워커가 다른 호스트라면 `WORKER_BASE_URL`도 설정한다. 기존 `BULLBEAR_WORKER_MODE=http`,
`BULLBEAR_WORKER_BASE_URL`, `BULLBEAR_WORKER_TOKEN` 방식도 지원한다. 기본 프로필은 가짜 워커다.
운영 compose에서는 `WORKER_MODE=http`와 키를 지정하고 `--profile worker`로 기동한다.

- 인증: `/health`를 제외한 모든 엔드포인트에 `X-Worker-Token`이 필요하다. 운영에서는 임의의 긴 토큰을 쓴다.
- 토론: 시세를 확인한 뒤 `202`를 반환하고 스냅샷·LLM 작업은 별도 스레드에서 실행한다.
  처음 응답의 `snapshot_id`는 `null`일 수 있으며 `snapshot_created`에서 확정된다.
- 재사용: 종목·확정 종가 날짜마다 처음 생성한 스냅샷과 토론을 고정해 재사용한다. 같은 날짜에 추가된 뉴스로
  재생성하지 않는 Spring 정책과 같다. 같은 `request_id`는 재시작 후에도 같은 토론을 반환한다.
  다른 본문으로 키를 재사용하면 409다. 실패한 토론을 새로 실행하려면 새 키를 쓴다.
- SSE: `Last-Event-ID` 이후 이벤트 재생, 10초 하트비트, 완료·실패 시 연결 종료.
  검증 실패 발언·원시 토큰·중간 중재자 평가를 내보내지 않는다. 검증 재시도가 소진되면 토론을 실패 처리한다.
- 저장: `BULLBEAR_DATA_DIR/http/worker.sqlite3`에 요청·스냅샷·공개 이벤트를 저장한다.
  기존 JSONL은 감사용으로 유지하며 SSE로 그대로 노출하지 않는다. 중재자 최종 판정은 Spring이 봉인한다.
- 재시작: 완료 이벤트는 그대로 재생하고, 중단된 토론에는 `debate_failed`를 기록한다. 유료 호출을 자동 재실행하지 않는다.
  재시작으로 중단된 호출의 정확한 사용량은 복구할 수 없으므로 Spring 추정 비용이 적용된다.
- 동시 실행: `WORKER_MAX_CONCURRENT` 기본 2. 용량 초과는 429 + `Retry-After: 5`.
  데이터 디렉터리당 **프로세스 하나**만 허용한다. 다중 Uvicorn worker/replica는 시작 시 차단한다.

HTTP·CLI 시세는 KRX 공식 OPEN API, 재무·발행주식수·공시는 OpenDART를 사용한다.
KST 15:40 이전 당일 값과 미래 날짜는 제외한다. 종목 화면·스냅샷은 같은 확정 일봉을 공유한다.
코스피·코스닥 지수도 KRX에서 가져온다. 네이버는 뉴스 검색 API만 사용하며, 시세 실패 시 네이버 차트로 대체하지 않는다.
검색은 기본 30종목 + 예시 우선주·ETF, DART 키가 있으면 상장회사 목록을 추가한다.
DART에 시장 구분이 없는 추가 종목은 `market: null`이며, 전체 ETF·우선주 목록은 제공하지 않는다.
현재 토론 허용 기준은 `UNIVERSE`의 대형주 30종목이다. 시장 전체의 시총·거래대금 필터는 아직 구현하지 않았다.

모델은 `BULLBEAR_MODEL`을 기본으로 쓰고, `BULLBEAR_DEBATER_MODEL`·`BULLBEAR_MODERATOR_MODEL`로 역할별 지정할 수 있다.
실제 응답 모델별 입력·출력·캐시 읽기/생성 토큰을 합산한다. Haiku에는 서버 측 `fallbacks` 옵션을 보내지 않는다.

## HTTP 통합 검증

기본 `uv run pytest`는 외부 데이터·유료 LLM 호출 없이 서버와 토론 엔진을 검증한다.
실제 Spring/PostgreSQL까지 확인하려면 다음 테스트 전용 워커를 실행한다 (운영 진입점에는 테스트 모드가 없다).

```bash
uv run python -m tests.http_fixture --port 18000 --data data/integration-test
```

Spring을 별도 테스트 DB와 `WORKER_BASE_URL=http://127.0.0.1:18000`,
`WORKER_TOKEN=integration-test-token`, `worker` 프로필로 실행한 뒤:

```powershell
$env:BULLBEAR_TEST_API_URL = 'http://127.0.0.1:8080'
uv run pytest tests/test_spring_integration.py -q
```

실제 HTTP/SSE·DB 저장·판정 봉인·공개·채점 예약을 확인한다. 이 테스트는 게스트와 판정을 생성하므로 테스트 DB에서 실행한다.
외부 API 키와 실제 모델 응답 품질은 별도로 확인해야 한다.

## 구조

```
src/bullbear/
  data/base.py        MarketDataSource 인터페이스 (시세·재무·발행주식수·공시)
  data/krx_openapi.py 현재 시세·지수: KRX 공식 API, 날짜별 공통 캐시
  data/pykrx_dart.py  재사용하는 OpenDART 재무·공시 구현 (기존 pykrx 시세 메서드는 현재 경로에서 호출하지 않음)
  data/kis.py         구현체: 한국투자증권 (미구현 자리)
  data/naver_news.py  NewsSource 구현체: 네이버 검색 API 뉴스 (제목·요약·링크만)
  snapshot.py         판단 시점 스냅샷. 모든 수치를 ID 붙은 Fact로 고정, 파생 지표 계산
  tools.py            에이전트 도구. 스냅샷에 묶여 있어 같은 시점 데이터만 반환
  verifier.py         근거 검증기 (결정론적). 근거 값을 원본과 대조해 반려
  agents.py           매수·매도 토론자, 중재자
  llm.py              Claude 호출: 스트리밍, 도구 루프, 구조화 출력, 거절 시 폴백
  debate.py           토론 진행: 3라운드, 검증 재시도, 추가 질문 라운드, 판정 봉인
  events.py           JSONL 이벤트 기록 (재현용, 덧붙이기만)
  cli.py
```

흐름:

1. `build_snapshot`이 데이터 소스에서 한 번 받아와 스냅샷을 고정한다. ID는 내용 해시라서 같은 데이터면 같은 ID다.
2. 매수 → 매도 순으로 주장, 반박, 최종 변론. 토론자는 도구로 스냅샷 Fact를 조회하고,
   발언을 `{claim, argument, evidence[{ref, source_id, value, interpretation}]}` 형식으로 낸다.
3. 검증기가 근거의 `source_id`와 `value`를 스냅샷과 대조한다. 틀리면 같은 대화에 피드백을 붙여
   최대 2번 다시 쓰게 한다.
4. 중재자가 기준표(관련성·중요도·반박·리스크 인식)와 검증 통계로 평가한다. 쟁점이 남았다고 보면
   추가 질문 라운드를 요청한다 (기본 최대 1회).
5. 중재자 판정은 봉인된 채 기록되고, 사용자 판정이 기록된 뒤에 공개된다.

## 데이터 소스 메모

- 시세·지수는 KRX 공식 OPEN API. 기존 pykrx/네이버 차트 어댑터는 남겨 두지만 HTTP·CLI 기본 경로에서 사용하지 않는다.
  밸류에이션은 `snapshot.py`에서 시세 × DART 발행주식수, DART 재무로 계산하고 계산 입력을 `inputs`에 남긴다.
- KRX 원시 일봉은 기업행사 수정주가가 아니다. 액면분할·병합 등이 있으면 지표·수익률이 왜곡될 수 있으며
  현재는 스냅샷 경고로 알린다. 해당 종목을 정식 성과평가에 쓰기 전 기업행사 보정이 필요하다.
- PER은 당기순이익(연결, 비지배지분 포함) 기준이라 증권사 PER(지배주주 순이익)과 다를 수 있다.
- 시가총액은 보통주만 센다.
- 뉴스는 `NewsSource`로 따로 둔다. 네이버 검색 API로 최근 7일 기사 중 제목에 종목명이 있는 것만, 재전송 기사는 하나로 합쳐 최대 30건.
  스냅샷 생성 시각 이후 기사는 넣지 않는다. 본문은 가져오지 않는다 (저작권·약관).
- LG, SK처럼 이름이 짧은 종목은 관련 없는 기사가 섞인다. `naver_news.QUERY_OVERRIDES`로 보정한다.
- 새 공급자는 `MarketDataSource`를 구현하고 공통 진입점 `server/market.py`에서 연결한다.

### 데이터 소스 설정

`ai-worker/.env`에 다음 값을 설정한다. 비밀값은 커밋하지 않는다.

```dotenv
KRX_API_KEY=
OPENDART_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
# OpenAI 실험용. 기존 HTTP 워커는 ANTHROPIC_API_KEY 사용.
OPENAI_API_KEY=
```

- 네이버 키는 **NAVER API HUB**에서 `NAVER 검색 > 뉴스`를 선택한 Application의 인증 정보다.
  기존 개발자센터 신규 발급은 종료됐다. 현재 코드는 HUB 주소와 `X-NCP-APIGW-API-KEY-ID/KEY` 헤더를 사용한다.
  [뉴스 API 공식 문서](https://api.ncloud-docs.com/docs/naver-api-hub-search-news).
- KRX 인증키와 별도로 유가증권/코스닥 일별매매정보, KOSPI/KOSDAQ 시리즈 일별시세정보 활용 승인이 필요하다.
  [공식 이용 절차](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp).
- KRX는 하루치 시장 전체를 반환한다. 날짜별 압축 캐시를 공유하며, 최근 7일과 빈 응답은 1시간 뒤 갱신한다.
  최초 400일 수집은 여러 분 걸릴 수 있다. **API를 사용하기 전에 `uv run bullbear snapshot 삼성전자`로
  과거 시세 캐시를 준비한다.** 준비하지 않으면 Spring의 15초 요청 제한을 초과할 수 있다.
- 조회 간격은 최소 0.25초, 단일 조회 구간은 최대 800일로 제한한다. 오류 응답을 휴장일로 처리하지 않는다.
- KRX 키가 없으면 시세 조회가 실패한다. DART·뉴스 키가 없으면 해당 자료를 제외하고 스냅샷 경고를 남긴다.
- 기존 셸 환경변수가 `.env`보다 우선이다. 실험에서 파일을 명시적으로 우선하려면
  `uv run python -m bullbear.experiment --env-file .env --provider openai --model gpt-5-mini`를 사용한다.
- 2026-10-29: 사용자 인증키로 유가증권 일봉·KOSPI 지수 조회와 삼성전자 265거래일 수집을 확인했다.
  실제 키의 코스닥 시세·지수 권한은 별도 확인이 필요하다.

## 판단 기간과 개념·논리 검토

- `7d-concise-v4`: 판정 질문을 그대로 공유한다. HOLD는 자료 부족/애매함이 아니라
  7거래일 뒤 코스피와 비슷하게 움직여 상대수익이 −2%p~+2%p 안일 것이라는 예측이다.
- 주장 한 줄·한 문장, 본문 최대 3문장, 서로 다른 근거 최대 3개. 반박·마무리는
  양측의 이전 전체 토론에 없던 source_id를 최소 1개 인용하며 7거래일 안의 계기가 될
  뉴스·공시를 우선 조회한다. 새 근거가 전혀 없으면 발언을 지어내지 않고 중단한다.
- 1조 원 이상 금액은 사용자 글에서 조 원으로 표현한다. 도구의 display는 표현용이며
  evidence.value는 원 단위 그대로다. 중재자 글에서는 내부 ID·검증 통계·투자자별 권고를 제외한다.
- 중재자 [E1]은 decisive_evidence[0]에 대응한다(토론자 번호와 별도). 이유 최대 3문장,
  양측 평가 각 1문장. 표현 규칙 위반도 재작성 피드백으로 처리한다.
- 반박은 상대 발언에서 짧은 원문을 인용하고, 코드가 실제 반대편 주장·본문의 문구인지 확인한다.
  의미 검토에는 발언자·라운드·각 발언의 독립적인 근거 번호 대응표를 전달한다.

- `prompts.JUDGMENT_POLICY`를 양측·중재자·검토 역할이 공유한다. 주가 기준일 이후
  7거래일 코스피 대비 초과수익률 기준: BUY > +2%p, SELL < -2%p, HOLD는 경계 포함 사이 구간.
  서비스의 3거래일 채점은 보조 지표다. 장기 지표를 쓸 경우 이 기간과의 연결 및 한계를 설명한다.
- 기존 수치/ID 대조 → 판단 기간 명시·알려진 PER 역전 규칙 검사 → 별도 대화의 LLM 의미 검토 순서다.
  의미 검토는 개념 오류, 근거 없는 인과 단정, 기간 이탈, 모순을 원문 인용과 함께 반려한다.
- 발언과 중재자 판정은 최대 3회 생성한다. 끝까지 실패하거나 검토 호출이 실패하면
  미검증 발언/판정을 성공 처리하지 않고 토론을 중단한다. 기존 API 응답 형식은 바꾸지 않는다.
- 실험 보고서의 `policy_version`, `judgment_policy`, `semantic_reviews`에 기준과 검토 대상/결과를 저장한다.
  검토 호출 토큰도 해당 토론자/중재자 사용량에 포함된다. 별도 대화지만 같은 모델이므로
  독립적인 사실 확인이나 논리적 정확성 증명이 아니며 오탐·누락 가능성이 있다.
- 현재 명시적 개념 규칙은 알려진 PER 역전 표현을 좁게 다룬다. 모든 표현을 정규식으로 판별하지 않는다.
- 인용 정확도를 원천 사실의 무오류로 확대하는 관측 사례도 규칙으로 반려한다.
  evidence.ref는 E1 형식만 허용하며 본문의 [E1]과 구분한다.

## 테스트

- 파이프라인 동작을 바꾸면 `tests/fakes.py`의 가짜 소스·에이전트로 테스트를 추가한다.

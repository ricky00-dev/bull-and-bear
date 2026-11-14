# 불앤베어 (Bull & Bear)

**AI가 토론하고, 당신이 판정합니다.**

같은 종목·같은 데이터를 두고 매수 AI와 매도 AI가 3라운드 토론을 합니다. 사용자는 AI 중재자의 판정을 보기 전에 먼저 매수·보류·매도를 고르고(판정 봉인), 3·7거래일 뒤 실제 주가로 사용자와 AI가 같은 규칙으로 채점됩니다.
AI가 정답을 알려 주는 서비스가 아니라, **양쪽 근거를 읽고 스스로 판단하는 눈을 기르는 모의투자 교육 서비스**입니다.

단국대학교 SW융합대학 졸업작품 (2026) · 팀 불앤베어

| | |
|---|---|
| 서비스 | https://54-253-242-203.sslip.io |
| 시연 영상 | (업로드 후 추가) |
| 결과보고서 | (제출본 추가 예정) |

![홈 → 종목 → 토론](docs/images/screens-flow.png)
![판정 → AI 판정 공개 → 채점](docs/images/screens-judge.png)

## 핵심 흐름

1. **종목 검색**: 코스피 보통주를 이름·코드·초성으로 찾습니다.
2. **AI 토론 시청**: 매수·매도 AI가 같은 스냅샷(시세·재무·공시·뉴스)을 근거로 입론·반박·마무리 6발언을 합니다. 발언은 SSE로 실시간 도착하고, 숫자마다 근거 칩을 눌러 원자료를 볼 수 있습니다.
3. **내 판정 (봉인)**: 매수·보류·매도와 확신도, 설득된 근거 2개를 고릅니다. 그 전까지 AI 중재자 판정은 서버가 봉인합니다.
4. **AI 판정 공개**: 제출하는 순간 중재자 판정과 이유, 다른 사용자 분포가 열립니다.
5. **채점**: 3·7거래일 뒤 종가의 코스피 대비 초과수익률로 채점합니다. +2%p 초과면 매수, −2%p 미만이면 매도, 그 사이면 보류가 정답입니다.

전시용으로 **타임머신 퀴즈**(결과가 이미 나온 과거 토론 5문제), 랭킹, 전시장 화면(QR), AI 성적표, 관리자 화면이 있습니다.

![타임머신 퀴즈와 채점 상세](docs/images/screens-quiz.png)

## 아키텍처

```mermaid
flowchart LR
  B[브라우저<br/>React PWA] -- HTTPS --> C[Caddy<br/>자동 HTTPS · 정적 파일]
  C -- "/api/* · SSE" --> S[Spring Boot API<br/>인증 · 토론 수명주기 · SSE 중계<br/>판정 봉인 · 채점 · 비용 상한 · 백테스트]
  S --> P[(PostgreSQL)]
  S -- "HTTP + SSE (계약 docs/worker-api.md)" --> W[Python AI 워커<br/>FastAPI · LangGraph]
  W --> L[Claude Sonnet 5.5]
  W --> D[KRX · OpenDART · NAVER 뉴스]
```

- 브라우저는 Spring만 호출합니다. Spring이 워커 이벤트를 모두 저장한 뒤 중계하고, 중재자 판정이 담긴 이벤트는 저장만 하고 봉인합니다.
- 같은 종목·같은 데이터 기준일의 토론은 재사용해 비용이 0입니다. 사용자당 하루 5회, 출처별 하루 비용 상한을 둡니다.
- AWS EC2 한 대에 Docker Compose(web·api·postgres·worker)로 배포합니다.

![토론 1건의 요청 흐름](docs/images/debate-sequence.png)

### 토론 엔진

![토론 엔진](docs/images/debate-engine.png)

- 스냅샷의 모든 수치는 `PX.CLOSE`, `FIN.2026H1.REVENUE_YOY`, `VAL.PER_TTM` 같은 근거 ID를 가집니다.
- 토론자 6회 요청은 공통 규칙·도구·스냅샷을 앞에 똑같이 두어 프롬프트 캐시를 함께 씁니다. 토론 1건 평균 **$0.28, 약 2분**.
- 중재자의 첫 판정이 보류면 양측 점수 차로 다시 봅니다(±0.2 안이면 보류 유지).

### AI Worker 아키텍처

**같은 자료, 다른 관점.** 기준 시점이 고정된 스냅샷으로 매수·매도가 토론하고, 중재자가 근거를 평가합니다.

```mermaid
flowchart TB
    sources["종목 정보 수집<br/>KRX · OpenDART · 네이버 뉴스"]
    api["Spring API<br/>토론 요청 · 이벤트 중계 · 판정 봉인"]

    subgraph worker["AI Worker · Python / LangGraph / Claude"]
        snapshot["공통 스냅샷<br/>시세 · 재무 · 공시 · 뉴스 / 기준 시점 고정"]
        debate["Bull 매수 · Bear 매도<br/>입론 → 반박 → 최종변론<br/>라운드별 병렬 실행 · 총 6개 발언"]
        judge["중재자<br/>자료와 6개 발언 평가 → BUY / HOLD / SELL"]
        tools["세 에이전트의 공통 도구<br/>read_snapshot · get_news_body · get_statement_details"]
        snapshot --> debate --> judge
        debate <-.->|"필요한 자료 조회"| tools
        judge <-.->|"근거 확인"| tools
    end

    sources --> snapshot
    api -->|"내부 HTTP · 토론 실행"| snapshot
    judge -->|"SSE · 토론 결과와 판정"| api

    classDef data fill:#eff6ff,stroke:#93b4e8,color:#172554
    classDef agent fill:#f8fafc,stroke:#94a3b8,color:#0f172a
    classDef server fill:#1e293b,stroke:#1e293b,color:#ffffff
    class snapshot,tools data
    class debate,judge,sources agent
    class api server
```

- **공통 입력:** 양측은 같은 스냅샷을 사용하고, 반박·최종변론에서는 이전 라운드의 양쪽 발언을 읽습니다.
- **도구 호출:** 필요한 자료를 조회한 뒤 결과를 반영해 발언하거나 판정합니다. 뉴스 외부 본문 조회는 설정과 실행 조건에 따라 제한됩니다.
- **판정 공개:** 워커는 Spring에 판정을 반환합니다. Spring은 사용자 판정 제출 전까지 이를 브라우저에 공개하지 않습니다.

라운드별 실행 흐름과 도구별 조회 범위는 [워커 아키텍처](ai-worker/README.md#ai-worker-아키텍처)를 참고하세요.

## 실제 토론 예시

**삼성전자 · “낮은 PER은 저평가일까요, 이익 정점의 착시일까요?”**

2026-11-12 실행, 2026-11-10 시세 기준의 실제 기록을 요약했습니다. 아래 문장은 원문 인용이 아닌 요약입니다.

| 라운드 | Bull · 매수 | Bear · 매도 |
|---|---|---|
| **01 입론** | 이익 증가와 PER 7.72배를 근거로, 급락 뒤 가격이 이익에 비해 낮다고 주장합니다. | 한 달 -20.6% 하락과 장기 평균선 아래의 가격을 근거로 하락 위험을 주장합니다. |
| **02 반박** | 이동평균은 과거 가격일 뿐이며, 시장 전체 하락과 회사의 이익 체력을 구분해야 한다고 반박합니다. | PER은 이미 번 이익으로 계산하므로, 앞으로 이익이 줄면 저평가처럼 보이는 착시일 수 있다고 반박합니다. |
| **03 최종변론** | 과거 이익 기준이라는 약점을 인정하면서도, 우려가 가격에 반영됐다고 보고 매수를 유지합니다. | 이익 증가만으로 하락 종료를 판단할 수 없다며, 이익 지속성과 가격 흐름의 위험을 강조합니다. |

<details>
<summary>중재자는 어떻게 판정했나요?</summary>

최초 의견은 **HOLD**, 양측 평가 점수의 평균 차이(매수 3.75 − 매도 3.25 = +0.50)를 적용한 최종 판정은 **BUY**였습니다. HOLD 보정 기준은 ±0.20이며, 보정 후 해설을 다시 생성했습니다.

중재자는 매수 측의 “이익이 거의 두 배”라는 표현이 기록의 영업이익 증가율과 맞지 않는다고 지적했습니다. 매도 측의 “평균선 아래에서 매물이 나온다”는 가정도 자료로 확인되지 않았다고 평가했습니다. 실제 발언에는 오류가 남아 있으며, AI 판정은 정답이나 실측 투자 성과를 뜻하지 않습니다.

</details>

[발언 6개 원문 · 인용 근거 · 중재자 평가 읽기](docs/examples/debate-samsung-20261112.md)

## 실험: 토론 AI는 혼자 판단한 AI보다 나은가

모델 지식 기준일 이후의 과거 날짜(2026-09 ~ 11)로 토론을 재구성하는 백테스트를 했습니다. 대형주 10종목 × 8주 + 시범 5건 = **토론 85건**, 같은 스냅샷의 단일 AI 판정 73건.

| 조건 | 7거래일 적중률 | 3거래일 적중률 |
|---|---:|---:|
| 토론 + 중재자 (최종) | 47.1% | 30.6% |
| 중재자 첫 판정 (보류 재판정 전) | 15.3% | 31.8% |
| 단일 AI | 16.4% | 35.6% |
| 기준선: 항상 매도 | 44.7% | 31.8% |
| 기준선: 항상 보류 | 16.5% | 32.9% |

- 두 AI 모두 거의 항상 보류를 골랐습니다(중재자 첫 판정 96%, 단일 AI 99%).
- 7거래일의 차이는 토론 내용보다 **토론 점수로 방향을 정하는 규칙**에서 나왔고, "항상 매도" 기준선과는 오차(±11%p) 안입니다.
- 결론: 이 표본으로는 토론형 AI가 더 잘 맞힌다고 말할 수 없습니다. AI 판정을 그대로 믿지 말고 근거를 직접 판단하자는 서비스 방향과 맞는 결과입니다. 자세한 설계와 한계는 [docs/experiment.md](docs/experiment.md)와 결과보고서에 있습니다.

## 기술 스택

| 영역 | 사용 |
|---|---|
| 웹 | React 19, Vite, TypeScript, Tailwind CSS 4, TanStack Query, PWA |
| API 서버 | Java 17, Spring Boot 4.1, Spring Data JPA, Flyway, PostgreSQL 16, SSE |
| AI 워커 | Python 3.12, FastAPI, LangGraph, Anthropic SDK (Claude Sonnet 5.5) |
| 데이터 | KRX OPEN API, OpenDART, NAVER 검색 API |
| 인프라 | AWS EC2, Docker Compose, Caddy (Let's Encrypt), GitHub Actions |

## 폴더

| 폴더 | 내용 |
|---|---|
| [`web/`](web) | React 웹앱 |
| [`api/`](api) | Spring Boot API 서버 (사용자, 판정 봉인·공개, 채점, 비용 상한, 백테스트, 관리자) |
| [`ai-worker/`](ai-worker) | AI 워커 (스냅샷, 토론·단일 판정, 중재자, HTTP/SSE) |
| [`deploy/`](deploy) | 운영 배포 (Compose, 백업, 백테스트 스크립트) |
| [`docs/`](docs) | 워커 계약, 아키텍처, 배포·운영, 실험 설계, 작업 로그 |

## 로컬 실행

필요한 것: JDK 17, Node 22, Python 3.12 + [uv](https://docs.astral.sh/uv/), Docker

```bash
docker compose up -d                 # PostgreSQL (포트 5433)
cd api && ./gradlew bootRun          # API :8080. 기본은 가짜 워커라 키 없이 전체 흐름을 볼 수 있음
cd web && npm ci && npm run dev      # 웹 :5173
```

실제 AI 토론까지 돌리려면 `ai-worker/.env`에 Anthropic·KRX·OpenDART·NAVER 키를 넣고 워커를 띄운 뒤, API를 `worker` 프로필로 실행합니다. 자세한 방법은 [ai-worker/README.md](ai-worker/README.md)에 있습니다.

```bash
cd ai-worker && uv sync && uv run uvicorn bullbear.server:app --port 8000 --workers 1
```

테스트: `cd api && ./gradlew test` (Docker 필요) · `cd ai-worker && uv run pytest` · `cd web && npm run lint`

운영 배포는 [docs/DEPLOY.md](docs/DEPLOY.md)를 참고하세요.

## 팀

| 이름 | 역할 |
|---|---|
| 조성빈 | 웹·API 서버·배포 |
| 이장원 | AI 워커 (토론 엔진·데이터) |
| 이용찬 | UI/UX |
| 송준서 | 디자인 |

> 교육용 모의 서비스입니다. AI 판정은 투자 권유가 아니며 실제 주문을 실행하지 않습니다.

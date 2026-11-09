# 불앤베어 웹 (React)

모바일 우선 반응형 웹앱 + PWA. 나중에 Capacitor로 같은 빌드를 감싸 iOS·안드로이드 앱으로 만들 수 있게 짰다.

## 실행

```bash
# API 서버가 먼저 떠 있어야 한다 (../api/README.md, 기본 가짜 워커)
cd web
cp .env.example .env.local   # VITE_API_BASE_URL (기본 http://localhost:8080)
npm install
npm run dev                  # http://localhost:5173
npm run build                # 타입 검사 + 빌드 + 서비스워커 생성
```

스택: React 19, Vite 8, TypeScript, Tailwind CSS 4, TanStack Query 5, React Router 8, vite-plugin-pwa.

## 화면

| 경로 | 화면 |
|---|---|
| `/` | 홈·검색 (종목명·코드·초성, 토론 불가 종목은 이유와 함께) |
| `/stocks/:ticker` | 종목 확인 (60일 차트, AI가 쓸 데이터, 오늘 토론 재사용) |
| `/debates/:id` | 토론 실시간 (라운드 진행, 지금 하는 일, 발언, 근거 칩 → 설명 시트) |
| `/debates/:id/judge` | 내 판정 (매수·보류·매도, 확신도, 설득력 있던 근거, 메모) |
| `/debates/:id/reveal` | AI 판정 공개 (비교, 판정 분포, 중재자 이유, 기준표, 채점 예정일, 가입 권유) |
| `/me` | 내 판정 탭: 적중률·AI 적중률·AI를 이긴 판정, 자주 고르는 근거, 판정 목록과 채점 상태 |
| `/me/judgments/:id` | 채점 결과: 종목·코스피·초과수익, 적중 구간 막대, 나 vs AI, 복기(고른 근거 vs 결정적 근거, 메모) |
| `/quiz` | 타임머신 퀴즈 시작 |
| `/quiz/:id` | 과거 토론 판정·결과 확인 |
| `/my` | 계정·퀴즈 누적 기록·학습 메뉴 |
| `/glossary` | 투자 용어 사전 |
| `/report` | 토론·단일·기준선 및 관람객 성적표, 3/7거래일·예비/정식 범위 선택 |

디자인 기준은 목업(claude.ai 아티팩트)이고, 색 토큰은 `src/index.css`의 `@theme`에 있다.
상승·매수 = 빨강, 하락·매도 = 파랑.

## 코드 구조

```
src/lib/api.ts              API 호출, 게스트 토큰 자동 발급, 401이면 토큰 재발급
src/lib/useDebateStream.ts  토론 SSE 구독 (EventSource, 재연결 시 seq로 중복 무시)
src/lib/glossary.ts         근거 ID → 입문자용 이름·설명·값 표기
src/components/             공통 UI, 근거 설명 시트, 스파크라인
src/pages/                  라우트별 화면 (경로 목록은 src/App.tsx)
```

## 채점 화면 미리 보기 (QA)

채점은 판정 3·7거래일 뒤라 바로 볼 수 없다. API를 "오늘"을 앞당겨 띄우면 된다.

```bash
cd api
BULLBEAR_DEV_CLOCK_OFFSET=P11D BULLBEAR_SCORING_CRON='*/15 * * * * *' ./gradlew bootRun
```

새 토론에 판정을 내고 15초쯤 기다리면 `/me`에 채점 결과가 뜬다 (가짜 워커 시세 기준).

## 앱 전환 대비 원칙

- API 주소는 `VITE_API_BASE_URL` 환경변수. 앱에서는 실제 서버 주소를 넣는다.
- 쿠키 없이 Bearer 토큰 (localStorage). `EventSource`는 헤더를 못 붙여 SSE만 쿼리로 토큰을 보낸다.
- `viewport-fit=cover` + `pt-safe`/`pb-safe`로 노치·홈 바 영역을 비운다.
- hover에 기대는 동작 없음. 터치 영역 44px 이상.
- 라우팅은 SPA(React Router). 서버는 모든 경로에 `index.html`을 돌려줘야 한다 (배포 시 설정).

## 아직 없는 것

- 친구 리그 (카카오 로그인·게스트 기록 승격은 구현됐으며 실제 사용에는 운영 키 설정이 필요하다)
- 홈의 "많이 찾는 종목" (API 필요)
- 아이콘 PNG (지금은 SVG 하나. iOS 홈 화면 아이콘에는 PNG 필요)

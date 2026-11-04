# UI 개선 기록 · 2026-11-04

범위: React 19 / Tailwind 4 기반 홈, 공통 버튼·탭·시트, 토론 읽기와 판정 진입. 서버 계약·판정 봉인 로직은 변경하지 않았다. 전체 서비스 재설계나 실사용자 연구 결과가 아닌 로컬 구현·검토 기록이다.

## 적용한 스킬

사용자 요청으로 아래 원본을 사용자 전역 `~/.codex/skills/`에 설치했다. 저장소 의존성에는 추가하지 않았다.

- [ui-design-system](https://github.com/alirezarezvani/claude-skills/tree/main/product-team/skills/ui-design-system): 토큰과 공통 컴포넌트의 역할·상태 정리.
- [frontend-design](https://github.com/anthropics/skills/tree/main/skills/frontend-design): 서비스 상황에 맞춘 화면 구성과 문구.
- [make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better/tree/main/skills/make-interfaces-feel-better): 터치 영역, 포커스, 모션, 글자 가독성.
- 기존 design-taste-frontend의 앱 화면 지침: 변경 전후 화면 폭별 점검. Achromatic ledger, seed 95163329. 기존 Noto Sans KR와 매수 빨강·매도 파랑 유지. 스타일 재추첨 없음.

## 화면의 질문과 방향

첫 화면의 질문은 “어떤 종목의 토론을 읽고 판정할까?”다. 시세 수치나 투자 성과를 새로 만들어 넣지 않고 기존 API 자료를 사용한다. 첫 계정에 판정이 없으면 실적 수치를 보여주지 않는다.

- 종목은 종목명·6자리 코드·시장으로 구분하고 선택하면 상세로 바로 이동한다. 기존 제안 종목 5개를 유지했다.
- 오늘의 토론·기존 판정은 실제 API 응답이 있을 때만 나타난다. 검색보다 용어 학습이 앞서지 않도록 순서를 정리했다.
- “토론 읽기 → 내 판정 → AI와 비교”가 서비스의 고유한 순서다. AI 판정 봉인은 설명과 자물쇠 아이콘으로 표현한다.
- 모바일은 한 열과 하단 탐색, 768px 이상 홈은 종목과 학습 안내 두 열. 상세·토론·판정은 480px 읽기 폭을 유지한다.
- 이미지는 사용하지 않았다. 새 로고 마크는 상반된 두 방향의 선이며 사진·성과·증언 등의 임시 콘텐츠는 없다.

## 토큰과 공통 컴포넌트

토큰의 원본은 `web/src/index.css`의 Tailwind 4 `@theme`다. 별도 UI 라이브러리나 모션 패키지를 도입하지 않았다.

| 역할 | 값 / 사용처 |
| --- | --- |
| ground / ink / sub | #f5f6f8 / #111318 / #4e5562 |
| faint | #687180. 기존 #9aa1ad보다 어둡게 조정 |
| 매수 / 매도 | 기존 #d92d20 / #2b6fe0 유지 |
| 중재자·봉인 | #465564, #293744, #eef2f5, #d7e0e7. 매수·매도와 구분되는 중립색 |
| control / panel / sheet | 모서리 8 / 12 / 24px |
| touch | 공통 44px. 본문 주요 버튼 56px |
| type | Noto Sans KR, 표 숫자 tabular-nums, 제목 balance, 본문 pretty |

`Screen({wide})`는 홈에만 넓은 폭을 허용한다. `PrimaryButton`은 solid/outline과 disabled를 유지하며 색·누름 피드백을 제공한다. `ModalSheet`는 native dialog 기반으로 Tab/Shift+Tab 순환, Escape/배경 클릭 종료, 배경 비활성화, 스크롤 잠금과 이전 포커스 복귀를 제공한다. `BottomSheet`와 첫 이용 안내가 이를 공유한다. 모션 줄이기 환경에서는 등장·누름 애니메이션과 부드러운 자동 스크롤을 생략한다.

## 전체 검토(full) 범위

| 범주 | 확인한 근거 | 결과 / 경계 |
| --- | --- | --- |
| Typography | 홈·탭·TopBar, 폰트 로드와 세 폭 캡처 | 흐린 보조 글자와 작은 주요 설명 보완. 전 페이지의 모든 글자를 검사한 것은 아님 |
| Surfaces | Card, 검색, 홈 종목 목록, IntroSheet/BottomSheet | 역할별 모서리·44px 터치 영역·스크롤 가능한 시트 |
| Animations | 공통 버튼 CSS, 시트 등장, DebatePage 자동 스크롤 | reduced-motion 분기. 10% 재생 속도의 육안 검사는 미수행 |
| Icons | 홈 마크·기존 Icon·탭 | 기존 currentColor 아이콘 유지, 별도 패키지 없음 |
| Performance | package.json, CSS transition 속성, build | 새 런타임 의존성 없음. 성능 프로파일링은 미수행 |

## 수정한 항목

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| HIGH | web/src/components/ui.tsx:106; web/src/components/IntroSheet.tsx | 커스텀 role=dialog만 사용, 포커스·배경 스크롤 관리 없음 | 공유 native dialog와 포커스 순환·복귀·스크롤 잠금 | 키보드 사용 중 배경으로 이동하는 문제 방지 |
| MEDIUM | web/src/pages/HomePage.tsx:17 | 제안 종목 클릭 후 검색 결과를 한 번 더 선택 | 상세로 직접 연결, 최근 검색 저장 유지 | 주요 경로의 불필요한 단계 제거 |
| MEDIUM | web/src/components/ui.tsx:5; web/src/pages/HomePage.tsx | 모든 폭에서 480px 한 열 | 홈만 최대 960px, 768px부터 두 열 | 넓은 화면에서 종목과 안내를 함께 읽을 수 있음 |
| MEDIUM | web/src/index.css:10; web/src/components/TabBar.tsx:20 | 비활성 탭 대비 약 2.6:1, 작은 텍스트 | 어두운 보조색, 탭·설명 크기 보완 | 색 대비와 가독성 |
| MEDIUM | web/src/pages/HomePage.tsx:190 | 검색 실패 문구만 표시 | 실패 후 재시도와 오프라인 대기 설명 | 실패·연결 대기를 0개 결과와 구분 |
| MEDIUM | web/src/pages/DebatePage.tsx:22 | 새 발언마다 맨 아래로 이동 | 위로 읽을 때 따라가기 중단, 최근 발언 복귀 버튼 | 읽던 위치 보존 |
| MEDIUM | web/src/components/TodayTerm.tsx; web/src/pages/JudgePage.tsx; web/src/pages/HomePage.tsx | 32~40px 검색 삭제·근거·최근 검색, 작은 용어 링크 | 공통 44px 터치 토큰 | 모바일 조작 영역 확보 |
| MEDIUM | web/src/index.css:93; web/src/pages/DebatePage.tsx:48 | 모션 선호도와 관계없이 애니메이션·smooth scroll | prefers-reduced-motion 대응 | 모션을 줄여도 모든 정보·조작 유지 |
| LOW | web/src/components/ui.tsx:51; web/src/index.css | 큰 둥근 모서리·검색 그림자, 누름 반응 부재 | 역할별 모서리, 평평한 검색, 지정 속성만 transition, 0.96 누름 반응 | 공통 상태와 표면 정리 |
| LOW | web/src/pages/HomePage.tsx; web/src/components/TodayTerm.tsx; web/vite.config.ts; web/index.html | 용어가 종목 선택보다 앞섬, 판정 흐름 안내 부재 | 종목 우선, 판정 봉인 설명·퀴즈 진입, PWA 배경색 동기화 | 다음 행동과 서비스 순서를 분명히 함 |

## 검토 후 채택하지 않은 후보

- 시세·수익률을 홈에 새로 하드코딩: 실제 API 자료와 혼동될 수 있어 제외했다.
- 전 화면을 데스크톱 폭으로 확대: 토론·근거를 읽는 모바일 흐름을 유지하기 위해 홈에만 반응형을 적용했다.
- 모션 라이브러리와 카드별 등장 효과: 반복 사용 비용과 의존성 증가에 비해 이득이 작아 제외했다.
- 전체 운영 배포: 로컬 UI 요청 범위를 넘어 실행하지 않았다.

## 검증과 판정

- `cd web && npm run build`, `npm run lint`: 최종 구현 통과.
- 원본 `inspect.mjs --app`: 1440/768/390px 첫 방문 화면 0 FAIL. 첫 방문 시트 뒤 독립 패널 높이 차이 경고는 콘텐츠별 높이를 유지하기로 결정했다.
- 재방문용 점검: 원본 inspector를 임시 파일에 복사하고 테스트 브라우저에만 `bb.intro.v1=1`을 설정했다. 제품 코드에 안내 우회 기능은 넣지 않았다. 최종 배포 빌드의 1440/768/390px에서 **0 FAIL, 0 WARN**, 세 폭의 전체 캡처를 육안 검토했다.
- 변경 전 원본 점검에서는 보라 계열 색상 실패 1개와 낮은 텍스트 대비 등의 경고가 있었다. 이는 스타일 검사 결과이며 실제 사용자 만족도 측정은 아니다.
- 실제 브라우저: 초성 검색, 우선주 토론 불가 표시, 빈 검색 결과, 검색 API 요청 차단 시 실패 안내 및 차단 해제 후 재시도 성공, 홈 제안 종목 → 상세 → 가짜 워커 토론 완료 → 사용자 판정 화면 진입을 확인했다. 사용자 판정 제출은 하지 않았다. 로컬 DB에는 확인용 SK하이닉스 가짜 토론이 추가됐다.
- 시트: 최초 포커스·Tab/Shift+Tab 순환·Escape 종료·이전 버튼으로 포커스 복귀·배경 스크롤 잠금을 확인했다. reduced-motion 환경의 애니메이션 제거를 확인했다.
- 토론: 완료된 토론에서 위로 스크롤했을 때 최근 발언 복귀 버튼 표시 및 버튼으로 복귀를 확인했다. 새 SSE 발언이 도착하는 바로 그 순간의 읽기 위치 보존은 별도 실시간 검증하지 않았다.
- 오프라인 emulation에서는 TanStack Query가 요청을 일시 중지하는 것을 확인해 대기 상태 안내를 추가했다. 보완 후 오프라인 안내·자동 재개 분기는 별도로 재검증하지 않았다. 임시 Network 차단과 오프라인 설정은 해제했다.
- `lint.mjs`: 0 FAIL, 기존 로딩·진행 표시 pulse 관련 경고 3개. 진행 상태 표시에만 쓰며 reduced-motion에서 제거한다.
- 미검증: iOS/PWA 실기기, 스크린리더, 애니메이션 10% 재생 검토, 성능 프로파일, 실제 모델 연결·실제 판정 채점, 전체 회귀 테스트.

캡처 검토의 주관적 점수는 design 7 / usability 8 / creativity 6 / content 8, 가중 평균 **7.2/10**이다. 새 마크와 판정 순서의 표현은 서비스에 맞지만, 전체 시각 정체성은 아직 절제된 기본 UI에 가깝다. 모바일에서 이미 있는 토론이 많으면 제안 종목 목록은 아래로 밀리며, 첫 화면에선 기존 토론을 바로 읽는 경로가 우선한다. 사용자 평가로 검증한 점수는 아니다.

판정: **Approve — 이번에 확인한 범위의 즉시 수정할 항목은 해결**. 위 미검증 항목은 전체 서비스 QA 통과나 배포 승인으로 해석하지 않는다.

[변경 전 데스크톱](../output/ui-review-20261104/before-desktop.png), [최종 데스크톱](../output/ui-review-20261104/desktop-fold.jpg), [태블릿](../output/ui-review-20261104/tablet-fold.jpg), [모바일](../output/ui-review-20261104/mobile-fold.jpg), [모바일 전체](../output/ui-review-20261104/mobile-page-01.jpg), [최종 측정 JSON](../output/ui-review-20261104/report.json), [방향 기록](../output/ui-review-20261104/direction.json).

## 후속 개선: 토론 비교·근거 확인·결과 복기

사용자가 1~3번 개선을 지정해 같은 `feat/ui-experience-polish`에서 이어 작업했다. 아래는 앞선 홈·공통 UI 개선 이후의 범위다. 토론·판정 공개·채점 화면도 최대 960px을 사용하며, 판정 입력은 480px을 유지한다. 서버·워커 계약은 변경하지 않았다.

### 달라진 경로

1. 토론을 라운드별로 묶어 데스크톱·태블릿(768px 이상)에서는 매수·매도를 좌우로, 모바일에서는 매수 다음 매도로 읽는다. 추가 라운드의 여러 발언도 보존한다. ‘앞선 상대 주장’은 구조상 앞선 상대편 라운드로 연결하며, API에 없는 의미상의 반박 관계를 만들어내지 않는다. 완료된 토론은 첫 주장부터 연다.
2. 근거 칩은 내용을 확인하고, 옆 ‘담기’는 내 판정에 사용할 근거를 보관한다. 최대 2개이며 세 번째 선택으로 기존 근거를 몰래 교체하지 않는다. 같은 근거가 여러 발언에 등장해도 선택은 하나다. 같은 탭의 토론→판정 이동·새로고침에 유지하고, 성공적으로 제출하거나 내 기록 삭제로 세션을 초기화하면 제거한다.
3. 근거 시트는 발언의 인용값·토론 기준일·근거 ID·출처 구분·양측 해석을 나누어 보여준다. PX.CLOSE, VAL.PER_TTM, VAL.PBR, VAL.ROE_TTM, VAL.OP_MARGIN_TTM, VAL.MKTCAP은 기존 RAG 수치 API로 저장 수치·수치 기준일·출처를 별도 조회한다. 나머지 근거나 제공되지 않은 원문 URL은 ‘현재 제공되지 않음’으로 표시한다. 발언의 값을 원본 조회 결과로 표시하지 않는다. 숫자 대조와 전망·해석의 타당성을 구분한다.
4. 판정 화면에서 담아온 근거를 다시 확인·해제할 수 있다. 토론 근거 재생이 끝나기 전에는 제출을 막고, 실제 발언에 있는 근거만 제출한다.
5. 공개 결과와 채점 화면의 첫 비교 블록은 같은 기간의 **내 판정 / AI 판정 / 실제 결과**다. 3거래일 중간·7거래일 최종 결과를 전환하면 적중 여부·초과수익·종목/코스피 수익률이 함께 바뀐다. 응답 배열 순서에 의존하지 않고 7일 결과를 우선한다. 보류 경계는 ±holdBand를 포함한다.
6. 실제 결과가 없으면 예상일과 자료 대기를 표시하고, 일정 조회 실패를 ‘채점 전’으로 단정하지 않는다. 내 선택과 AI의 결정적 근거를 비교하고 겹치는 근거·내 메모를 함께 보여준다. 인용 방향의 일치가 개별 근거의 인과적 타당성을 입증하는 것처럼 표현하지 않는다.

### 후속 검토(full)

React 19 / Tailwind 4의 기존 컴포넌트·토큰을 사용했고 새 런타임 의존성은 추가하지 않았다.

| 범주 | 근거 | 확인 범위 |
| --- | --- | --- |
| Typography | 토론·근거 시트·공개 결과·채점의 3폭 캡처 | 주장·해석·출처·채점 기간의 읽기 순서와 모바일 줄바꿈 |
| Surfaces | StatementBubble, EvidenceSheet, JudgmentComparison, EvidenceComparison | 두 주장 정렬, 44px 조작, 공유 시트·선택 상태 |
| Animations | 완료 토론 최초 위치, 기존 따라가기와 reduced-motion | 완료 토론은 위에서 시작. 10% 속도 재생·실시간 신규 SSE 순간 검사는 미수행 |
| Icons | 담기/해제 체크, 근거 이동, 기존 currentColor 세트 | 아이콘에만 의존하지 않는 버튼명과 aria-pressed |
| Performance | build·package.json·메타데이터 조회 시점 | 수치 조회는 명시적 조작 시만 실행, 새 패키지 없음. 프로파일링은 미수행 |

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | web/src/pages/DebatePage.tsx; web/src/lib/evidence.ts | 발언을 채팅 순서로만 표시 | 라운드별 좌우/상하 비교, 앞선 상대 주장 링크 | 같은 논점을 오가며 읽기 |
| MEDIUM | web/src/components/StatementBubble.tsx; web/src/lib/useEvidencePicks.ts | 읽으면서 근거를 기억해야 함 | 최대 두 개 담기·초안 보관·해제 | 읽기와 판정의 선택 연결 |
| MEDIUM | web/src/pages/JudgePage.tsx | 선택이 이전 화면에서 이어지지 않음, 세 번째 선택이 첫 선택을 대체 | 보관 근거 복원·명시적 해제·확인 시트 | 조용한 선택 변경 방지 |
| MEDIUM | web/src/components/EvidenceSheet.tsx; web/src/components/VerdictText.tsx | 인용값·원본 대조·용어 풀이의 경계가 약함 | 공통 근거 확인, 출처 분류·기준일·양측 해석·지원 지표만 별도 수치 조회 | 확인한 것과 해석의 한계 구분 |
| MEDIUM | web/src/components/JudgmentComparison.tsx; web/src/lib/score.ts | 내/AI 판정과 수익률·채점 기간이 분산 | 같은 기간의 세 결과를 함께 표시, 명시적 기간 전환 | 중간 결과와 최종 결과 혼동 방지 |
| MEDIUM | web/src/components/EvidenceComparison.tsx; web/src/pages/RevealPage.tsx; web/src/pages/ScorePage.tsx | 내 선택·AI 근거·메모가 분산 | 나란히 비교, 공통 선택 표시·근거 열기·메모 | 판단 근거를 복기 |
| MEDIUM | web/src/pages/ScorePage.tsx | ‘그 근거를 더 무겁게 봤다면 결과가 달랐을 것’이라는 인과 추정 | 인용 방향과 이후 주가의 비교로 한정 | 채점 결과를 근거의 진실성으로 과장하지 않음 |
| LOW | web/src/components/ui.tsx; web/src/components/ScoreBits.tsx | 긴 시트 전체에 포커스 외곽선, 데이터 구간을 CSS gradient로 구성 | 정적 시트 내용에 최초 포커스·실제 조작에 포커스 표시, 평면 색 구간 | 긴 자료 읽기와 표면 일관성 |

채택하지 않은 후보: 근거 ID만 보고 원문 링크/자료 공급자를 추정하는 방법, 실모델 추가 호출로 빠진 자료를 채우는 방법, 답변 데이터에 없는 반박 대상 관계를 단정하는 방법은 제외했다. 보관 초안은 새로운 사용자 프로필 저장소를 만들지 않고 탭 세션 안으로 제한했다.

### 후속 검증 결과와 한계

- 최종 `npm run build`, `npm run lint`, `node --test tests/evidence.test.ts` 통과. Node 26에서 7개 테스트: 비대칭 라운드·복수 추가 발언·앞선 상대 링크·2개 선택 제한·손상 초안·±2%p 경계·정렬되지 않은 3/7일 결과.
- 실제 localhost:5173 + Spring fake 워커: 근거 2개 선택·세 번째 비활성·시트의 양측 해석·새로고침 후 초안 복원·판정 화면의 두 선택 유지 확인. 기존 사용자 판정은 새로 제출하지 않았다. 실제 로컬 API에 이미 저장된 삼성전자 3/7일 결과의 전환도 확인했다. 이는 가짜 워커의 로컬 자료이며 실제 시장·실모델 검증이 아니다.
- 별도 localhost:5180 임시 QA 프록시로 독립 게스트를 사용했다. 실제 Spring API에서 제출 전 reveal 403, 제출 후 공개·선택 근거/메모 저장·성공 후 초안 제거·채점 대기를 확인했다. 확인용 판정 1건이 로컬 DB에 추가됐으며 사용자 계정의 판정은 변경하지 않았다.
- QA 프록시의 명시적 채점 fixture에서는 3일만 채점된 상태와 7일 최종 상태를 확인했다. 3일 +4.50%p/매수, 7일 -3.20%p/매도 전환에 따라 결과·적중·수익률이 함께 바뀌었다. fixture는 노란 QA 안내가 있는 별도 주소에만 적용했고 DB 채점 결과는 바꾸지 않았다.
- 토론 비교와 QA 채점 화면 각각 배포 빌드 390/768/1440px `inspect.mjs --app` **0 FAIL / 0 WARN**, 세 폭 전체 캡처 육안 확인. 앱 모드 source lint는 0 FAIL, 기존 진행 점 pulse 경고 1개(진행 상태만 표시, reduced-motion 제외).
- 미확인: 실워커 저장 수치 조회 성공 경로(현재 fake 모드에 실워커 없음), 실시간 새 SSE 도착과 동시에 스크롤 중인 경우, iOS/PWA 실기기·스크린리더, 전체 API·워커 회귀. 원문 URL은 기존 브라우저 API에 없어 추가하지 않았다.

자체 캡처 검토: design 7.5 / usability 8 / creativity 7 / content 8, 가중 평균 7.6/10. 라운드 비교와 선택 근거의 연결은 좋아졌지만, 모바일 긴 토론의 실제 사용 피로와 저장 수치 연동은 후속 검증이 필요하다. 사용자 연구 점수가 아니다. 이번 확인 범위는 Approve이며 위 미검증 사항을 전체 배포 승인으로 해석하지 않는다.

확인용 이미지: [토론 데스크톱](../output/ui-review-20261104/rounds/desktop-fold.jpg), [토론 모바일](../output/ui-review-20261104/rounds/mobile-page-01.jpg), [근거 시트](../output/ui-review-20261104/evidence-sheet-final.png), [실제 로컬 API 공개 결과](../output/ui-review-20261104/reveal-local-api.png), [채점 fixture 모바일](../output/ui-review-20261104/score-fixture/mobile-page-01.jpg). 결과 측정 JSON도 각 캡처 폴더에 있다.


## 후속 4~5번: 첫 체험과 모바일 사용성 (2026-11-04)

완료된 토론을 홈의 ‘바로 읽을 수 있는 토론’으로 먼저 보여주고 진행 중인 토론은 별도로 표시한다. 새 토론이 없으면 첫 선택 방법과 과거 퀴즈를 안내한다. 종목 상세에서는 완료된 토론 읽기·진행 중 토론 보기·새로 시작하기를 구분한다. 첫 이용 안내도 토론 둘러보기와 퀴즈로 나누었다.

준비 중에는 실제 snapshot/발언/중재자 이벤트에 따라 자료 고정→양측 토론→AI 판정을 표시한다. 임의 퍼센트나 남은 시간을 만들지 않는다. 연결 실패는 토론 실패와 구분하고 동일 토론에 다시 연결한다. 기다리는 동안 다른 토론·퀴즈로 이동할 수 있으며 AI 판정은 제출 전까지 봉인된다.

판정 선택·확신도·최대 200자 여러 줄 메모는 같은 탭의 sessionStorage에 즉시 보관한다. 성공 제출·세션 초기화 시 제거하고 저장 실패는 화면에 알린다. 모바일 메모는 16px 글자로 표시하고 입력 포커스 중 제출 영역을 문서 흐름으로 돌린다. 근거 창은 visualViewport 높이를 따라가고 상단 닫기를 유지한다. 새 페이지는 위에서, 브라우저 뒤로 가기는 읽던 위치로 복원하며 사용자가 스크롤·터치·키보드를 조작하면 복원을 중단한다.

PWA는 입력 도중 강제로 새로고침하지 않고 ‘새 화면으로 업데이트’ 버튼으로 전환한다. 기존 구버전 PWA가 이미 활성화된 로컬 탭은 입력 상태를 먼저 확인한 뒤 잠시 다른 페이지로 이동해 구버전 클라이언트를 해제했다. 실제 localhost:5173 탭에서 최신 제목·여러 줄 메모 입력과 기존 담은 근거 2개를 확인했다.

### 확인한 범위

- 최종 build, lint, Node 테스트 13개 통과. 기존 7개에 피드 분류·실제 준비 단계·초안 복원/손상 처리·연결 실패 구분·스트림 초기화/중복 방지 6개 추가.
- 홈 배포 빌드 320×568, 390×844, 768px, 1440px 측정 0 FAIL/0 WARN 및 전체 이미지 육안 확인. 원본 검사 스크립트는 320px 높이 기본값이 200px여서 임시 검사본에 568px을 지정했고, 재방문 홈 측정을 위해 독립 검사 세션에서만 초기 안내를 제외했다. 첫 방문 안내는 별도 UI로 확인했다.
- 독립 localhost:5181 테스트 fixture(노란 검증 안내, 더미 토큰)로 완료/진행 구분, 빈 상태, 자료 수집 단계, 연결 오류→동일 토론 재연결 완료를 확인했다. fixture는 DB를 바꾸지 않으며 실제 모델 검증이 아니다. 검증 서버는 확인 후 종료했다.
- fixture의 매수·확신도90%·여러 줄 메모가 새로고침과 PWA 수동 업데이트 후 유지됨을 확인했다. 390×420 화면에서 메모 bottom314px, 하단 영역 position:static. 근거 창은 top42px/bottom420px, 내부 스크롤과 상단 닫기, 닫은 뒤 열었던 근거 버튼으로 포커스 복귀 확인. 뒤로 가기로 완료 발언 재생 후 읽던 부근으로 복원됨을 확인했으며 완전히 동일한 픽셀 위치를 보장하는 검증은 아니다.
- iPhone17 / iOS26.5 Simulator Safari에서 홈·판정 렌더와 최초 안내 닫기를 확인했다. 자동화 도구가 Simulator의 웹 터치/키보드를 충분히 조작하지 못해 실제 iOS 소프트 키보드와 터치는 미검증이다. Chromium의 짧은 뷰포트 검사를 실제 iPhone 검증으로 대체하지 않는다.
- 미확인: 실제 기기, 설치형 standalone PWA, 스크린리더, 새 SSE 도착 순간의 수동 스크롤 경합, 전체 API/워커 회귀. 실모델·유료 호출·배포·판정 제출 없음.

캡처: [모바일 홈](../output/ui-review-20261104/first-experience-mobile/home-local-final.png), [짧은 화면 메모](../output/ui-review-20261104/first-experience-mobile/short-viewport-memo.png), [짧은 근거 창](../output/ui-review-20261104/first-experience-mobile/short-sheet.png). 홈의 네 폭 전체 캡처와 측정 JSON은 같은 폴더의 home/에 보관한다.

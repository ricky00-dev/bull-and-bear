# 작업 로그

작업을 마칠 때(또는 PR을 올릴 때) **맨 위에** 한 항목을 추가한다. 다음 사람이 이것만 읽고 이어서 할 수 있게 쓴다.
Claude Code는 세션 시작 시 이 파일의 최근 항목이 자동으로 보인다 (SessionStart 훅). Codex는 `AGENTS.md` 안내에 따라 `./scripts/session-brief.sh`를 실행해 본다.

형식:

```
## YYYY-MM-DD · 이름 · 영역(api / web / ai-worker / docs)
- 한 것: 무엇을 했는지 (PR 번호)
- 진행 중: 끝나지 않은 것, 어느 브랜치에 있는지
- 다음: 다음에 할 일 (누가)
- 막힘·결정 필요: 다른 사람 확인이 필요한 것
```

이전 기록: [2026-11-02 이전 작업 로그](archive/WORKLOG-before-20261102.md). 최근 인계는 아래 최신 항목부터 읽습니다.

---

## 2026-11-03 · Codex · docs, api, web, ai-worker
- 한 것: 문서 정리 검토 후 9dbc6f2(docs: RAG 운영 안내와 평가 기록 정리)로 커밋. origin/develop 004879c의 학습 부가 기능·CI·계정 삭제 변경을 현재 chore/worker-http-live-validation에 병합. WORKLOG 한 곳의 충돌은 양측 기록을 보존해 해결했으며 과거 항목은 archive와 대조(이동 경로 수정 제외 내용 보존).
- 진행 중: 로컬 통합 완료. 원격 푸시·PR 병합은 하지 않음.
- 다음: test_rag_evidence.py의 test_http_facts_missing_concept_auth_and_no_model_or_market_calls 실패를 조사하고 Java17 및 DB 통합 환경에서 API 검증 후 원격 반영 검토.
- 막힘·결정 필요: 문서 상대 링크152개·git diff 공백 검사·웹 build/lint 통과. 워커 전체650 passed/78 skipped/1 failed(83.84초); 실패는 origin/develop WORKLOG에 기존 보고된 검색503 RETRIEVAL_UNAVAILABLE 및 snapshot publication binding unavailable과 동일. 해당 테스트 파일은 origin/develop과 동일하며 이번 병합은 워커 코드를 변경하지 않음. uv가 PATH에 없어 기존 .venv Python으로 검사. API는 gradlew.bat의 한글 경로 문제를 직접 Java 호출로 우회했으나 Java17 toolchain 부재로 실행 불가(Java8 기본/Java23 설치 확인). Docker/실모델/배포 검증 없음.


## 2026-11-03 · Codex · docs
- 한 것: git fetch origin 후 원격·로컬 커밋 상태 비교. 현재 chore/worker-http-live-validation은 원격 동일 브랜치와 964031a로 일치(0/0). 로컬 develop은 origin/develop(004879c)보다 8커밋 뒤이며, 현재 브랜치는 origin/develop 대비 고유 1커밋/미반영 8커밋.
- 진행 중: 기존 문서 정리 미커밋 변경 유지(추적 파일 16개, 미추적 파일 11개). 이번 비교 기록만 추가.
- 다음: 문서 정리 변경을 검토·커밋한 뒤 최신 develop 통합 및 PR 검토.
- 막힘·결정 필요: merge/rebase/pull/commit/push는 실행하지 않음. session-brief.sh는 기존 CRLF 문제로 실행 실패하여 git 명령과 WORKLOG 직접 조회로 확인. 제품 테스트는 상태 조회 작업이므로 실행하지 않음.


## 2026-11-02 · Codex · docs
- 한 것: 이전 RAG 계획·WIP 이관·일차별 기록과 11/02 이전 작업 로그를 docs/archive로 보관. RAG-OPERATIONS에 현행 설치·이관·큐·평가 안내 통합, 장기 문서는 설계·확장 조건으로 축약. 다종목 실측·지표 감사·단일 HTTP 보고서를 evaluations로 모으고 44개 보고서 색인 추가. 웹 라우트·성적표, API 재사용 설명, 선공·병렬화 제안 설명을 현재 코드와 대조해 수정.
- 진행 중: 문서 정리 완료, 현재 브랜치 chore/worker-http-live-validation의 미커밋 문서 변경. 기존 제품 코드·평가 JSON·대화록·계약은 변경하지 않음.
- 다음: 현재 안내는 docs/README.md에서, 이전 계획은 archive/README.md에서, 실측 근거는 evaluations/README.md에서 찾는다. 기능 변경 시 해당 현행 안내만 갱신하고 당시 실험 기록은 보존한다.
- 막힘·결정 필요: 상대 파일 링크 235개·코드 블록 닫힘·diff 공백 검사 통과. 이동/보관 원문 6개와 기존 WORKLOG 107항목, 분리한 다종목 결과의 내용 보존 확인(링크·보관 표시 제외). RAG CLI 4개 진입점 --help 성공. 문서 변경이므로 제품 테스트·실모델·배포 재실행 없음. 기존 session-brief CRLF 문제는 범위 밖으로 유지.

## 2026-11-02 · Codex · docs, ai-worker, api, web, deploy
- 한 것: 사용자 요청에 따라 문서 정리와 기존 전체 변경의 커밋 대상 검토 완료. docs/README에 문서 색인 추가, 루트·API·워커 README와 ARCHITECTURE의 구조·중복 방지·모델·비용/재시작 설명 정정. ROADMAP에서 단일 구현과 운영 활성화를 구분하고 기존 일정은 유지. 최신 인계를 현재 구현/실측 비용/검증 한계/남은 순서로 재작성하고 과거 보고서에서 연결. 대화록 JSON 표시만 정리해 원문 보존 확인.
- 진행 중: chore/worker-http-live-validation에 기존 KRX 수정, 검토 문맥·HOLD/재작성 개선, 영속 비용 장부, 실측 실행기·보고서와 이번 문서 정리 45개 파일을 함께 보존. 예비 운용 목표는 계속 일시정지 상태. 커밋·원격 반영 상태는 git log/status 및 origin의 해당 브랜치로 확인한다.
- 다음: 목표 재개 시 docs/evaluations/worker-goal-readiness-20261102.md의 남은 작업 순서를 따른다. develop 통합은 별도 리뷰·PR 절차다.
- 막힘·결정 필요: 문서 상대 링크 72개·실측 JSON 4개 파싱·대화록 내용 보존 검사 통과. 이번에는 문서만 추가 수정하여 기존 Python650+후속51/8·Spring fixture5·웹 build/lint 증거를 사용했고 코드 테스트를 다시 실행하지 않음. 신규 시장/모델 호출·배포 없음. 운영 대상 미정, 실모델 1쌍 완주 미완료, 기존 $3 승인 누적 $0.8975489 및 잔액/예약 부족을 그대로 보존. 실제 .env·원자료는 커밋 대상에서 제외.

## 2026-11-02 · Codex · ai-worker, api, deploy, docs
- 한 것: 잔여 예산 내 후속 검증 승인으로 v8 실측. 토론6발언 통과·중재자 스냅샷 도구3종 호출 후 HOLD 후보 반려, 다음 요청은 비용 예약 거부. 토론292.570초/29요청/$0.2380716, 단일0요청 사전거부. 누적$0.8975489·잔여$2.1024511, 장부 미확정0·서버종료. 원문/JSON/보고서 worker-goal-live-v8-20261102에 보존.
- 한 것: 선택적 운영 HTTP 영속 비용 장부 추가(동시 예약/재시작/미확정 보존/SDK 재시도0/설정 초기화 방지). 호출 전 거부와 미확정 실패 구분, 현재 실행의 기존 usage.cost_usd로 Spring 정산. Sonnet 캐시 읽기 단가$0.10/100만 정정. Compose 설정 템플릿·WORKER-OPERATIONS 안내 추가, 실제 .env/운영 설정은 변경하지 않음.
- 진행 중: 전체 Python650 passed/78 skipped(81.34초), 이후 관련51개·최종 설정 삭제 방지8개 통과. 실제 임시 Spring/PostgreSQL/HTTP fixture5 passed(53.02초), Java 선택 검사/bootJar·DB recovery7개 통과. 통합 임시 프로세스 종료 및 포트 리스너 없음. 실제 v7 자료의 로컬 백업/복원/2회 재시작·결과/SSE/재사용/인증·손상 거부 확인(신규 모델/시장0호출).
- 다음: **사용자가 “일단 작업은 여기까지 하고 결과 공유”를 요청하여 목표 일시정지. 추가 호출/배포/작업 없음.** 재개 시 docs/evaluations/worker-goal-readiness-20261102.md 최종 인계부터 읽는다. 최신 비용 체인 run은 data/http-live-20261102-123540-3313ca.
- 막힘·결정 필요: 1쌍 완주·반복 품질·실모델 Spring/웹 전체 경로·실배포 미완료. 잔액이 Sonnet 예약$2.16보다 작아 같은 정책으로 추가 호출 불가(실제 지출$3 소진 아님). 운영 장부는 코드/오프라인 검증 상태이며 실제 활성화하지 않음. Docker 없음·배포대상 선택 미확정. 모든 변경 미커밋, 기존 사용자 변경 보존, 커밋/푸시/실배포 없음.

## 2026-11-02 · Codex · ai-worker, docs
- 한 것: 사용자 승인 추가1쌍을 v7로 실행. 단일 HOLD 완료(16.128초/4요청/$0.1665040), 토론 매도 반박 실패(295.609초/21요청/$0.0780479), 추가$0.2445519·이전 포함 누적$0.6594773·잔여$2.3405227. 동일 스냅샷/usage 일치·재사용/SSE재생·미확정0·서버종료 확인. 상대 인용을 자기 주장으로 오인한 검토와 재작성 중 새 근거 소실을 원문으로 확인.
- 진행 중: 실행 종료 후 v8에 인용 구간/과거 발언자 매핑과 새 근거 보존 피드백 보완. 검토 결과 자동 통과·조건 완화 없음. 관련136 passed(10.08초), 비용장부 검증 네트워크0. v8 실모델 효과는 미검증, 기존 미커밋 변경 보존.
- 다음: docs/evaluations/worker-goal-live-v7-20261102.md/JSON에 원문·반려·누적 비용 기록. 토론 완주와 미도달 중재자 실제 도구 검증 우선. 추가 유료 실행이 허용될 경우 최신 --prior-run은 data/http-live-20261102-122447-3ddbd2. 기존 첫실패 기록 보존.
- 막힘·결정 필요: 승인된 추가1쌍 실행 완료, 세 번째 유료 실행 없음. 1쌍 동시 완주·다종목/반복 품질·실제 Spring/브라우저 연결·배포 아직 미검증. Docker 없음·배포대상 미확정, 운영 토큰/공용 확정 비용 상한 별도 필요. 단일1회 성공은 예측 정확성 또는 운용 준비 완료가 아님. 계약/.env/배포 변경·커밋·푸시 없음.

## 2026-11-02 · Codex · ai-worker, docs
- 한 것: 첫1쌍 실패 이후 비용 없는 후속 개선. 정책v7에서 관측된 같은 기간 상대수익·명시적 유지 가정·이탈 위험을 갖춘 조건부 예측과 사실/인과 단정을 구분, 자료 부족만의 HOLD·잘못된 인용 차단 유지. 유료 실행기에 --prior-run 누적 지출 차감과 --check-budget 추가, 과거usage 재계산/보고서 대조·미확정/미종료/변경장부 거부·기존장부 덮어쓰기 방지.
- 진행 중: 관련128 passed(9.79초), 비용검사에서 총$3/기존$0.4149254/잔여$2.5850746/네트워크0 확인. v7 실모델 효과 미검증, 신규 유료호출0. 기존 미커밋 변경 보존.
- 다음: 사용자에게 기존 총$3 내 추가1쌍 허용 여부 질문. 허용 시 직전 run을 --prior-run으로 명시해 실행하고, 실패해도 기록 보존. 상세 명령/정책 경계는 docs/evaluations/worker-goal-live-20261102.md.
- 막힘·결정 필요: 최초1쌍 승인은 소진, 추가 실행 답변 대기. Docker 없음·배포대상 미확정 유지. 누적 비용 보조기는 순차 파일럿용이며 운영 다중 프로세스 공용 예산이 아님. v7은 조건부 가정의 허용 범위를 명시한 정책 변경이며 과거 후보의 사람 승인 또는 예측 정확성 보장이 아님. 계약/.env/배포 변경·커밋·푸시 없음.

## 2026-11-02 · Codex · ai-worker, web, docs
- 한 것: 사용자가 이번 작업 총$3/우선1쌍을 승인해 정책v5의 실제 HTTP 토론·동일 스냅샷 단일 분석 실행. 토론209.959초/17요청/$0.0557934(3발언 뒤 매도반박 실패), 단일43.768초/7요청/$0.3591320(HOLD3회반려), 합계$0.4149254·미확정0·둘실패. 코스피 비교Fact 정상·동일스냅샷·사용량 일치·실패 재생/멱등성·서버종료 확인. 별도 fixture 브라우저에서 검색→토론봉인→사용자판정→공개 확인. StockPage의 과거 연동/시간 단정 안내 수정, build/lint·실화면 확인, 임시4프로세스 종료.
- 진행 중: 정책v6에 재작성시 전체3문장/불확실성·인용 유지 지침 및 실제 문장수 피드백 추가, 영향범위110 passed(9.50초). v6 실모델은 미검증. 기존 변경 보존, 미커밋 상태.
- 다음: HOLD 반려 기준·조건부 추론 검수 → 추가 유료 실행 범위 확정 후 누적 한도를 적용해 재실측 → 완주 뒤 종목 확대/실제 Spring·웹/운영환경 검증. 상세 docs/evaluations/worker-goal-live-20261102.md 및 worker-goal-readiness-20261102.md.
- 막힘·결정 필요: 첫1쌍 승인만 사용했으므로 남은 금액이 있어도 추가 호출0. 사용자가 Docker 없음 확인, 배포 대상 미확정. 두 실패는 운영 준비 미완료의 근거이며 fixture 성공으로 대체하지 않음. 검토기의 모든 반려를 사람 승인한 것은 아님. 계약/.env/RAG설정·커밋·푸시·배포 변경 없음.

## 2026-11-02 · Codex · ai-worker, docs
- 한 것: 사용자 요청으로 워커 예비 운용 목표를 내장 goal에 등록. 기존 KRX 수정 관련51개 재검증, 검토기에 전체 고정 Fact와 인용 범위를 구분해 전달, 중재자 SnapshotTools 조회 및 HOLD 조건부 예측/한계 지침 보완(7d-concise-v5). 기존 유료 실행기에 추가 라운드0 선택과 provenance 기록·보호 회귀 추가. 기존 미커밋 실측/KRX/문서 작업 보존.
- 진행 중: chore/worker-http-live-validation에서 미커밋 작업. 전체 Python587 passed/78 skipped, 최종 영향범위94 passed, 웹build/lint 통과. Spring/PostgreSQL/HTTP5 passed(58.52초), Java 선택검사/bootJar 및 DB recovery7통과, 임시 프로세스 전부 종료. 상세 인계는 docs/evaluations/worker-goal-readiness-20261102.md.
- 다음: 이번 유료 총한도 답변 후 수정된 코드의 새 동일 스냅샷 토론/단일1쌍 → 성공 시 반복 확대 → 실제 Spring/웹 및 배포 검증.
- 막힘·결정 필요: 신규 유료 호출은 예산 답변 대기(현재0회). preflight는 개발용WORKER_TOKEN으로 실패, Docker PATH 미발견·운영 서버 정보 미확인. fixture 통과는 실모델 품질/실배포 성공이 아님. 계약/.env/RAG 설정·커밋·푸시·배포 변경 없음. 컨텍스트 부족 시 새 세션 인계는 사용자 허용.

## 2026-11-02 · Codex · docs
- 한 것: 문서 목록·주요 안내·평가 기록 표제와 대표 본문을 검토하고 코드와 대조. evaluations Markdown 37개, WORKLOG 667줄(이번 항목 추가 전), RAG 계획/진행/운영 안내의 역할 혼재 확인. API README의 중복 방지 미구현 설명은 V4 제약과 불일치, ARCHITECTURE의 Opus 설명은 현재 Sonnet 기본 설정과 불일치, ROADMAP 단일 모드는 구현/실운용 상태 분리 필요.
- 진행 중: 검토 완료. 문서 삭제·이동·통합은 하지 않았으며 기존 미커밋 코드·실측 자료 보존.
- 다음: 과거 계획·이관 메모는 archive로 분리, RAG-WEEK-ONE의 현행 명령은 운영 안내로 정리하고 구현 일지는 보존. README/ROADMAP 현재 상태 갱신, 평가 기록은 날짜·revision·fixture/실모델·후속 기록을 연결하는 색인으로 탐색 개선.
- 막힘·결정 필요: 평가 보고서 전수의 원자료·수치 재검증은 범위 밖. session-brief.sh는 기존 CRLF 오류로 실패하여 git/WORKLOG/열린 PR 직접 조회로 대체. 코드 테스트·유료 호출·배포 없음. 기록 삭제 전 고유 실측 근거와 문서/스크립트 참조 확인 필요.

## 2026-11-02 · Codex · docs
- 한 것: 뉴스 원문 저장 가능 여부 조사. 실제 실측은 RAG 비활성이고 Naver description→NewsArticle.summary→Snapshot Fact.note→get_news 경로임을 코드·저장 자료로 확인. 공식 NAVER API HUB 문서도 제목·요약 패시지·원문 URL 제공을 명시. DocumentInput의 full_text 저장 형식은 이미 있으나 원문 수집기와 뉴스 문단의 운영 토론 근거 연결은 미구현임을 구분.
- 진행 중: 원인 설명과 후속 구현 방향 정리 완료. 본문 수집·색인·공개 근거 투영은 아직 변경하지 않음.
- 다음: 사용 가능한 원문 공급 경로 선정→본문·수집/발행/수정 시각·출처 저장→문단 검색 및 근거 문맥 구성→토론 시작 전 Snapshot 고정. 생성기·검토기에 같은 근거 문단 제공, 요약만 확보한 경우 명시. 별도 검토 문맥/HOLD 문제도 함께 평가.
- 막힘·결정 필요: 저장은 가능하지만 언론사별 원문 수집·보관 조건은 별도 확인 필요. 자동 본문 크롤링·유료 공급자 도입·모델 호출·기능 코드 변경·테스트 실행 없음. 기존 원본/미커밋 작업 보존. 공식 문서 https://api.ncloud-docs.com/docs/naver-api-hub-search-news 확인.

## 2026-11-02 · Codex · docs
- 한 것: 사용자 요청으로 실제 삼성전자 토론 로그를 worker-http-live-20261102-transcript.md 대화록으로 추출. 검증 통과6발언의 주장·본문·근거 해석, 반려5후보와 피드백, 중재자 반려3후보를 원문 그대로 수록하고 상태 구분.
- 진행 중: 대화록 작성 완료. 기존 미커밋 실측·KRX 수정·문서 변경 보존.
- 다음: 대화록에서 검토 문맥 누락·HOLD 추론·기사 해석 문제를 검토하고 기존 실측 보고서의 개선 순서로 진행.
- 막힘·결정 필요: 저장된 JSONL/응답에서만 추출했으며 추가 모델 호출·비용 없음. 원문 필드 포함 여부와 건수(6/5/3) 확인. 이 기록은 코스피 누락 수정 전 실행이며 중재자 후보는 확정 판정이 아님. 제품 코드·환경 설정 변경 및 테스트 재실행 없음.

## 2026-11-02 · Codex · ai-worker, docs
- 한 것: 사용자 요청으로 develop bb28c57의 실제 Uvicorn/HTTP+Anthropic 토론·단일 판정을 삼성전자 동일 스냅샷으로 실측. 토론 339.177초/33요청/$0.2524194, 단일 36.560초/6요청/$0.1827160, 합계 $0.4351354. 토론 발언6개는 통과했으나 중재자 후보3회 반려, 단일도 의미·문장수 검증3회 반려로 실패. 요청 재사용·SSE 재생·인증·공개/감사/장부 usage 일치 확인. 상세 원인·지표는 docs/evaluations/worker-http-live-20261102.md 및 JSON에 기록.
- 진행 중: 실제 KRX 응답의 보조지수 빈 값 때문에 정상 코스피까지 버리는 오류를 수정하고 회귀 추가. chore/worker-http-live-validation에 실행기·수정·실측 보고서가 미커밋 상태. 기존 분석 WORKLOG 항목 보존. 검토기의 선택 Fact 문맥 누락 및 HOLD 근거 기준 개선은 미완료.
- 다음: 검토 문맥에서 실제 존재하는 종가/변동성을 날조로 오판하는 사례와 미인용을 분리하고, 뉴스 왜곡·없는 인과 거부를 유지하는 회귀 구성. 정상 코스피 입력으로 HOLD 생성/검증 기준 점검 후 동일 스냅샷 토론/단일 재실측, 1쌍 완주 뒤 종목·반복 수 확대.
- 막힘·결정 필요: 수정 전 신규2실패/4통과, 수정 후 KRX·데이터 정합성·HTTP market·snapshot 51 passed(5.16초). 실제 KRX 재조회로 3/7/21거래일 비교 Fact9개·누락0 확인(7.156초, 추가 LLM0). 수정 후 유료 재실행·Spring/브라우저·배포·전체 회귀는 미실시. 실측39응답 usage 모두 확보, $3/48요청 보호 한도 미도달·서버 종료 확인. 비용은 공식 단가 환산이며 청구/크레딧 차감 미확인. 초기 계측 SDK 타임아웃 타입 오류는 모델 호출0에서 수정해 별도 기록. session-brief 기존 CRLF 오류로 git/문서 대체. 계약·프롬프트·환경파일·RAG 설정 변경 및 커밋/푸시 없음.

## 2026-11-02 · Codex · docs
- 한 것: 최신 develop bb28c57 기준 구현 상태와 잔여 우선순위 정리. 핵심 체험·단일 비교/성적표·RAG 저장/조회 구현과 실제 운용/품질 검증을 구분. 단일 모드·성적표의 ROADMAP 미체크가 코드와 불일치함을 확인. 열린 PR #26은 미통합으로 분류.
- 진행 중: 분석 완료. 기능 코드·설정·일정 변경 없음.
- 다음: 실제 공급자/모델 전체 경로 반복 검증과 배포 준비 → 예비 운용11/4 → 검증기/채점·실험 정책 고정11/10 → 정식 운용11/11. RAG 검수 corpus·독립 평가셋은 병행하되 미충족 시 비활성 유지. 전시 모드/공유/로그인은 핵심 경로 안정화 이후.
- 막힘·결정 필요: 직전 PR 검토의 PostgreSQL 포함648 passed/외부 Spring5 skipped·Java15·웹build/lint 결과를 근거로 사용, 이번 재실행 없음. 기본 설정은 fake/전향 및 단일 비활성이나 실제 배포 환경의 실행 상태는 확인하지 않음. 운영 Docker/TLS·실모델 반복 품질/비용·사람 검수 자료·기업행사 미보정 정책 확인 필요. session-brief 기존 CRLF 오류로 git/문서 직접 조회. 본 항목만 미커밋으로 추가.

## 2026-11-02 · ricky00-dev (Claude Code) · api, web
- 한 것: 개인정보 처리방침·이용약관 페이지(`/policy/privacy`, `/policy/terms`)와 내 기록 삭제(`DELETE /api/me`). 삭제는 판정·채점·메모·퀴즈 기록·닉네임·계정을 지우고, 공용 토론은 남기되 requested_by만 비움. 웹은 마이 탭에서 한 번 더 확인 후 삭제 → 토큰·최근 검색어 버리고 새 게스트로 홈. 방침 내용은 실제 저장 항목 기준 (IP·기기 정보 미저장, Caddy 접근 로그 없음, 판정·메모는 워커/LLM에 안 보냄).
- 진행 중: 없음.
- 다음: 문의처(팀 메일) 정해지면 `web/src/pages/PolicyPage.tsx`의 CONTACT 교체. 카카오 로그인 붙이면 방침의 저장 항목 갱신.
- 막힘·결정 필요: (jangwonii) develop의 `ai-worker/tests/test_rag_evidence.py::test_http_facts_missing_concept_auth_and_no_model_or_market_calls`가 로컬·CI 모두 실패 (`/rag/search` 503 RETRIEVAL_UNAVAILABLE, 로그 "snapshot publication binding unavailable"). 나머지 575 통과. 법률 검토는 받지 않은 학생 프로젝트 초안.
## 2026-11-02 · ricky00-dev (Claude Code) · ci
- 한 것: GitHub Actions CI 추가 (`.github/workflows/ci.yml`). develop·main으로 가는 PR과 develop 푸시마다 바뀐 폴더만 검사: api `./gradlew test`(Testcontainers), web `lint`·`build`, ai-worker `uv run pytest`. develop 푸시 때는 운영 이미지 3개 빌드도 확인. 배포 점검: 최신 develop(RAG 머지 후)으로 운영 이미지 3개 로컬 빌드 성공, 워커는 메모리 512MB 제한에서 서버 import 정상.
- 진행 중: 없음.
- 다음: 첫 수동 배포 성공 뒤 CD(develop/main 머지 → EC2 자동 반영) 추가. EC2 주소·SSH 키를 GitHub Secrets에 등록해야 함 (ricky00-dev).
- 막힘·결정 필요: develop 브랜치 보호 규칙에서 CI 통과를 머지 필수 조건으로 걸지는 레포 설정에서 결정 (ricky00-dev).

## 2026-11-01 · ricky00-dev (Claude Code) · api, web
- 한 것: 학습 부가 기능 3개 (feat/learning-extras).
  1. 내 근거 채점: 판정 때 고른 근거를 그 근거를 인용한 쪽(매수 측·매도 측) 방향으로 채점. 초과수익 +2%p 초과면 매수 측 근거, −2%p 미만이면 매도 측 근거가 맞음, 그 사이는 FLAT. `GET /api/me/judgments/{id}`에 `pickResults`·`pickHorizon`, `/api/me/stats`의 `evidenceHabit`에 `right`·`graded` 추가. 채점 화면에 근거별 결과와 "판정은 빗나갔지만 근거는 맞았어요" 같은 한 줄 정리, 내 판정 탭 습관 리포트에 분류별 맞은 방향 횟수. DB 변경 없음 (debate_events의 statement_accepted에서 계산).
  2. 퀴즈 랭킹: `GET /api/quiz/ranking?scope=today|all` (맞힌 수 → 덜 풀고 맞힌 사람 → 먼저 도달 순, 공동 순위, 상위 20 + 내 순위), `PUT /api/me/nickname` (한글·영문·숫자 2~10자, 최소 욕설·사칭 차단). 웹 `/quiz/ranking` (오늘/전체, 30초마다 갱신, 닉네임 정하기). 퀴즈 홈·한 판 결과·마이 탭에서 진입.
  3. 오늘의 용어: 홈에 한국 시간 날짜로 고른 용어 카드 (프론트만).
- 진행 중: 없음.
- 다음: 전시 때 랭킹 화면을 대기 화면(큰 화면)으로 띄울지 결정. 욕설 목록은 최소한이라 운영 중 보강.
- 막힘·결정 필요: 없음. API 전체 테스트 41개 통과, 웹 tsc·lint 통과, 브라우저(390px)로 세 화면 확인. 근거 채점은 같은 근거를 양쪽이 다 인용하면 이긴 쪽 기준으로 RIGHT 처리 (화면에 안내 문구 있음).
## 2026-11-02 · Codex · ai-worker, api, web, docs
- 한 것: 사용자 요청으로 PR #28(e1f7a87) 검토. 저장/이관·불변 감사·검색 시점/스냅샷 연결·예산/작업 lease·인증/응답 DTO·판정 봉인·웹 조회 경계를 확인했으며 검토 범위에서 병합 차단 결함을 찾지 못함. 원래 로컬 변경4개는 chore/local-backup-before-pr28-20261102의 9ffe962에 보존, 고유 작업 로그12개가 PR에 포함됨을 대조. 사용자 조건부 병합 지시에 따라 squash 병합과 원래 폴더 develop 동기화 진행.
- 진행 중: 코드 검토/검증 완료. RAG 기본 비활성 및 운영 준비 미완료 상태 유지; 이 검토를 사람 검수 corpus 품질 승인·배포 승인으로 해석하지 않음.
- 다음: 운영 활성화 전 사람 검수 corpus/독립 평가셋, Docker/실배포·부하 검증. 원래 폴더는 최신 origin/develop으로 fast-forward하고 환경 파일 해시·작업 트리 상태 확인.
- 막힘·결정 필요: 별도 새 로컬 PostgreSQL16+pgvector 클러스터에서 전체 Python648 passed/외부 Spring5 skipped(129.27초). 검사 후 전용 DB 서버 종료, 기존 DB/실험 자료 불변. 동일 제품 head에서 직전 Java15개·웹build/lint 통과 결과 유지. 전체 Spring DB/브라우저·Docker·외부 모델/S3는 이번 재실행하지 않음. GitHub 자동CI/타인 리뷰 없음. 사용자 직접 병합 요청에 따른 검토이며 별도 팀원의 계약 승인으로 기록하지 않음. 원래 ignored 환경파일 해시 사전 기록, 백업 브랜치는 삭제하지 않음.


## 2026-11-02 · Codex · ai-worker, api, web, deploy, docs
- 한 것: 사용자 요청으로 feat/rag-week-one의 기존 변경을 계약·워커 저장/검색·Spring/웹 연동·평가/운영 문서의 4개 커밋으로 정리. 원래 체크아웃의 고유 작업 로그12개와 이전 RAG 우선순위를 통합·이력 보존하고 최신 RAG 문서를 사용. develop 기존47커밋은 재작성하지 않으며 새 브랜치 푸시와 develop 대상 초안 PR 준비.
- 진행 중: 구현·자료 보존 완료, 계약 공동 검토와 운영 품질 승인은 미완료. 기본 비활성 유지.
- 다음: 초안 PR에서 v0.8 계약 및 저장/검색 경계 공동 검토, 사람 검수 corpus·독립 평가셋 확보와 실제 배포 환경 검증 후 병합 판단.
- 막힘·결정 필요: 이번 최종 Python577 passed/76 skipped(72.25초; PostgreSQL/pgvector·외부 Spring 환경 미설정), Java RAG8+HTTP2+채점5 총15통과, 웹build/lint 통과. Python 최초는 패키지 소스 경로 누락으로 수집 실패 후 PYTHONPATH=src 지정해 통과. Java 최초 Mockito inline attachment 실패 후 영문 java.io.tmpdir로 재실행 통과(제품 코드 변경 없음). PostgreSQL 포함647개·브라우저·복원은 이전 기록이며 이번 재실행 아님. 변경 JSON33개 파싱 및 비밀 패턴 점검; 탐지1개는 테스트용 private-secret 가짜 DSN. 실제 모델/시장/S3/배포 호출 없음. 원래 체크아웃 파일은 보존.


## 2026-11-02 · Codex · api, web, ai-worker, docs
- 한 것: 현재 프로젝트 분석. origin fetch 후 최신 develop 2cca67f, 현재 체크아웃 83247f2(47커밋 뒤), feat/rag-week-one 미커밋 확장을 구분. 핵심 판정 봉인·SSE·단일 비교·RAG 통합 및 별도 PostgreSQL/pgvector·문서/Fact 조회·snapshot-generation 고정·로컬 복구 검증 기록 확인. 열린 PR #26 확인.
- 진행 중: 분석 완료. 기능 코드·브랜치·다른 worktree 변경 없이 기존 문서 변경 보존.
- 다음: 최신 통합본 기준 작업 상태 정리, rag-week-one 변경의 계약 공동 검토·단계별 통합, 사람 검수 corpus/독립 평가셋 확보, 실제 배포 환경과 모델 반복 완료율·비용 검증. 최신 일정은 예비11/4·엔진고정11/10·정식11/11·코드프리즈11/16.
- 막힘·결정 필요: 이번 직접 검증은 현재 체크아웃 Python 91 passed/외부 Spring 2 skipped 및 웹 build/lint 통과. 최신 통합본의 476개와 후속 worktree의 647개 통과·브라우저/복원 검증은 기존 기록이며 재실행하지 않음. 실제 모델/공급자/배포·전체 Spring 검증 없음. session-brief.sh CRLF 오류로 실패하여 git/문서/gh 직접 조회로 대체. 사람 검수 자료 부재·Docker/운영환경 미검증은 후속 작업의 readiness 감사 기록 기준.

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

---

## 2026-11-01 · ricky00-dev (Claude Code) · api, web
- 한 것: 학습 부가 기능 3개 (feat/learning-extras).
  1. 내 근거 채점: 판정 때 고른 근거를 그 근거를 인용한 쪽(매수 측·매도 측) 방향으로 채점. 초과수익 +2%p 초과면 매수 측 근거, −2%p 미만이면 매도 측 근거가 맞음, 그 사이는 FLAT. `GET /api/me/judgments/{id}`에 `pickResults`·`pickHorizon`, `/api/me/stats`의 `evidenceHabit`에 `right`·`graded` 추가. 채점 화면에 근거별 결과와 "판정은 빗나갔지만 근거는 맞았어요" 같은 한 줄 정리, 내 판정 탭 습관 리포트에 분류별 맞은 방향 횟수. DB 변경 없음 (debate_events의 statement_accepted에서 계산).
  2. 퀴즈 랭킹: `GET /api/quiz/ranking?scope=today|all` (맞힌 수 → 덜 풀고 맞힌 사람 → 먼저 도달 순, 공동 순위, 상위 20 + 내 순위), `PUT /api/me/nickname` (한글·영문·숫자 2~10자, 최소 욕설·사칭 차단). 웹 `/quiz/ranking` (오늘/전체, 30초마다 갱신, 닉네임 정하기). 퀴즈 홈·한 판 결과·마이 탭에서 진입.
  3. 오늘의 용어: 홈에 한국 시간 날짜로 고른 용어 카드 (프론트만).
- 진행 중: 없음.
- 다음: 전시 때 랭킹 화면을 대기 화면(큰 화면)으로 띄울지 결정. 욕설 목록은 최소한이라 운영 중 보강.
- 막힘·결정 필요: 없음. API 전체 테스트 41개 통과, 웹 tsc·lint 통과, 브라우저(390px)로 세 화면 확인. 근거 채점은 같은 근거를 양쪽이 다 인용하면 이긴 쪽 기준으로 RIGHT 처리 (화면에 안내 문구 있음).

## 2026-11-01 · Codex · api, ai-worker, web, docs
- 한 것: PR #23 비용/복구 수정 d8a5c27과 #24 snapshot 수정 2e389e3을 통합한 9867a14에서 최종 Python476 통과/외부5 생략, 별도 실제 Spring/PostgreSQL/HTTP5 통과, Java 관련9+DB복구7 통과, 웹 build/lint 성공. 초기 import 경로 오류와 fixture 오류 수정·재실행을 상세 보고서에 기록.
- 진행 중: 사용자 요청에 따른 #23→#24→#25 develop 병합. #23 병합 9e4926a 및 #24 병합 2ef53e2 완료. #24와 #25의 base 통합 충돌은 WORKLOG만 발생해 모든 기록을 보존. #25 최종 원격 반영 중. 제품 코드는 검증 revision 유지, 검사 실행기에서 DB복구7개 실행을 의무화.
- 다음: PR head 고정 병합 후 원격 상태와 제품 tree 동일성 확인. 상세 docs/evaluations/pr-23-24-25-merge-validation.md.
- 막힘·결정 필요: 재현된 미해결 결함/사용자 판단 대기 없음. Docker Java 전체·실모델 성공률·독립 사람 평가·실청구/실시장 검증은 미완료. 운영 single/RAG 기본 비활성, 배포/추가 유료 호출 없음. 이전 V6 소실 비용 복구 불가.


## 2026-11-01 · Codex · api, ai-worker, web, docs
- 한 것: 사용자 요청으로 이전 PR #23(d431ce2)/#24(51cf34f) 검토 및 통합 PR #25 초안 생성. 양 PR을 로컬 통합해 WORKLOG 양쪽 기록과 executor 실패 처리·single 인자를 보존. #23 시도 비용 덮어쓰기/RUNNING 복구/SSE 전송 오류 결함, #24 같은 ID의 snapshot cutoff 불일치를 확인하여 병합 보류 후 수정 진행.
- 진행 중: #23 전용 수정 세션은 시도 원장·재시작 복구·3일 성적표 토글 수정 중. 통합 워커 canonical snapshot 보완 후 전체476 passed/외부5 skipped. 웹 build/lint 통과. 새 Spring single 연결 검사 첫 실행4 passed/1 failed는 fixture의 single 경로 누락으로 확인, 테스트 대역 라우팅과 실클라이언트 생성 차단 추가 후 재검증 중.
- 다음: 각 PR 수정 커밋 반영, 전체/연동 검사, 검증된 PR head 고정 후 develop 병합. 운영 single/RAG 기본 비활성 유지.
- 막힘·결정 필요: 첫 fixture single 오류는 TypeError이며 모델 응답/토큰 기록 없음; 이를 실제 Claude 성공/청구 검증으로 해석하지 않음. 실모델·지출 상한·사람 검수는 별도. Docker 미설치로 Java Testcontainers 전체 검사는 임시 PostgreSQL 대안과 구분하여 기록. 원본 작업 폴더 보존.

## 2026-11-01 · Codex · ai-worker, docs
- 한 것: 사용자 푸시 요청에 따라 통합 HEAD d7f315c와 독립 검토 수정 71af77b의 사용량 미확정 보존·MKT 표시 검사, 데이터/복구 변경 및 기존 평가 증거 검토. origin fetch 후 워커 전체 460 passed/외부 4 skipped(44.97초), 별도 Spring/PostgreSQL fixture 4 passed(15.12초) 재확인. Java 관련 테스트·bootJar는 Gradle UP-TO-DATE 성공. 공백 검사 통과, 추적 .env/원본 data 없음, 임시 프로세스 잔존 없음.
- 진행 중: 검증 기록 커밋 후 fix/worker-integrated-validation 원격 푸시. 제품 소스 추가 변경 없음.
- 다음: 원격 HEAD 일치 확인 후 실제 모델 접근·호출 예산·독립 사람 검수 준비. develop/main 병합·배포는 별도.
- 막힘·결정 필요: 오프라인 구현/통합 검증 완료로 평가하며 실제 운영 완료는 아님. 실제 유료/시장 공급자 호출, SDK 내부 전송 재시도 청구 대조, 지출 상한, 기업행사 정책은 미검증. 실행 증거 ai-worker/data/spring-integration/run-eaf78afb99ad42e7bee3dd0700a68433(ignored). 원본 작업 폴더 변경 보존.

## 2026-11-01 · Codex 독립 검토 수정 세션 · ai-worker, docs
- 한 것: 독립 검토 원본을 읽기 전용 확인 후 P1 내부 재시도 성공 시 미확정 사용량 유실과 P2 MKT 내부 ID 표시 누락을 회귀로 재현(수정 전5 실패/정상 대조2 통과). llm→audit→LiveRunner/Service에 요청별 영속 관측·지속 미확정 상태를 연결하고 정상 완전 usage 공개 유지. presentation 기존 차단 prefix에 MKT 추가. 수정 코드71af77bd5c0ae57ea384325496199f3ad1e6cf97.
- 진행 중: 두 재현 결함 수정 완료. 최초 영향46 통과 후 요청 기록 저장 실패/호출 전 영속화 회귀 보강, 전체460 통과/실패0/외부4 생략(45.80초). 실제 Spring/PostgreSQL4 통과/실패0/생략0(16.04초), 생성·재시작 프로세스/포트 정리 확인. 이전 통과 검사가 놓친 성공 재시도 분기와 새 MKT prefix 통합 경계를 docs/evaluations/worker-integrated-review-fixes.md에 기록.
- 다음: 총괄이 수정 revision과 재현/대조군을 확인. 실제 모델 검증은 키·접근·총비용 상한 확보 후 진행하고 사람 평가셋·청구 대조는 별도 수행.
- 막힘·결정 필요: 유료/실제 공급자 호출0, SDK stream 시도 관측이 SDK 내부 전송 재시도·실제 청구액 전체의 원장은 아님. 공통 예산 예약/단가/공개 계약 정책 및 기본 RAG 비활성 유지. 검토 세션·기존 데이터/.env 변경, push·배포·원격 병합 없음. 사용자 판단 대기로 중지한 작업 없음.

## 2026-10-31 · Codex 통합 검증 세션 · ai-worker, docs
- 한 것: HTTP 변경을 4b27d93으로 보존, fix/worker-integrated-validation에서 9176afc를 70021d1로 로컬 통합. worker-quality/worker-data-consistency 완료 파일 12개와 WORKLOG 항목을 원본 수정 없이 반영하고 test_server.py 양쪽 보존. 최종 코드 27f61611fe7dec317e61b9ecb2104917b5eab784.
- 한 것: 실제 Spring/PostgreSQL에서 사용량 미확정 실패·워커 os._exit 후 재시작/SSE 재구독 검증 추가. 비용/토큰 NULL 및 $0.15 추정치, 실패 이벤트1개, 원본 감사·부분 사용량 보존 확인. psql 미설치로 새 E2E2개가 처음 실패했으나 JDBC 조회 보조 도구로 해결. 기존 4조건14후보 해시 연결 재검증, 전부 미검수·품질비율 null 유지.
- 진행 중: 요청된 통합·검증 완료. 전체 Python451 통과/실패0/외부2 생략(45.91초), 마지막 fixture 변경 후 영향 범위115 통과/실패0/외부2 생략(19.35초). 실제 Spring4 통과/실패0/생략0(13.61초), Java 관련7개 및 bootJar는 코드 변화 없어 Gradle 성공 캐시 재사용. 생성 서버와 재시작 프로세스 종료·포트 해제 확인. 상세 출처·증거·한계는 docs/evaluations/worker-integrated-validation.md.
- 다음: 총괄이 로컬 통합 브랜치/보고서를 검토. 실제 키·모델 접근·별도 총비용 상한/예약 준비 후 Claude HTTP 검증, 독립 사람 라벨 후 품질 평가. HTTP 단일 모드/v0.6은 양측 승인과 별도 구현 범위 결정 필요, 이번 통합 범위에 포함하지 않음.
- 막힘·결정 필요: 재현된 미해결 회귀 없음. 실제 공급자/유료 호출0, $0.15 추정치는 결제 상한 아님. 사람 검수·실시장 관측/기업행사 정책·성숙한 성과는 미확인. 사용자 판단 대기로 중단한 작업 없음; 외부 선행 조건 없는 임의 재개 금지. 원본/타 세션/환경파일 보존, RAG 기본 비활성, 공개 계약/config/budget/Spring 제품 코드·원격 push/develop/main 병합/배포/스케줄 활성화 없음.

## 2026-10-31 · Codex 데이터 정합성 세션 · ai-worker, docs
- 한 것: 5d2a8e5에서 별도 worker-data-consistency worktree/브랜치 fix/worker-data-consistency 생성. CLI/HTTP 확정 종가 cutoff 통일, timezone 없는 시각 거부, 범위 밖 시세·미래 뉴스/공시 필터, 주식수 공시일 보존. KRX 캐시 읽기/저장 전 가격·지수 형식 검증, 장중 캐시 재조회, 빈 응답 TTL 60초. 동일 날짜의 과거 3·7·21종목 거래일 코스피/종목 수익률과 초과수익률 Fact 추가(누락 날짜 비보간).
- 진행 중: 담당 구현·오프라인 검증 완료, 전용 폴더 미커밋 변경으로 통합 대기. 최초 결함 6개 재현 후 수정. 최종 전체 Python 402 passed·외부 Spring 2 skipped(45.88초), diff 공백 검사 통과. 기존 KRX 캐시 287개 읽기 전용 검사(비어 있지 않은 정상265/빈22/실패0). 상세: docs/evaluations/worker-data-consistency-session.md.
- 다음: KRX 공급자 파일 → snapshot.py와 server/market.py 함께 → 신규 test_data_consistency.py 및 test_server.py fixture 보완 → 보고서/이 로그 항목 순으로 통합. 통합 후 전체 회귀 및 프롬프트/검토기의 신규 과거 비교 Fact 해석 확인.
- 막힘·결정 필요: 실제 공급자/유료 모델 호출0, 성숙한 3·7거래일 성과·공급자별 observed_at·기업행사 보정·특별 거래시간/발표지연 미검증. 지수 cold 조회 지연 추가 가능. service/store의 시각·캐시 해시 감사 및 재사용 정책 보완은 범위 밖 제안으로 기록. 공통 schemas/config·공개 계약·프롬프트/검증기 변경 없음. RAG 기본 비활성, 배포/스케줄 활성화/push/merge 없음. 다른 작업 폴더·원본 데이터·환경 파일 보존.

## 2026-10-31 · Codex 품질 평가 세션 · ai-worker, docs
- 한 것: 5d2a8e5 기준 격리 worktree worker-quality / fix/worker-quality-evaluation에서 기존 미커밋 diagnostics를 읽고 후속 quality_evaluation 구현. queue 원본/후보/자동 결과 및 snapshot 연결 검증, 미검수·제안·사람 검수 분리, 사람 확인·분모 있는 집계와 원문 없는 결과 생성. 기존 4조건 14후보 읽기 전용 적용 모두 미검수·오류율 null 유지.
- 한 것: 기간 검사 공백 오탐 수정과 17/7.7거래일 누락 차단, 합성 기간 회귀9개 및 의미 검수 제안6개 작성. 전체 Python 414 passed/외부2 skipped(43.37초), 공백 검사 통과. 유료 호출0, 기존 원본 데이터/.env 및 타 세션 수정 없음.
- 진행 중: 사람 검수와 실제 Claude 품질 측정 미완료. 저장 후보14개는 이번 기간 수정으로 판정 변화 없음. 의미 검토 과잉반려는 확정 라벨 없이 규칙을 완화하지 않음. 구현 변경은 이 브랜치에 미커밋 상태로 보존.
- 다음: worker-integration의 기존 diagnostics 먼저 통합 → 새 모듈/fixture/test 및 semantic 변경 반영 → 독립 사람 검수 → 후속 Claude HTTP 실험. 변경 파일/실험표/통합 순서는 docs/evaluations/worker-quality-session.md 참고.
- 막힘·결정 필요: 사용자가 토론자 Haiku·중재자 Sonnet 선택 완료. 정확한 계정 모델 ID/키 접근·새 총비용 상한 확인 전 유료 호출 보류. HTTP audit 변환은 범위 밖 제안. RAG 기본 비활성, 계약/배포/스케줄/push/merge 변경 없음. session-brief CRLF 실패 후 로그 직접 확인.

## 2026-10-31 · Codex HTTP 안정화 세션 · ai-worker, docs
- 한 것: 5d2a8e5에서 전용 worker-http-stability worktree 생성. executor 제출 실패의 영구 running/용량 누수, SSE Last-Event-ID 정수 범위 오류, 상세 조회 종료 상태 경쟁을 재현·수정. 인증 실패·멱등성·실패 SSE·실제 프로세스 강제 종료 회귀 보강.
- 한 것: 사용량 조회 실패/미완료·실패한 모델 호출의 부분 사용량을 확정 비용으로 보내지 않도록 usage 생략. 감사 부분 사용량/usage_complete=false 보존. 재시작은 원본 manifest를 수정하지 않고 SQLite recoveries에 부분 사용량·미완료 호출 ID·미확정 상태를 보존하며 실패 이벤트 1회 기록. 상세·통합 순서는 docs/evaluations/worker-http-stability-session.md.
- 진행 중: 구현 완료, 이 전용 worktree에 미커밋 변경으로 보존. 전체 Python399 passed/외부2 skipped(49.42초) 후 강제 종료·부분 실패 사용량 회귀 보강, 최종 영향 범위65 passed(19.69초). Java 단위7개·bootJar 및 실제 임시 PostgreSQL/Spring/HTTP fixture2 passed(5.40초), 서버 잔여 프로세스 없음. git diff 공백 검사 통과.
- 다음: 총괄이 server app/service/store와 HTTP/audit 테스트를 함께 통합하고 공통 config/budget/LLM 변경 후 회귀·Spring fixture 재실행. 실제 유료 검증은 키·모델 접근·총비용 상한 확보 후 진행.
- 막힘·결정 필요: 유료/외부 데이터 호출0, 공개 계약·기본 RAG 비활성·타 소유 파일 유지. Spring 성공 fixture E2E는 통과했지만 재시작 미확정 비용의 PostgreSQL 정산 E2E는 미실행. 기존 Spring 추정치($0.15)는 실제 지출 상한이 아니므로 공통 예산 예약/미확정분 대조는 별도 담당 후속. session-brief는 기존 CRLF 오류로 실패해 문서/Git 직접 확인. 원본·타 세션·.env·기존 데이터 수정 및 커밋/push/merge/배포/스케줄 활성화 없음.
## 2026-11-01 · Codex PR #24 스냅샷 정합성 수정 · ai-worker, docs
- 한 것: 51cf34f에서 전용 worker-canonical-snapshot worktree와 fix/worker-canonical-snapshot 브랜치 생성. Service의 snapshot 단계에서 저장 후 DB의 canonical 객체를 다시 읽고 audit/RAG/runner에 동일 객체 전달. ID 해시·정책·공개 계약 변경 없음.
- 한 것: 감독 폴더의 회귀를 읽기 전용 참고해 기존 실패 스냅샷 저장 → 같은 ID/새 created_at으로 토론 재시도 → single 실행을 검증. 수정 전1 실패로 재현, 수정 후 두 runner와 두 audit의 전체 snapshot이 옛 canonical 객체와 같음을 확인. 관련 single/HTTP/audit/RAG 테스트64 passed(15.76초), diff 공백 검사 통과.
- 진행 중: 최소 수정·회귀·본 기록의 로컬 커밋 완료 후 감독에게 전달. 다른 worktree와 원본 데이터/환경 파일 보존.
- 다음: 감독이 #24에 커밋 반영 및 push/merge 수행. 통합 브랜치의 사용량·복구·MKT 보완을 보존해 통합 검증.
- 막힘·결정 필요: 실제 공급자·유료 호출 및 Spring 외부 통합은 미실행. 추가 정책 판단이나 사용자 판단 대기 없음. 이 세션에서는 push/merge/배포하지 않음.

## 2026-10-31 · Codex · ai-worker, docs
- 한 것: 사용자 요청으로 #23 계약 v0.6을 그대로 반영하고 HTTP single 구현. mode/snapshot_id 검증, 저장 스냅샷 실행, 모드별 재사용, SQLite 이관, 중재자와 같은 모델의 중립 판정, scores/stats=null·SSE·감사·RAG 경로 추가. README 아키텍처와 PNG 갱신.
- 한 것: 전체 Python407 passed/외부 Spring2 skipped(40.13초). 병렬 중복 방지·구버전 호환·실패 재시도·스냅샷 분리·독립 의미 검토 확인. 실제 Claude 스키마 maxItems 거절을 발견해 전송용 변환과 회귀 테스트 추가.
- 한 것: 허가받은 실제 Sonnet 호출로 localhost HTTP 실험. 스키마 거절3요청 이후 2실험에서 실제 응답12회(입력135,098/출력7,668토큰), 모두 최종 판정 검증 반려. 실패 SSE·usage·멱등성 확인; 원본 자료/키는 제외하고 ai-worker/docs/single-http-validation.md에 결과 기록.
- 진행 중: feat/worker-operational-readiness 변경분을 커밋·푸시해 기존 PR #24에 반영. Spring/web 코드는 수정하지 않음.
- 다음: 별도 평가 스냅샷에서 생성 성공률·반려 사유 점검, 실제 debate_completed 확인 및 #23 Spring 단일 결과 저장 연결 테스트 후 운영 스위치 활성화 검토.
- 막힘·결정 필요: 실제 완료 판정0건이며 이를 운영 성공으로 해석하면 안 됨. Spring #23 실행·실제 토론 짝·최신 시세 재수집·청구 금액 확인은 미실행. 단일 모드 운영 스위치는 활성화하지 않음. 기존 WORKLOG 기록 보존, session-brief CRLF 실패는 기존 git/로그 직접 조회로 대체.

## 2026-10-31 · Codex · docs
- 한 것: PR #23(d431ce2, 단일 모드 계약 v0.6/Spring/AI 성적표)과 #24(9176afc, 워커 RAG/운영 준비)를 비교. git merge-tree 모의 병합에서 충돌 파일은 WORKLOG만 확인; 실제 병합/코드 변경 없음.
- 한 것: 현재 StartDebate가 mode/snapshot_id를 무시하고 Store가 종목·날짜만으로 기존 토론을 재사용하는 동작을 임시 SQLite로 재현. #23 기본 single-enabled=false 확인.
- 진행 중: 계약 검토만 수행. HTTP 단일 모드는 여전히 미구현이며 benchmark 단일 분석가와 별개.
- 다음: 양측 계약 승인, mode/snapshot_id 검증 및 재사용 분리·동일 스냅샷 단일 실행·이벤트/응답 구현과 연결 검증 후 단일 스위치 활성화. 양 PR 병합 시 WORKLOG 양쪽 기록 보존.
- 막힘·결정 필요: 현 상태에서 단일 스위치를 켜면 토론 판정이 단일 결과로 저장될 위험. 유료/외부 API 호출 없음, 전체 런타임 테스트 미실행. PR 승인·댓글·병합·푸시하지 않음.

## 2026-10-31 · Codex · docs
- 한 것: 미커밋 진단 도구·아키텍처 문서를 0f9f295로 커밋하고 브랜치 푸시 완료. develop 대상 PR #24 생성: https://github.com/ricky00-dev/bull-and-bear/pull/24. 최신 develop 7e48f7c 일정 변경을 통합하고 WORKLOG 충돌은 양쪽 기록을 모두 보존해 해결.
- 진행 중: PR 리뷰 대기. PR에는 기존 5d2a8e5의 RAG·Claude 모델 정책·preflight 통합도 포함.
- 다음: 리뷰 반영 후 develop 병합 검토. 실제 Claude 호출 보류와 RAG 기본 비활성 유지.
- 막힘·결정 필요: 최종 코드 전체 Python392 passed/외부2 skipped. 이후 병합은 문서만 변경되어 테스트 재실행하지 않음. 키/.env/로컬 원본 데이터 제외, 유료 호출 없음. PR 생성은 완료했으며 develop 자체 병합은 하지 않음.

## 2026-11-01 · Codex PR #23 복구 수정 · api, web, docs
- 한 것: d431ce2에서 별도 single-mode-recovery worktree/fix 브랜치 생성. V7 시도별 비용 원장과 기존 V6 최신 행 이관, 날짜별 확정/미확정 비용 합산, 동일 request_id/worker_id 재시작 복구, SSE 전송 오류와 실제 terminal 실패 분리, 원장/결과 원자적 저장 구현. 7일 표본0에서도 3일 토글 표시.
- 한 것: 독립 실제 PostgreSQL/Flyway 회귀7개 + 기존 HTTP/직렬화4개 = 11 통과/실패0/생략0. bootJar·웹 tsc/Vite build·lint 통과. 임시 PostgreSQL 종료와 포트 해제 확인. 제품 파일 외 test fixture 초기 컴파일/Mockito agent 환경 문제는 표준 Java fixture로 해결, 검증 조건 유지.
- 진행 중: 로컬 fix 브랜치 커밋 후 감독 통합 대기. 보고서 docs/evaluations/single-mode-recovery.md. 기존 품질 worktree 및 감독 통합 폴더 보존.
- 다음: 감독이 PR #23에 로컬 수정 커밋 반영 후 최종 검증·push/merge. 실제 worker single HTTP 지원·양측 v0.6 승인 전 SINGLE_ENABLED=false 유지.
- 막힘·결정 필요: V6에서 이미 사라진 과거 시도 비용은 복구 불가, 현재 저장된 증거만 이관. 전체 Docker API 통합/실제 single HTTP/프로세스 강제 종료 E2E/브라우저 클릭 미실행. 재시작은 실제 DB 유지·runner 인스턴스 교체로 검증. 새 예산 정책·계약 변경·유료 호출·push/merge 없음. 사용자 판단 대기 중단 항목 없음.

## 2026-10-31 · Claude Code · api, web, docs(계약)
- 한 것 (feat/single-mode-report):
  - **계약 v0.6**: `POST /debates`에 선택 필드 `mode`(`debate`|`single`)·`snapshot_id`. 단일 모드 = 실험 조건 B (중재자와 같은 모델이 같은 스냅샷으로 바로 판정, `scores`·`stats`는 null)
  - Spring: `SingleVerdictRunner`가 정식 운용(`bullbear.experiment.start`, 기본 11/11) 전향 운용 토론이 끝나면 단일 판정을 한 번 받아 `single_verdicts`에 저장 (실패 시 3회까지, 전향 운용 하루 비용 상한에 합산). 스위치 `BULLBEAR_SINGLE_ENABLED`(기본 false)
  - `debate_outcomes`에 3거래일 결과도 기록 (PK를 (debate_id, horizon_days)로). 퀴즈는 7거래일만 사용
  - `GET /api/report?scope=official|all`: 7·3거래일 적중률 (토론 AI, 단일 AI, 항상 보류/매수/매도), 판정 분포, 사람 vs AI
  - 웹 `/report` AI 성적표 (마이 → AI 성적표). 정식/예비 포함 토글, 7일/3일 토글, 표본 한계 문구
  - 가짜 워커 단일 모드 (종목마다 다른 판정)
- 확인: API 테스트 28개 통과 (`ExperimentReportTest`, `StartDebateRequestTest` 추가), 웹 tsc·lint, 브라우저에서 성적표 확인 (로컬 DB 토론을 SCHEDULED로 바꾸고 시작일을 앞당겨 확인)
- 막힘·결정 필요 (**jangwonii**): 계약 v0.6 리뷰·승인 후 머지. 워커 단일 모드 구현 → 정식 운용(11/11) 전에 `SINGLE_ENABLED=true`

## 2026-10-31 · Claude Code · docs
- 한 것: 일정 변경 반영 (ROADMAP, experiment.md). 예비 운용 11/4(현재 엔진, 퀴즈·시연용, 실험 집계 제외) → 정식 운용 11/11(엔진 고정, 실험 집계). 전시 전 7거래일 채점 약 50건, 발표 메시지 결정 11/18 → 11/21. 모델 Haiku+Sonnet 반영, 비용 추정 갱신
- 막힘·결정 필요 (**jangwonii**): 11/10까지 엔진 고정, 단일 모드(`mode: "single"`) 구현. KRX·DART·네이버 키 공유 (로컬 연동 테스트용)

## 2026-10-31 · Codex · ai-worker, docs
- 한 것: 사용자 요청으로 미커밋 9개 파일(오프라인 진단 CLI/테스트, 평가 기록, README Mermaid/PNG 3개, 작업 로그)을 검토하고 커밋 준비. 앞선 RAG·Claude 제한 통합 커밋 5d2a8e5와 함께 feat/worker-operational-readiness를 develop 대상 PR로 게시할 범위 정리.
- 진행 중: 커밋·푸시·PR 등록. 최신 origin/develop 7e48f7c 확인; 추가 변경은 일정 문서이며 워커 공개 계약/Spring·웹 코드는 이번 PR에서 변경하지 않음.
- 다음: PR 리뷰 반영, 미라벨 검수와 독립 평가셋 준비. 실제 Claude 호출은 사용자 보류 유지.
- 막힘·결정 필요: 최종 전체 워커 테스트392 passed/외부 Spring2 skipped(42.52초). 과거 실제 Spring fixture2개·Java7개/bootJar 검증은 이번 재실행하지 않음. Mermaid 실제 렌더링 완료, diff 공백 검사 통과. 키/.env/로컬 실험 원본 제외, 유료 호출0. session-brief 기존 CRLF 실패로 git/로그 직접 확인.

## 2026-10-31 · Codex · ai-worker, docs
- 한 것: README Mermaid 3개를 실제 mermaid-cli/Edge로 PNG 렌더링. ai-worker/docs/images에 전체 구성·토론 처리·RAG 이미지 저장하고 README에 모바일/비지원 뷰어용 링크 추가. 한글 표시와 이미지 경계 확인.
- 진행 중: 없음. 기존 미커밋 변경 보존.
- 다음: Mermaid 수정 시 PNG도 재생성. 실제 Claude 호출 보류 유지.
- 막힘·결정 필요: Mermaid 실제 파싱·PNG 생성 성공. 문서/이미지 변경으로 런타임 테스트 미실행, 유료 API 호출 없음. 렌더러는 npm 임시 캐시에서 실행했고 프로젝트 의존성 변경 없음.

## 2026-10-31 · Codex · ai-worker, docs
- 한 것: ai-worker/README.md에 현재 코드 기준 Mermaid 아키텍처 3개(전체 구성·책임 경계, 토론 처리·검증/재시도/실패, RAG 검색·배경 주입)와 모듈/저장소 대응표 추가. Spring 판정 봉인, 공개 Fact와 비공개 배경 구분, HTTP 이벤트와 감사 저장 분리, 기본 비활성 RAG 및 실험 예산/운영 비용 정책 차이 명시. 오래된 자동 모델 대체·워커 봉인 설명 교체.
- 진행 중: 없음. 기존 미커밋 진단 도구·평가 문서·작업 로그 변경 보존.
- 다음: README 다이어그램을 기준으로 워커 후속 구현·검수 진행. 실제 Claude 호출은 사용자 요청대로 보류 유지.
- 막힘·결정 필요: 문서만 수정. 코드 대조·코드 펜스/다이어그램 개수 확인·git diff --check 수행. Mermaid 실제 렌더링과 런타임 테스트는 미실행. session-brief는 기존 CRLF 오류로 실패해 git 상태/작업 로그 직접 확인. API 호출·키 조회 없음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: 사용자 요청에 따라 실제 Claude 호출 보류, 키·유료 호출 없이 benchmark 기록을 읽는 diagnostics CLI 추가. 오류/경고 분리, 단일 분석가 검증 지적 중복 집계 방지, 통과·반려 모두 미라벨 검수 목록 생성, 원본 해시/후보 해시/리뷰 위치 기록, 기존 결과 덮어쓰기 차단.
- 한 것: 기존 OpenAI comparison-2-v3 4조건에 적용해 후보14건(자동 통과2·반려12) 추출. 자동 추론 지적17건·기간 지적5건을 확인했으나 실제 오류/오탐으로 확정하지 않음. docs/evaluations/worker-offline-diagnostics.md에 절차·결과·한계 기록.
- 진행 중: 사람 검수 라벨과 독립 평가셋은 미완료. 이 목록은 기존 개발 파일럿 재시도 자료이며 Claude 성능 증거 아님.
- 다음: 원본 Fact/후보/검토 의견 대조 라벨 검수, 별도 스냅샷 평가셋 준비. Anthropic 키 설정·비용 상한 확정 뒤 사용자 보류 해제 시 실제 Claude HTTP 검증 재개.
- 막힘·결정 필요: 진단/benchmark 관련26개 테스트 통과(7.39초). 이번 전체 스위트·Spring 재실행은 하지 않음(운영 코드 변경 없음). API 호출0, 원본 실험·키·다른 worktree 수정 없음. session-brief는 기존 CRLF 오류로 실패해 상태/계획 문서 직접 확인. RAG 기본 비활성·운영 활성화 보류 유지.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: 최신 origin/develop 034d8da에서 feat/worker-operational-readiness 생성, RAG ad8cb26 및 별도 hardening의 검토된 실패 정책 통합. config 비밀값 보호/RAG 설정과 fixture 종료 정리 충돌 해결. 작업 순서·완료 기준·실측은 docs/evaluations/worker-operational-readiness.md에 기록.
- 한 것: 사용자 지시에 따라 Claude Haiku·Sonnet만 허용, 기본 토론자 Haiku/중재자 Sonnet, Opus 및 자동 모델 대체 차단. 예상 외 응답 계열은 사용량 보존 후 중단. CLI/HTTP/Claude 실험 역할 선택 통일. 네트워크·키 출력 없는 preflight 명령 추가.
- 진행 중: 실제 Claude HTTP 검증은 ANTHROPIC_API_KEY 누락으로 보류. 원본 .env와 타 작업 폴더 수정 없음. 사용자 모바일 환경으로 지금 키 설정 어려움.
- 다음: PC에서 Anthropic 키 설정 후 계정 모델 ID/접근 확인, 총비용 상한 확정 및 제한 가능한 실행 경로 준비 → 실제 HTTP 지연/완료율/사용량 검증 → 독립 오류 라벨 평가 → 소수 종목 전향 검증. RAG 기본 비활성 유지.
- 막힘·결정 필요: 전체 Python 385 passed/외부2 skipped 후 응답 계열 차단 추가분 영향 회귀 12 passed. 실제 로컬 Spring/PostgreSQL/HTTP 2 passed(모델/시장/시계 fixture), Java 단위7개·bootJar 통과, 임시 서버 종료 확인. 실제 외부 공급자/Claude 호출·배포 미실행, 유료 호출0. 개발 기본 WORKER_TOKEN은 운영 전 Spring과 함께 교체 필요. 키 입력 전용 모바일→로컬 경로는 현재 도구에서 확인 못 함. session-brief는 CRLF 오류로 실패해 git/로그 직접 확인. 원본 문서 변경 보존.

## 2026-10-30 · Claude Code · api, web
- 한 것: 마이 탭 열기 (계정·학습 허브). 계정 카드(게스트, 카카오 버튼은 준비 중), 퀴즈 누적 기록(`GET /api/quiz/stats`), 용어 사전 화면(`/glossary`, 검색), 서비스 소개 다시 보기. 적중률·근거 습관은 중복이라 "내 판정" 탭에 그대로 둠
- 다음: AI 성적표(실험 결과 화면) — 마이 탭 메뉴에 자리만 있음 (Claude Code)

## 2026-10-30 · Claude Code · api
- 한 것: 예산 단가표에 `claude-sonnet-5-5` 추가 (없으면 중재자 호출이 추정치로 잡혀 하루 상한이 부정확). 사용량 모를 때 추정치 $0.3 → $0.15 (토론자 Haiku + 중재자 Sonnet)

## 2026-10-30 · Claude Code · api, web
- 한 것:
  - 중재자 글의 `[E1]`·`[E2]`를 근거 칩으로 표시 (`VerdictText`, 판정 공개·퀴즈 정답 화면). `[E1]` = `decisive_evidence[0]` (worker-api.md v0.5 설명 보강). 번호 없는 예전 글은 그대로 보임
  - 퀴즈 답하기 전 가리기 강화: 종가·이동평균·52주 고저·시가총액 등 가격 수준 근거와 1억 이상 금액 근거의 값은 `null`, 본문 속 금액("242,000원", "146.7조 원")과 큰 숫자는 "○○"
  - 퀴즈 정답 응답에 `decisiveEvidence` 추가, 퀴즈 홈·결과에 "투자 권유 아님" 안내
- 다음: 전시 모드 (A/B/C 결정 대기)

## 2026-10-30 · Claude Code · deploy
- 한 것: 운영 compose가 `BULLBEAR_DEBATER_MODEL`·`BULLBEAR_MODERATOR_MODEL`을 워커에 넘기지 않아 둘 다 기본값(Opus)으로 돌던 문제 수정. 기본값 토론자 `claude-haiku-5-5`, 중재자 `claude-sonnet-5-5` (`deploy/.env.example`의 `DEBATER_MODEL`·`MODERATOR_MODEL`로 바꿀 수 있음)
- 막힘·결정 필요 (**jangwonii**): 로컬 `ai-worker/.env`에도 같은 두 줄을 넣어야 Opus로 돌지 않는다. 토론 1건의 모델별 토큰 사용량을 재서 공유 (API 크레딧 월 $200 안에서 개발·백테스트·운용을 모두 해결해야 함)

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: 워커 안정화 코드·회귀 테스트·문서 16개 파일을 검토해 38a4516(fix: 워커 데이터 캐시와 장애 처리 및 초기 시세 조회 개선)으로 커밋하고 codex/fix-worker-data-reliability를 원격에 푸시. develop 대상 PR #17 생성: https://github.com/ricky00-dev/bull-and-bear/pull/17.
- 진행 중: PR 리뷰 대기. 구현 변경 없이 PR 등록 기록만 추가.
- 다음: 리뷰 반영 후 develop 병합 검토. 실제 Spring/PostgreSQL 통합 및 외부 공급자·모델 검증은 별도 진행.
- 막힘·결정 필요: 구현 검증은 앞선 전체 워커 테스트 158개 통과·외부 Spring 2개 건너뜀 기준이며 이번 커밋·PR 등록 과정에서는 코드 변경이나 테스트 재실행 없음. 최초 데이터 준비 시간 및 동기 일별 시세·지수/카탈로그 조회의 잔여 범위를 PR에 명시.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: codex/fix-worker-data-reliability에서 고우선 데이터 안정화 수정. DART 013 응답 비캐시 및 기존 013 캐시 무시, 손상 캐시 재조회, DART HTTP/JSON/회사 ZIP·XML 오류와 뉴스 HTTP/JSON/기사 형식 오류를 안전한 DataUnavailable로 정규화. 실제 공급자+MockTransport로 선택 자료 장애에도 시세 스냅샷·경고가 유지됨을 검증. 설정 객체 repr에서 비밀값 제외.
- 한 것: 종목 quote의 400일 수집을 제한된 백그라운드 작업으로 이동(스레드 2개·실행/대기 합계 32개). 동일 종목·cutoff 수집 공유, 준비 완료는 최대 1초 대기 후 503, 실패 후 재시도·TTL 만료 재조회·기준일 경계 분리·KRX 종료 중단 구현. 전체 시세·sparkline 60개·스냅샷 날짜/종가 일치 유지. 앱 소유 Market만 lifespan 종료 때 닫으며 주입 Market은 호출자가 정리. 기존 HTTP 계약 필드와 Spring 코드는 변경하지 않음.
- 진행 중: 없음. Python 전체 158개 통과, 외부 Spring 2개 건너뜀(40.60초), git diff 공백 검사 통과. 기존 cold 조회가 응답을 막는 회귀를 먼저 재현한 뒤 수정 후 통과 확인. README 실행 안내 갱신.
- 다음: 실제 Spring/PostgreSQL fixture 통합, 실제 Anthropic HTTP 경로의 지연·비용·성공률 측정. /prices/daily·/indices/daily의 동기 조회 대기, DART 검색 카탈로그의 동기 조회, 판단 시각·코스피 비교 입력·기업행사 보정은 후속 검토.
- 막힘·결정 필요: 실제 외부 데이터/유료 LLM 호출 및 Spring 전체 통합은 실행하지 않음. cold 수집 자체는 여전히 여러 분 걸릴 수 있으며, 준비 전 재시도가 필요하므로 시연 전 캐시 준비 권장. 커밋·푸시는 하지 않음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: develop 83247f2 기준 워커 엔진·FastAPI/SSE·Spring 계약 연동·운영 설정을 분석. 잠금 파일 버전으로 로컬 .venv 구성 후 Python 91개 통과, 외부 Spring 2개 건너뜀. OpenDART 자료 없음(013) 응답이 만료 없이 재사용되는 문제를 MockTransport로 재현(두 번 조회에도 외부 요청 1회, 두 번째도 None). 구현 코드는 변경하지 않음.
- 진행 중: 없음. FastAPI 엔드포인트·SQLite 영속 저장·멱등성·재연결은 구현되어 있으며 ROADMAP/DEPLOY의 일부 골격 단계 설명은 갱신 필요.
- 다음: 최초 KRX 캐시 준비/갱신과 202 이전 시세 조회 지연 개선, DART 미발표 응답 캐시 정책 및 선택 데이터 HTTP 오류 처리 보완. 이후 Spring/PostgreSQL fixture 통합과 실제 Anthropic HTTP 토론의 성공률·전체 지연·비용 측정. 지수 비교 입력·판단 시각 정합성·단일 에이전트 비교 모드도 별도 잔여 작업.
- 막힘·결정 필요: 현재 Docker 엔진 미기동, 기본 Java는 11로 Spring 전체 통합 미실행. 실제 키/유료 모델 호출 없음. HTTP/CLI는 Anthropic이고 최근 GPT 실험은 별도 경로이며 운영 기본 설정은 토론자·중재자 모두 Opus. 실제 배포 모델과 예산 가정을 맞출 필요 있음. 기업행사 미보정·정적 30종목 허용·재시작 시 진행 중 토론 실패 처리의 운영 범위 유지.
## 2026-10-30 · Codex 총괄·독립 평가 세션 · ai-worker, docs
- 한 것: 구현·로컬 평가를 5672ace로 커밋한 뒤 최종 소스를 고정해 gpt-5-mini 실제 4조건 비교 완료. v2 개발 중 진단 0/4·27요청·$0.24590350, 커밋된 v3 검증 1/4·34요청·$0.24445650. v3 RAG single만 HOLD/raw confidence0.48로 통과, none single/debate와 RAG debate는 생성·검증 반려 한도에서 실패. 같은 snapshot/세대/모델/effort/순서 및 모든 실패 원문 보존. 전체 61응답 사용량 가격 $0.49036, 미확정0, 승인총액 $3 원장 유지. 상세 결과·논문/GitHub 조사·검토기 오탐과 모델 실제 오류를 docs/evaluations/worker-rag-live-pilot.md 및 worker-rag-evaluation-research.md에 기록.
- 진행 중: 요청한 후속 구현·테스트·실제 비교 실행·평가 기록은 완료. P1 운영 활성화/예측 성과 검증은 미충족으로 BULLBEAR_RAG_ENABLED=false 유지. v3 실행 중 소스 변경 false, snapshot/context/주입 경계 일치. 후보14개 내 근거42건 Fact ID/value 일치는 복사 검사이며 추론 정확도/예측 성과가 아니다. 운영 HTTP Anthropic과 별도 OpenAI benchmark의 검증 범위를 구분한다.
- 다음: 실제 추론 오류와 검증기 오탐을 분리한 독립 정답 집합, 가격 기준일/정보 관측 시각 및 단기 상대수익 근거 보완, 독립 검색 관련성·운영 완료율/p95/비용 기준 검증을 P1 순서로 진행. 38a4516 안정화 통합·전향 운용은 별도 후속. P2 위험 검토/LangGraph 미착수.
- 막힘·결정 필요: 전체 Python296 passed·외부2 skipped(35.21초), 별도 실제 Spring/PostgreSQL/HTTP2 passed(4.85초), Java 단위7개·bootJar 검증 완료. 외부통합의 시장/모델/시계는 fixture; 실모델은 삼성전자 snapshot1개의 반복이므로 독립 예측 표본/일반적 RAG 인과효과로 해석하지 않음. 실제3/7거래일 확정수익률·대표표본 운영기준 미검증. 추가 비용 승인 불필요(남은총액$2.50964). 원본 ROADMAP/WORKLOG 사용자 변경 보존, 키/.env/로컬 데이터 커밋 및 push·PR·develop 병합 없음.

## 2026-10-30 · Codex 총괄·검색 평가·예산·Spring 하위 세션 · ai-worker, docs
- 한 것: feat/worker-rag-retrieval에서 P0/P1 후속 구현. 출처 연결 실험용 지식 common/short 6문단 import·별도 provenance·재관측 승인/거절 보존, synthetic 검색 평가 실행기/recall·MRR·precision, 한글 별칭과 실제 큰 snapshot의 핵심 질의 우선순위(v3), 4조건 비교 CLI, gpt-5-mini 입력/출력 상한과 영속 총승인 예산·실제 사용량 정산, 미가격 응답 보존·정산 실패 보고·비교 중 소스 변경 감지 구현. 실제 PostgreSQL/Flyway/Spring/HTTP의 봉인→판정→공개→당일 재사용→3/7거래일 채점 경로 검증. 조사·검토·한계는 docs/evaluations/worker-rag-p1-followup.md에서 주제별 문서로 연결.
- 진행 중: 사용자 승인 gpt-5-mini/전체 USD 3로 최초 실모델 4조건 파일럿 실행 중. data/rag-p1-live/comparison-1은 v2 고정 context이며 실행 중 코드 검토·개선 사실을 별도 기록한다. 기준선 single/debate는 검증 반려 후 각각 5/8호출로 실패했고 사용량 가격 합계 $0.11472715; RAG 조건 결과는 종료 후 별도 기록. 이 실행을 최종 v3의 성능 증거로 바꾸지 않는다.
- 다음: 최초 파일럿 실패·비용·원문 보존, 최종 소스와 v3 불변 context의 실모델 검증 및 운영 활성화 판정 기록. 모든 후속 호출은 ai-worker/data/rag-p1-live/authorization.sqlite3와 rag-p1-20261030-user-approved-3usd를 재사용하며 3달러 한도를 재설정하지 않는다. 완료 후 한국어 후속 평가 커밋.
- 막힘·결정 필요: 전체 Python 296 passed·외부 2 skipped(35.21초), 별도 실제 Spring 2 passed(4.85초), Java HTTP/채점 단위 7개와 bootJar 검증. Spring 시장/LLM/시계는 fixture이고 API 원시 비용·예측 성과가 아니다. 실제 corpus는 인간 검수 전 experimental; 독립 자연 질문 평가·운영 완료율/p95/비용 허용 기준·성숙한 3/7거래일 결과는 미충족. BULLBEAR_RAG_ENABLED=false 유지, P2 미착수. 키/.env/로컬 시장·API 데이터·DB·런타임 커밋, push·PR·develop 병합 없음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: fetch 후 원격 feat/worker-rag-context HEAD=2f6af9f 및 이후 커밋 없음 확인. 해당 HEAD에서 독립 worktree/feat/worker-rag-retrieval 생성, 포함된 감사·benchmark·ingest 선행 커밋 보존. Retriever 실제 구현(common 2/short 3·경로별 후보 20·6000자/2000 UTF-8 byte 보수 상한·검색 1초), 시점/활성 revision/검수/시장/종목 필터, 고정 세대 BM25·NFC/별칭, 원자적 세대 발행/무결성, 검색 감사·불변 컨텍스트 저장/재생·CLI publish/retrieve/replay 구현. HTTP/benchmark fingerprint에 저장/재생 소스도 포함.
- 진행 중: 이번 검색·통합 구현은 완료. P1 운영 활성화 검증은 남아 BULLBEAR_RAG_ENABLED=false 유지. 별도 조사 세션에서 공식 문서·논문·GitHub 확인, 조사 문서와 실제 결과를 docs/evaluations/worker-rag-retrieval-research.md 및 worker-rag-retrieval.md에 기록. 추가 검토 세션 생성은 자동 승인 정책으로 차단되어 현재 세션에서 검토·검증.
- 다음: 실제 검수 corpus/한국어 자연 질문 정답 집합 검색 품질 평가, 명시 모델·가격표·입력 여유·호출 상한으로 실모델 비교, 실제 Spring/공급자 연결·전향 지연/비용/완료율 기준 검증. 이관 v1 색인은 v2로 재발행 필요. P1 활성화 기준 충족 전 P2 위험 검토/LangGraph로 확장하지 않음.
- 막힘·결정 필요: 최종 Python 225 passed·외부 Spring 2 skipped(25.39초), 집중 회귀 29 passed(14.93초), diff 공백 검사 통과. 실제 SQLite 저장→검색→HTTP/benchmark 사용; 시장/LLM은 fixture. 50문서 30회 30/30 완료·context 1개, 검색 p95 0.031초/max 0.032초·저장 포함 p95 0.047초. 비교 4/4 완료·조건별 16 fixture 요청, 비용/accuracy=null이며 예측 성과 아님. OS I/O 강제 종료/실시간 1초 보장 아님(최대 4 reader·늦은 결과 폐기·저장은 검색 한도 밖). 실제 키·유료 모델·운영 corpus·가격표·성숙한 3/7거래일 결과·Spring 봉인 외부 통합 미검증. 원본 변경/키/.env/로컬 데이터 커밋, push·PR·develop 병합 없음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: feat/worker-rag-context 독립 worktree를 develop에서 만들고 감사 dc4040f·benchmark e66c062/6edd8ec·ingest c7eb1a7을 명시적으로 cherry-pick. 충돌한 모든 WORKLOG 보존. 불변 KnowledgeContext·별도 세대 FTS5 초안, 토론자/중재자/의미 검토 동일 배경 주입·공개 지식 ID 차단, HTTP 비공개 감사/설정 연결, none/common_short 내부 비교를 구현. 상세 조건·실측·이관 명령은 docs/evaluations/worker-rag-context-checkpoint.md.
- 진행 중: 사용자 최신 이관 요청에 따라 구현 중단한 WIP 체크포인트. rag/retrieval.py가 없어 실제 검색 활성 경로는 미완성. BULLBEAR_RAG_ENABLED=false 유지. 부모 채팅이 push와 통합 이관 메모를 담당하며 이 채팅은 push·PR·develop 병합하지 않음.
- 다음: 다른 컴퓨터에서 이 브랜치 체크아웃 후 평가 문서 순서대로 Retriever(common 2/short 3·각 후보 20·시장/시점/검수 필터·1초 상한), 검색 감사/재생·세대 시점/무결성 검증, 실제 저장층→검색→HTTP/benchmark 평가를 이어간다. 38a4516은 적용하지 않았고 상세 설계 9c91086은 별도 docs/worker-rag-design 브랜치 참조.
- 막힘·결정 필요: 최종 전체 Python 200 passed·외부 Spring 2 skipped(43.99초), 공백 검사 통과. context/index 4개, 에이전트/의미/표현 71개, benchmark 19개, HTTP/감사/서버 31개+상태 3개 부분 검증도 통과(중복 묶음 합산 금지). fixture none/common_short 모두 2/2 완료·16요청, 셀 경과 0.211380/0.268008초, 비용 미산정 null. 검색 정답/실제 공급자/유료 모델/실제 7거래일 예측·Spring 통합은 이번에 검증하지 않음. HTTP는 주입 Retriever 연결 검증뿐. 원시 confidence는 보정 확률이 아니며 P2 위험 검토/LangGraph는 시작하지 않음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: HTTP 토론 시작·전체 스냅샷 고정·클라이언트 생성·역할별 LLM 호출·성공/실패를 data/audits/<debate_id>/manifest.json에 원자적 교체와 fsync로 저장. 코드 revision/dirty, 정책·프롬프트·스키마 해시, 정확한 snapshot ID/decision_at, 선택/실제 모델과 사용량·단계 시간 기록. 키·원시 예외·토큰 비기록과 공급자 오류 경고 상세 제거. HTTP/SSE·날짜 재사용·판정 봉인 경계 유지.
- 진행 중: 없음. feat/worker-run-audit에 구현·최종 전체 검증 완료, develop 반영 전. 평가·한계는 docs/evaluations/worker-run-audit.md.
- 다음: 실제 Spring HTTP 연동과 전향 운용에서 감사 산출물 확인. CLI/내부 비교 실행기 연결은 별도 작업.
- 막힘·결정 필요: Python 전체 106개 통과, 외부 Spring 통합 2개 건너뜀. Docker·실제 시장 API·유료 LLM 외부 실측은 하지 않음. 응답 직후 저장 전 종료의 미확정 청구량과 저장장치 장애는 복구 보장 없음. 초기 실행 재개·재시작 감사 상태 보정은 미구현이며 마지막 running 기록을 보존. 키와 로컬 실행 데이터는 커밋하지 않음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: feat/worker-paired-baseline에서 내부 benchmark 실행기 구현(e66c062). 동일 Snapshot JSON을 두 조건에 독립 복원하고 중립 단일 분석가와 기존 3라운드 토론을 비교. 최종 모델·effort와 7거래일 코스피 상대수익 판정 기준을 공유하고 단일 조건도 Fact·수치·표현·기간·의미 검증 및 재작성을 적용. 기존 선공 비교 실행기·운영 HTTP API·당일 캐시·Spring 봉인 계약은 유지.
- 한 것: fixture/live/주입 테스트 더블 구분, 실제 실행 --allow-paid·명시 모델 필수, 조건별 요청 상한·SDK 재시도/모델 폴백 비활성, 조건/배치 실패·손상 입력 보존, 프롬프트/원응답/검증 시도·시간·실제 모델별 토큰·코드/설정/프롬프트/스키마/스냅샷 해시 기록. 동일 배경 묶음 연결과 실제 최종 모델 불일치 시 비교 제외를 지원. docs/evaluations/worker-paired-baseline.md에 실행·산출물·한계·후속 KnowledgeContext 연결 방법 기록.
- 진행 중: 없음. 루트 기존 .venv와 전용 worktree PYTHONPATH로 Python 전체 106개 통과·외부 Spring 2개 건너뜀(61.43초). 새 테스트는 동일 입력·6발언·재작성·실패/원문 보존·호출 상한·입력 변조·fixture/실제 구분·SDK 폴백 비활성·실제 응답 모델/캐시 토큰·잘못된 배경 연결을 확인. staged diff 공백 검사 통과.
- 다음: 공통/단기 KnowledgeContext를 한 번 고정해 두 조건에 같은 JSON으로 주입하고 별도 출력 디렉터리에서 비교. 허용된 실제 호출은 공급자 키·모델·요청 상한을 명시해 실행한 뒤 확정된 3/7거래일 결과를 연결(담당자). root가 원본 develop에 기능별 cherry-pick 통합 예정.
- 막힘·결정 필요: 실제 공급자·유료 LLM·Spring/PostgreSQL 전체 통합·전향 성과 검증은 실행하지 않음. fixture/판정 일치는 예측 품질 증거가 아니며 confidence는 보정 확률이 아님. 가격표 미구현으로 cost_usd는 null, 응답 없는 요청은 사용량 미확정으로 표시. 자동 실행 재개·운영 API·검색 정책 변경·push·PR은 하지 않음.

## 2026-10-30 · Codex · ai-worker, docs
- 한 것: feat/worker-rag-ingest 전용 worktree에서 최소 RAG 원문 저장·수집 계층 구현. 별도 SQLite WAL 스키마 v1, SHA256 원문 objects, 현재 NewsArticle/Disclosure 캡처 변환, 안정 문서 ID·불변 revision·관측 항목·A→B→A 활성화·철회 사건·수집 상태/거절 수·완료 watermark 보존. 네트워크 없는 bullbear rag import/sync/inspect와 후속 문단·복수 기간 태그·기간 단위·검수 이력 API 추가. 평가/사용 안내는 docs/evaluations/worker-rag-ingest.md.
- 진행 중: 없음. 실제 worktree 소스를 PYTHONPATH로 지정해 신규 회귀 27개 통과, 최종 전체 Python 118개 통과·외부 Spring 2개 건너뜀(44.51초), git diff 공백 검사 통과. 독립 검토의 늦게 도착한 관측 캡처 재생 문제를 수정하고, capture별 격리·정상 확인 회복 및 document_at 다중 조회의 WAL 스냅샷 일관성까지 검증.
- 다음: 현재 공급자 캡처 생산자/일별 적재를 연결하고 coverage를 실제 확인. 후속 검색은 document_at으로 당시 활성 버전을 먼저 확정한 뒤 문단·검수 이력과 세대별 색인·고정 KnowledgeContext를 연결. 원문/관측 API와 마이그레이션 DDL은 rag/schemas.py·store.py에 있음.
- 막힘·결정 필요: 실제 공급자·본문 크롤링·스케줄러·검색/임베딩·LLM/그래프·Spring/PostgreSQL 통합은 이번 범위에서 실행/구현하지 않음. 현재 뉴스 API의 고정 페이지 상한은 완전 수집을 증명하지 않으므로 미확인 범위는 partial로 저장해야 함. 공개 관측 시각은 생산자가 제공한 증거를 신뢰하며, 원문 손상은 실패 처리. 기존 API·워커 계약 변경, push·PR 없음.

## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 사용자 요청대로 기능별 커밋을 develop에 직접 푸시하고(머지 커밋 없음), 실제 양쪽 선공 6발언·중재자 완료. 최종 결과 20261029-171045-91cbd6f9, GPT-5.4/7d-concise-v4: 매수 선공 SELL·0.68, 매도 선공 SELL·0.71. 동일 삼성전자 스냅샷 사용. 전체 원문 debate-transcript-ko.txt와 출력 재검사 output-audit.json 저장.
- 진행 중: 없음. 첫 GPT-5 mini 실행 중단, v4 mini 두 조건 중단, GPT-5.4 인용 검사 오탐 중단을 모두 보존하고 docs/experiment.md에 기록. 마지막 실행은 검증 완료 첫 주장 2개씩을 원문 그대로 이어받아 남은 4발언·중재자를 새로 생성했으며 재사용 출처를 manifest/report에 명시.
- 다음: 반복 표본으로 선공 영향 평가, 코스피 비교 입력·기준 시각 정합성 개선, '7거래일 뒤 종가' 표현 엄밀성 및 예고된 일정과 발표 내용의 새로움을 구별하는 의미 평가 보완.
- 막힘·결정 필요: Python 91개 통과(외부 Spring 2개 건너뜀), Java HTTP 클라이언트·채점 7개 통과. Docker 전체 통합은 미실행. 최종 12발언과 두 중재자 출력 규칙 재검사 위반 없음. 개념·논리 무오류나 투자 성능 보장은 아님. 주가/뉴스 시각 차이·코스피 비교 입력 부재·기업행사 미보정 한계 유지. 키와 로컬 원본 데이터는 커밋하지 않음.

## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 기능별 8개 커밋을 develop에 푸시(3b5aa1a~89ed891, 머지 커밋 없음). 새 전체 실험 20261029-163807-601bc2c2는 매수 선공 4발언 뒤 마무리 3회 반려로 중단(972.199초); 결과 선택 없이 실패 원문 보존. 새 근거 누락과 변동성→상승 확률 비약을 확인.
- 진행 중: 7d-concise-v4 보완. 발언자·라운드·발언별 인용 대응을 검토 입력에 명시하고 불확실한 예측과 확정 사실을 구분. 실제 반박 대상 오인 사례는 지침만 바꾼 gpt-5-mini 재검토에서도 누락(data/audits/review-regression-v4.json)되어, 상대 원문 인용과 반대편 발언 문자열 일치를 코드로 검사하도록 추가.
- 다음: 수정 커밋 푸시 후 동일 스냅샷으로 두 조건을 처음부터 재실행하고 실제 대화·중재자 판정 기록.
- 막힘·결정 필요: Python 91개 통과, 외부 Spring 2개 건너뜀. Java 관련 7개 통과. 코드 인용 일치도 인용의 해석·논리까지 보증하지 않으며 모델 의미 검토의 오탐·누락은 남음. 원래 판정 구간·3문장·3근거·새 근거 규칙과 실패 시 중단은 유지.

## 2026-10-29 · Codex · ai-worker, api, docs
- 한 것: 사용자 요청에 따라 기존 미커밋 변경을 데이터 공급자, LLM 연동, 판정·의미·표현 검증, 선공 비교 실행기, HTTP/SSE 서버, Spring SSE 처리, 실행 안내, 실험 기록으로 나누어 커밋. 비밀 설정과 원본 실험 데이터는 git 제외 확인. Python 89개 통과, 외부 Spring 연동 2개는 환경 미설정으로 건너뜀.
- 진행 중: 기능별 커밋을 원격 develop 위에 순서대로 반영하고 푸시 준비. 이후 동일 삼성전자 스냅샷과 7d-concise-v3 기준으로 양쪽 선공 전체 토론을 새로 실행할 예정.
- 다음: 매수 선공·매도 선공 각각 6발언과 중재자 판정을 저장하고 실제 대화·결과를 비교하여 기록.
- 막힘·결정 필요: session-brief.sh의 기존 CRLF/WSL 문제로 git·작업 로그를 직접 확인. 기본 Java 환경에서 JDK 17 탐색 실패 후 기존 로컬 JDK 17 경로로 HttpWorkerClientTest·ScoreRuleTest 통과. Docker 전체 통합 스위트는 이번에 실행하지 않음.
## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 사용자 지정 판정 질문을 그대로 프롬프트에 반영하고 HOLD를 코스피와 비슷하게 움직일 구간 예측으로 정의(7d-concise-v3). 주장 한 줄/본문 최대 3문장/근거 최대 3개, 반박·마무리에서 전체 토론 미사용 근거 최소 1개, 뉴스·공시 우선 탐색, 조 원 표시 및 원값 보존을 구현·검사. 중재자 글에서 내부 ID·검증 통계·투자자별 권고 제거, [E1]↔decisive_evidence[0] 대응 검사 및 계약 문서 설명 보강(필드 변경 없음).
- 진행 중: 없음. 실제 모델 스모크 완료(data/audits/concise-smoke-20261029.json 및 .txt): 새 마무리 3문장/근거 3개/미사용 공시 DISC.20261008800004 포함(3번째 생성에 통과), 중재자 이유 3문장 및 번호 대응·내부 표현 비노출 통과. 중재자 의미 검토 2회. 기존 토론을 문맥으로 쓴 제한적 점검이며 새 전체 토론 실험은 아님.
- 다음: 웹에서는 기존 배열 순서로 근거 번호 칩을 연결할 수 있음. 새로운 공시라도 과거 사건일 수 있으므로 단기 계기 관련성과 정보 시점은 의미 검토 및 반복 평가에서 계속 확인.
- 막힘·결정 필요: Python 89개 통과(Spring 외부 통합 제외). 기존 PER 검사에서 '상대적으로 큰'의 '적'을 잘못 잡는 오탐도 수정·회귀 테스트 추가. DART 공식 API 재조회 입력과 기존 캐시 일치, TTM 영업이익률 36.8793%→36.88% 확인. KRX 종가 21개 재조회 모두 캐시와 일치, 로그수익률 표본표준편차 연율화 68.1677%→68.17% 확인. 최신 분기 이익률/20일 등락폭이 아님. docs/metric-audit-20261029.md 참조. 과거 스냅샷은 보존, 새 지표 설명만 보강. session-brief.sh는 기존 CRLF/WSL 문제로 실패.
## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 양측·중재자·검토 역할의 판단을 7거래일 코스피 대비 초과수익(+2%p 초과 BUY/-2%p 미만 SELL/사이 HOLD)으로 통일. 기존 인용 검증에 PER 역전·검증 정확성 과장 규칙 및 별도 대화의 개념/논리 검토 추가. 오류 피드백 재작성, 최대 시도 실패 시 토론 중단, 중재자도 검토. ref 스키마/피드백 및 검토 인용 처리 보완. 전체 Python 72개 통과(Spring 외부 통합 제외), diff 공백 검사 통과.
- 진행 중: 없음. 동일 스냅샷 005930-20261028-c637dc2629로 양쪽 각 6턴 완료(data/experiments/20261029-141251-5fe2a2ca). 발언 반려 5회/4회, 최종 12발언 통과. 중재자 검토에 코드 통계가 빠져 오탐한 누락을 수정·테스트한 후 같은 발언으로 양쪽 중재자를 재생성: 최종 매수 선공 HOLD/0.42, 매도 선공 SELL/0.65. 최초 HOLD/0.30·SELL/0.60도 보존. comparison-reviewed.json 및 debate-transcript-ko.txt 저장. 앞선 중단·회귀 점검 기록은 docs/experiment.md 참조.
- 다음: 코스피 비교 지표·판단 시각 정합성 보완, 고정 오류 코퍼스의 오탐/누락률 및 반복 실험으로 검토·선공 편향 측정. 검토 반려 횟수가 중재자 점수에 미치는 영향도 분리 평가할 것.
- 막힘·결정 필요: 같은 모델의 별도 대화 검토는 독립적 정답 검증이 아님. 실제 점검에서 PER 오류 누락/비연속 인용/인용 정확성 과장을 확인해 규칙·지침 보강. 코스피 비교 지표 미제공, 뉴스 시점과 종가 기준일 차이, 기업행사 보정 미구현 한계 유지. 계약/API 형식 변경 없음. session-brief.sh는 기존 CRLF/WSL 문제로 실패하여 작업 로그·브랜치/최근 커밋을 직접 확인.
## 2026-10-29 · Codex · docs
- 한 것: 사용자 요청으로 20261029-124549-3170d2d3의 실제 두 조건 토론·중재자 기록 조회. 전체 주장·본문·근거·판정을 같은 로컬 결과 폴더의 debate-transcript-ko.txt로 추출하고 대화에 발췌 제공.
- 진행 중: 없음. 추가 LLM 호출·코드 변경 없음.
- 다음: 투자기간 통일 및 논리·개념 검증 보완 검토.
- 막힘·결정 필요: 매도 선공 최종 발언에 낮은 PER을 '시가총액 대비 이익이 상대적으로 작음'이라고 설명한 개념 오류 발견. 원문을 고치지 않고 별도로 지적. 기존 수치/근거 ID 검증만으로 이런 오류는 잡히지 않음. 읽기·텍스트 추출 작업으로 테스트 미실행.
## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 유가증권 일별매매정보 승인 후 .env 키로 재시도 성공(HTTP 200, 20261028 기준 940행). 삼성전자 265거래일 수집·캐시 생성, KRX+DART+네이버 뉴스 스냅샷 005930-20261028-c637dc2629 확보(주가 19/재무 21/가치평가 10/공시 30/뉴스 30). OpenAI gpt-5-mini 선공 비교 각 6턴+중재자 완료: 매수 선공 HOLD/0.62/333.570초, 매도 선공 HOLD/0.55/301.960초. 결과 data/experiments/20261029-124549-3170d2d3 및 docs/experiment.md 기록.
- 진행 중: 없음. 각 턴 이전 발언 0~5개 전달 및 최종 12발언 검증 통과, 반려 0회. 이번 턴은 실행·문서 기록만 수행, 코드 변경 없음.
- 다음: 정식 실험 전 투자기간·코스피 대비 판정 기준을 프롬프트에 통일하고 뉴스·공시 활용 방식 검토. 실제 인용은 PX/FIN/VAL에 한정됨. 기업행사 보정 및 미래 수익률 채점은 별도 보완.
- 막힘·결정 필요: API 인증 차단 해소. 주가는 10/28 종가, 뉴스는 10/29 낮 기준으로 과거 종가 시점 백테스트가 아님. 1쌍으로 선공 효과나 투자 성능 판단 불가; 인용 검증은 원천 정확성·논리 보장이 아님. 테스트 재실행 없음(이전 Python 54개 통과), Spring 외부 통합 미확인. 키 값 출력/변경 없음.
## 2026-10-29 · Codex · docs
- 한 것: 사용자 요청으로 현재 .env 키로 KRX 재시도. KOSPI 시리즈 일별시세정보 HTTP 200/54건 성공, 유가증권 일별매매정보는 HTTP 401 유지(기준일 20261028).
- 진행 중: 주식 일봉 API 인증 문제만 남음. 새 시세 스냅샷·토론은 미실행.
- 다음: 유가증권 일별매매정보(sto/stk_bydd_trd)의 서비스별 승인/이용 상태 확인 후 재호출.
- 막힘·결정 필요: 동일 키로 지수는 성공하므로 키 전체 오류로 단정할 수 없음. 주식 API 거절 원인은 응답만으로 미확정. 코드 변경·테스트 없음.
## 2026-10-29 · Codex · docs
- 한 것: 사용자의 이용 허가 완료 안내 후 .env를 직접 다시 읽어 KRX 주식·코스피 API 재호출. 모두 HTTP 401/respCode 401. 키 앞뒤 공백·줄바꿈·셸 키 충돌 없음. 주식 .json GET 및 POST 호출도 동일한 401 확인.
- 진행 중: KRX 연결 원인 진단. 승인 미완료로 단정하지 않음.
- 다음: 사용자 콘솔의 해당 API 샘플 테스트 결과 및 승인 서비스명/유효기간을 키 없이 확인하여 로컬 요청과 비교.
- 막힘·결정 필요: 승인 완료라는 사용자 정보와 현재 API 인증 거절이 함께 존재. 응답만으로 원인 확정 불가. 새 시세 실험 미실행; 코드 변경 없음.
## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 사용자 입력 후 KRX_API_KEY 존재 확인. 실제 승인 API의 유가증권 일별매매정보(sto/stk_bydd_trd)와 코스피 지수(idx/kospi_dd_trd)를 20261028 기준으로 호출해 모두 HTTP 401, respCode 401, Unauthorized API Call 확인. 키 값 출력 없음.
- 진행 중: 새 시세 기반 스냅샷/토론 미실행. DART·네이버 뉴스의 이전 연결 성공은 유지하되 네이버 시세로 대체하지 않음.
- 다음: 사용자 KRX 인증키 발급 승인 및 두 API의 개별 활용 승인 상태 확인 후 재호출.
- 막힘·결정 필요: 401 응답만으로 잘못된 키/미승인 키/서비스별 권한 부족을 구별할 수 없음. 이번에는 연결 확인만 수행, 코드 변경 및 추가 테스트 없음.
## 2026-10-29 · Codex · ai-worker, docs
- 한 것: 입력된 키 값을 노출하지 않고 인증 확인. OpenDART 회사 조회 HTTP 200/status 000, 삼성전자 재무 2026 H1·2025 FY·2024 FY 각 6계정, 발행주식수 및 최근 공시 88건 조회 성공. 네이버 뉴스는 API HUB 주소·NCP 헤더·JSON 파라미터로 이전, HTTP 200 및 현재 시각 기준 필터된 뉴스 197건 확인(스냅샷에는 기존 최대 30건 제한 적용).
- 진행 중: 새 KRX 시세 + DART + 뉴스 토론은 아직 미실행. ai-worker/.env에 KRX_API_KEY 항목이 없음. 기존 네이버 시세로 대체 실행하지 않음.
- 다음: KRX_API_KEY와 주식·지수 API 활용 승인 확인 후 과거 일봉 수집/스냅샷 생성, OpenAI 선공 비교 재실행. .env는 --env-file 옵션으로 명시해 셸의 오래된 키 우선 문제 방지.
- 막힘·결정 필요: KRX 키 추가 필요. Spring 외부 통합 제외 Python 54개 통과. 뉴스 최근 300건 조회 제한으로 과거 시각 재현은 별도 수집·보관 없이는 보장되지 않음(오늘 0시 종료 조건에서는 0건, 현재 시각에서는 197건). 키 파일 변경/출력 없음.
## 2026-10-28 · Codex · ai-worker, deploy, docs
- 한 것: 사용자 요청에 따라 HTTP/CLI의 주식·지수 공급자를 KRX 공식 OPEN API로 변경. 재무·발행주식수·공시는 OpenDART, 뉴스는 네이버 검색 API 유지. 날짜별 압축 캐시/호출 간격/응답 날짜 검증/오류 구분 구현, 네이버 시세 자동 대체 없음. 운영 compose에 KRX_API_KEY 전달 추가.
- 진행 중: 없음. 기존 네이버 시세 스냅샷 기반 OpenAI 예비 실험 2건 완료(매수 선공 HOLD/0.60/238.908초, 매도 선공 HOLD/0.65/194.438초). 6턴씩 누적 기록 전달, 최종 발언 12개 검증 통과. 결과는 data/experiments/20261028-184414-88afeee1 및 docs/experiment.md 참조. 새 .env 키 인증 성공; 기존 셸의 다른 키 문제에 대응해 실험 --env-file 옵션 추가.
- 다음: KRX 인증키 및 주식·지수 API 활용 승인, OpenDART·네이버 뉴스 키 설정 후 신규 스냅샷 생성 및 새 실험. 서버 사용 전 snapshot 명령으로 과거 시세 캐시 준비(최초 날짜별 수집은 15초 초과 가능). 파일럿에서 중재자가 투자기간 미명시를 지적했으므로 정식 실험 전 7거래일·코스피 대비 기준을 양측/중재자 프롬프트에 일치시킬 것.
- 막힘·결정 필요: 사용자 KRX/DART/뉴스 키 없음. KRX 공개 샘플 주식·코스피·코스닥 응답 확인; 인증키 기반 실제 기간 조회 미검증. Spring 외부 통합 제외 Python 53개 통과, 신규 snapshot 명령의 KRX 키 누락 오류 확인. KRX 원시 일봉의 기업행사 보정은 미구현(스냅샷 경고); 정식 수익률 평가 전 보완 필요. 사용자가 변경한 .env 및 삭제된 .env.example은 건드리지 않음.
## 2026-10-28 · Codex · ai-worker, docs
- 한 것: 사용자 요청으로 OpenAI Responses 실험 어댑터와 `--provider openai --model` 옵션 추가. openai 의존성/lock 갱신. 도구 호출·구조화 응답·추론 항목 유지·검증 피드백·캐시 토큰 분리 집계 구현. 기존 HTTP 워커 Anthropic 경로 유지.
- 진행 중: 삼성전자 동일 스냅샷 선공 비교 시도. 첫 호출 AuthenticationError; 별도 모델 접근 확인도 HTTP 401 invalid_api_key. 완료된 발언·중재자 판정 없음.
- 다음: 사용자가 OPENAI_API_KEY 수정 후 `data/experiments/20261028-183721-999aaa72/snapshot.json`으로 같은 실험 재개. 결과 로그·판정·반박 내용 비교.
- 막힘·결정 필요: 현재 키 인증 실패. DART·뉴스 키 미설정으로 해당 스냅샷은 시세 중심(재무·발행주식수·공시·뉴스 없음). Spring 외부 통합 테스트를 제외한 Python 44개 통과, git diff --check 통과; 실제 OpenAI 성공 응답은 미검증. 키 값은 출력·커밋하지 않음.
## 2026-10-28 · Codex · ai-worker, docs
- 한 것: 순차 멀티턴 선공 비교 실행기 `python -m bullbear.experiment` 추가. 동일 스냅샷에서 매수/매도 선공 각 6턴+중재자, 추가 라운드 없이 비교. 모델·전체 발언·판정·검증 통계·토큰·시간·이벤트 기록 저장. Debate에 선택적 first_side 추가(서비스 기본 매수 선공 유지).
- 진행 중: 실제 LLM 비교는 API 키 미설정으로 중단. 실행 명령에서 키 누락을 확인했으며 외부 LLM 호출 없음.
- 다음: 사용자가 ai-worker/.env에 ANTHROPIC_API_KEY 및 사용할 모델을 설정하면 삼성전자 1개 스냅샷으로 파일럿 실행 후 양측 반박 내용과 판정 변화 확인.
- 막힘·결정 필요: 실제 모델 품질·선공 효과·수익률 성능은 미측정. 가짜 에이전트 기반 양쪽 선공의 누적 기록 전달/중재자 입력/결과 저장 및 기존 서버 테스트 17개 통과. 1쌍 파일럿은 순서 효과와 생성 무작위성을 분리하지 못함. 기존 미커밋 작업 유지.
## 2026-10-28 · Codex · docs
- 한 것: 현재 feat/worker-http-sse 작업 트리(미커밋 구현 포함)의 코드·배포 설정을 확인하고 대화에 서비스 구성 및 토론/판정 흐름 시각화. Spring의 판정 봉인, 워커 SQLite 이벤트 저장, 순차 발언, 네이버 차트 기반 HTTP 시세 경로 확인.
- 진행 중: 없음. 기존 기능 변경은 그대로 유지.
- 다음: 실제 HTTP 모드·외부 API 연동 검증 및 오래된 워커 상태 문서 정리.
- 막힘·결정 필요: 실행 중인 배포 상태와 외부 API는 이번에 검증하지 않음. 분석 작업으로 테스트 미실행. session-brief.sh는 Windows CRLF/WSL 경로 문제로 정상 요약 실패하여 git 상태·최근 커밋·작업 로그를 직접 확인; 열린 PR은 미확인.
## 2026-10-28 · ricky00-dev · api, web
- 한 것 (feat/time-machine-quiz):
  - `debate_outcomes`: 끝난 토론마다 7거래일 뒤 실제 결과(종목·코스피·초과수익)를 한 번 기록 (`OutcomeRecorder`, 채점과 같은 시각 + 시작 시 따라잡기). 실험 집계에도 쓸 수 있음
  - 퀴즈 API `POST /api/quiz/rounds`, `GET /api/quiz/rounds/{id}`, `POST /api/quiz/rounds/{id}/questions/{idx}/answer`
    - 문제: 결과가 기록된 토론에서 무작위 5개. 이미 풀었거나 실제로 판정한 토론은 뒤로. **결과를 보고 고르지 않음**
    - 공개 전: 종목명·별칭·종목코드를 "이 회사"로 가림, 차트는 판정일까지만(날짜·가격 없음), 힌트는 업종 + "몇 월 몇째 주"
    - 답하면 종목·실제 결과·AI 판정과 이유·전체 차트 공개. 기록은 `quiz_*` 테이블, 실제 판정 통계와 분리
  - 웹: 하단 탭 "리그"(미구현 자리) → "퀴즈". 입구 / 문제 / 공개 / 한 판 결과(나 vs AI)
  - 말풍선 컴포넌트 공통화 (`StatementBubble`), 차트 날짜 가림 모드
  - 채점 예정일이 지났는데 아직 채점 전이면 "곧 채점"으로 표시 (지난 날짜에 "예정"이 붙던 문제)
  - 발언 말풍선 "자세히 보기": 접혀 있다가 펼치면 `argument`(근거별 설명) 표시. [E1] 표시와 주장 반복은 뺌. 가짜 워커 argument도 실제처럼
- 확인: QuizFlowTest(가림·채점·중복 답 방지·남의 퀴즈 404·통계 분리), 브라우저로 시계 +11일 띄워 한 판 끝까지
- 다음: 전시 모드 (ricky00-dev)
- 막힘·결정 필요: 실제 문제는 전향 운용 시작(늦어도 11/4) 뒤 7거래일, 즉 11/13쯤부터 생긴다. 그 전 시연은 가짜 워커 + 시계 앞당김으로
## 2026-10-28 · ricky00-dev · api, web
- 한 것 (feat/price-chart, #15):
  - `GET /api/debates/{id}/chart`: 판정일 앞 약 20거래일 ~ 7거래일 뒤(+2)까지, 종목·코스피를 판정일 종가 대비 수익률(%)로. 3·7거래일 지점(도달 전엔 예상일)
  - 두 선의 차이 = 채점 초과수익 (ChartFlowTest로 확인). 확정 종가만 씀
  - `PriceHistory`: (종목, 기간)별 그날 하루 캐시. 결과 화면을 여러 명이 열어도 워커는 하루 한 번
  - 채점 결과 화면에 `ReturnChart`: 판정 뒤 회색 띠 = 코스피 ±2%p(보류 구간). 판정 직후에도 7일까지 자리를 비워 두고 예정일 표시
  - 가짜 워커: 10/22 이전 시세도 거꾸로 생성(차트용), 모든 종목 스파크라인, 등락을 섞어 직선처럼 안 보이게
- 확인: API 테스트 20개 통과, 브라우저로 SK하이닉스(3일 채점 후)·현대차(판정 직후) 화면 확인
- 다음: 타임머신 퀴즈 (ricky00-dev). ROADMAP의 주가 차트 항목 체크는 #14 머지 뒤
- 막힘·결정 필요: 없음. 워커의 `/prices/daily`, `/indices/daily`가 판정일 30일 전부터도 응답해야 차트 앞부분이 나온다 (계약상 기간 조회라 추가 작업 없음)
## 2026-10-28 · ricky00-dev · web, docs
- 한 것 (feat/plain-terms):
  - 토론 발언·중재자 이유 본문의 투자 용어(40여 개)에 점선 밑줄 → 누르면 쉬운 풀이 시트 (`lib/glossary.ts` `TERMS`, `components/TermText.tsx`)
  - 같은 용어는 발언마다 처음 한 번만 밑줄. 영문 약어는 단어 경계를 지킴 (PERFORMANCE 속 PER 무시)
  - 시트 공통화 `ui.tsx` `BottomSheet` (근거 시트도 이걸 씀)
  - 판정 화면 "판정 팁": 말솜씨보다 근거의 탄탄함을 보라는 한 줄
  - README 맨 위에 서비스 한 줄 정의, ROADMAP에 주가 차트·퀴즈 원칙·11/18 발표 메시지 결정·실시간 시세 제외 이유
  - worker-api.md "웹 쪽 희망 사항": 입문자 말투, 선택 필드 `statement.plain` 제안 (계약 아님)
- 확인: 가짜 워커 토론에서 밑줄·시트 동작 브라우저로 확인, tsc·lint 통과
- 다음: 주가 차트(종가) → 타임머신 퀴즈 → 전시 모드 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**): `statement.plain`을 넣을지, 발언 말투를 입문자 기준으로 할지
## 2026-10-26 · Codex · ai-worker, api, docs
- 한 것: 최신 develop 7967fb8 기반 feat/worker-http-sse에서 HTTP/SSE 서버 구현. v0.4 엔드포인트·이벤트 + 저장소의 v0.5 비동기 snapshot_id 응답 사용 (계약 형식 변경 없음).
  - 인증·오류 형식, 종목 검색/상세/가능 여부, 토론 생성/조회, 스냅샷, 종목·지수 일별 종가. 확정 종가만 사용하고 화면·스냅샷 일봉을 공유.
  - SQLite 영속 이벤트·요청 멱등성, 종목/기준일 재사용, 동시 실행 한도, SSE 재생/Last-Event-ID/하트비트, 재시작 시 중단 토론 실패 처리. 데이터 디렉터리당 단일 프로세스 강제.
  - 검증 실패 발언·원시 토큰·중간 판정 비공개, 최종 scores 변환, 실제 응답 모델별 캐시 생성 포함 토큰 집계, Haiku fallback 옵션 제외.
  - Spring worker 프로필 및 종료 이벤트 없는 SSE EOF/타임아웃 처리. README에 실행·제약·통합 테스트 절차 기록.
  - 검증: Python 38개 통과 (실제 Spring+PostgreSQL+HTTP 워커 통합 2개 포함), Java HTTP 클라이언트/채점 규칙 7개 통과. 실제 삼성전자 종가·코스피 지수 조회 성공. git diff --check 통과.
- 진행 중: 없음. 변경 미커밋. 이전 분석 로그 보존.
- 다음: 담당자가 API 키를 설정하고 실제 LLM 토론·DART·뉴스 호출 검증. 운영에서는 WORKER_TOKEN 일치, worker 프로필/WORKER_MODE=http, 단일 프로세스 및 데이터 볼륨 유지.
- 막힘·결정 필요: API 키 없어 유료 LLM·DART·뉴스 인증 연동 미검증. Docker 빌드/기존 Testcontainers 전체 스위트 미실행 (Docker 없음); 대신 임시 PostgreSQL 16.4 + Java 17 + Uvicorn으로 실제 HTTP/SSE/DB 저장/봉인/공개/채점 예약 검증. 테스트 프로세스는 종료함.
  - 현재 토론 허용 기준은 기존 UNIVERSE 30종목. 전체 ETF/우선주 마스터 및 시장 전체 시총·거래대금 필터는 미구현. 지수·HTTP 시세는 네이버 비공식 차트 공급자 사용.

## 2026-10-26 · ricky00-dev · ai-worker, api
- 한 것:
  - 워커 HTTP 서버 **틀만** (feat/worker-server-stub): 계약 엔드포인트 시그니처·인증·오류 형식, 내용은 전부 501
  - Spring http 모드 버그 수정 분리 (#12): Spring Boot 4 WebClient 스타터 누락으로 실제 워커 모드에서 앱이 안 떴음
  - PR #11(완성형 워커 서버)은 닫음. 에이전트·워커 설계는 jangwonii가 직접 하기로 (브랜치 `feat/worker-server`는 참고용으로 남김, 안 봐도 됨)
- 다음: M3 타임머신 퀴즈 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**): 워커 설계·구현 시작. 기존 10/20 코드는 초안이라 바꿔도 됨. `docs/worker-api.md` "Spring이 기대하는 것" 참고
## 2026-10-26 · ricky00-dev · deploy
- 한 것: 배포 준비 (chore/deploy)
  - Dockerfile: api(Gradle → JRE), web(Vite 빌드 → Caddy), ai-worker(uv, 비루트 실행)
  - `deploy/compose.yml`: Caddy(HTTPS 자동, /api 프록시, SPA) + Spring + Postgres + 워커(profile). 외부엔 80/443만
  - 로컬에서 운영 구성 실행 확인: 정적 파일·딥링크·API·SSE 스트림(버퍼링 없음)·서비스 워커·백업 스크립트
  - `docs/DEPLOY.md`: EC2 t3.small, sslip.io로 도메인 없이 HTTPS, 처음 설정·업데이트·운영 명령
- 다음: 워커 FastAPI 골격 초안 (jangwonii 인수인계용), 그다음 M3 타임머신 퀴즈 (ricky00-dev)
- 막힘·결정 필요:
  - **ricky00-dev**: AWS 계정 (11/2 전), 키 4종
  - **jangwonii**: 워커 이미지는 빌드됨. `bullbear.server:app`(FastAPI)과 `fastapi`·`uvicorn` 의존성만 있으면 뜸. 인증은 `X-Worker-Token` == env `WORKER_TOKEN`
## 2026-10-26 · ricky00-dev · api, web
- 한 것: 홈 "오늘의 토론" 피드 + 첫 방문 안내·투자 유의 고지 (feat/home-feed)
  - `GET /api/feed`: 최신 데이터 기준일 토론을 진행 중 → 판정 많은 순으로. 판정 수, 내 판정 여부 포함, 중재자 판정은 제외(봉인)
  - 워커 호출 없이 DB 쿼리 한 번. 피드의 토론은 전부 재사용 대상이라 누르면 대기 없음
  - 첫 방문 안내 시트(3단계 설명 + 투자 유의 고지), 공개 화면 하단 고지
- 다음: Docker 이미지 + 운영 compose (배포 준비, ricky00-dev)
- 메모: 이 터미널의 `NODE_OPTIONS`가 없는 파일을 가리켜 npm이 실패함 → `env -u NODE_OPTIONS npm ...`로 실행

## 2026-10-24 · Codex · docs
- 한 것: origin/develop 3046e23 체크아웃 및 구조·주요 로직 분석. 웹 npm ci --ignore-scripts, build, lint 성공.
- 진행 중: 없음. 분석 기록만 codex/repository-analysis에 추가; 기능 코드 변경 없음.
- 다음: 워커 계약 v0.4 HTTP/SSE 구현과 실제 연동 검증 우선. 판정 저장·3/7일 채점 예약의 원자성/실패 복구, 동시 요청 비용 상한 보강 검토.
- 막힘·결정 필요: PATH에 uv/Docker가 없고 기본 Java가 8이라 Python/API 테스트 미실행. 실제 외부 데이터·LLM 호출 미검증. ai-worker README의 웹·채점 미구현 설명 및 api README의 중복 방지 미구현 설명은 현재 코드와 불일치.

## 2026-10-23 · ricky00-dev · api, web, docs
- 한 것: 전향 운용 스케줄러 + 토론 재사용 기준을 데이터 기준일로 (feat/forward-run)
  - 재사용 키 `(종목, 최신 종가 날짜)`: 장 마감 뒤 만든 토론은 다음 날 장 마감 전까지 누구나 대기 없이 재사용
  - 스케줄러: 고정 10종목을 16:40·18:40에 2개씩 동시 실행, 하루 $4 상한, 서버 시작 시 밀린 회차 실행. 기본은 꺼짐
  - `docs/ARCHITECTURE.md`(LLM 지연 줄이는 4층 전략, ADR), `docs/experiment.md`(토론 vs 단일 실험 설계)
  - 워커 계약 v0.4: `GET /stocks/{ticker}`의 `as_of` 의미 명시
- 다음: 홈 "오늘의 토론" 피드 + 투자 유의 고지 (ricky00-dev)
- 막힘·결정 필요 (**jangwonii**):
  - 발언 병렬화 제안 (ARCHITECTURE ADR-2): 라운드마다 매수·매도 동시 호출 → 발언 단계 약 절반, 순서 편향 제거
  - 단일 에이전트 모드 `mode: "single"` (experiment.md) — 계약 v0.5로 같이 정하기
  - 과거 날짜 스냅샷(`as_of` 지정) 가능 여부 — 타임머신 퀴즈 문제 미리 쌓기

## 2026-10-23 · ricky00-dev · api, web, docs
- 한 것: 토론 비용 상한·중복 방지 (feat/cost-guard)
  - 같은 종목 같은 날 토론은 DB 유니크 인덱스로 1건만. 동시 요청은 먼저 들어간 토론을 재사용 (테스트로 경합 확인)
  - 워커 `usage`로 토큰·비용(USD) 저장 → 사용자 토론 하루 $3 상한, 사용자당 하루 새 토론 5회
  - 종목 화면에 남은 횟수 표시, 막히면 버튼 비활성 + 이유
  - 워커 계약 v0.3: `usage`를 모델별(`calls`) + 선택 `cost_usd`로. v0.2 형식도 받음
- 다음: 전향 운용 스케줄러 + 실험 설계 문서 (ricky00-dev)
- 막힘·결정 필요: **jangwonii** 계약 v0.3 `usage` 형식 확인. Haiku 5.5는 `fallbacks` 미지원 (ROADMAP 위험 참고)

## 2026-10-23 · ricky00-dev · docs
- 한 것: 작업 로그, AGENTS.md(Codex)·CLAUDE.md(Claude Code) 공통 안내, 세션 시작 훅, PR 템플릿 추가
- 다음: 토론 중복 방지 + LLM 비용 집계·일일 상한 (api) — ricky00-dev
- 막힘·결정 필요:
  - 전향 운용 종목 수 10개 vs 20개 (팀 결정)
  - 채점 규칙 ±2%p, 코스닥도 코스피 비교로 갈지 (팀 결정)
  - Max 결제 갱신일 확인 → 월 $200 API 크레딧 일일 상한 계산 (ricky00-dev)

## 2026-10-23 · ricky00-dev · api, web
- 한 것: 채점 스케줄러 + 내 판정 탭 + 채점 결과 화면 (#4 머지)
  - 3·7거래일 뒤 코스피 대비 채점, 거래일 달력 없이 실제 시세가 있는 날을 셈
  - `GET /api/me/judgments`, `/api/me/judgments/{id}`, `/api/me/stats`
  - QA: `BULLBEAR_DEV_CLOCK_OFFSET=P11D BULLBEAR_SCORING_CRON='*/15 * * * * *' ./gradlew bootRun`
- 막힘·결정 필요: 워커 API 계약 v0.2 (`/prices/daily`, `/indices/daily`) — **jangwonii 확인 필요**

## 2026-10-23 · ricky00-dev · api, web
- 한 것: Spring API 뼈대 (#2), React 웹 뼈대 (#3) 머지
  - 게스트 토큰, 토론 중계(SSE), 판정 봉인, 판정 제출·공개, 가짜 워커
  - 웹 5개 화면: 검색 → 종목 → 토론 → 판정 → 공개
- 다음: **jangwonii**: `docs/worker-api.md` 기준으로 ai-worker에 FastAPI 엔드포인트 구현
  (지금 워커는 CLI만 있음. Spring은 `bullbear.worker.mode=http`로 바꾸면 실제 워커에 붙는다)

## 2026-10-20 · ricky00-dev · ai-worker
- 한 것: Python 핵심 파이프라인 (CLI)
  - `MarketDataSource`(pykrx+OpenDART), `NewsSource`(네이버), 스냅샷 고정, 근거 검증기, 3라운드 토론, 중재자
- 확인 못 한 것: API 키가 없어 실제 토론·DART·네이버 뉴스는 한 번도 안 돌려봄 (시세 스냅샷만 확인)
- 알려진 문제: pykrx의 KRX API(PER/PBR, 시가총액, 전체 종목 목록, 지수)는 빈 응답 → 밸류에이션은 직접 계산

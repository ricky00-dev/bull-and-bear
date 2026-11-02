# 실제 워커·Spring·웹 RAG 연동 검증

2026-11-02 로컬 검증. [기계 판독 결과](rag-live-e2e.json)에 응답·context ID·검사15개·네트워크/DB 감사 결과를 보존했다.

## 구성과 데이터

- 웹 Vite/React `127.0.0.1:15173` → Spring Boot 실제 worker 프로필 `18080` → Python FastAPI 실제 앱 `18000`.
- Spring은 전용 PostgreSQL DB `rag_live_e2e`(포트15439), 워커는 복사한 SQLite 검색 색인/HTTP 저장소와 로컬 객체 저장소를 사용했다. 운영 DB/원본 검색 archive를 변경하지 않았다.
- 실수치: 기존 `005930-20261028-c637dc2629` 스냅샷. 원본의 날짜·Fact·출처를 변경하지 않고 HTTP 저장소에 복사했다. SHA-256은 결과 JSON에 기록했다.
- 문서: 기존 개념 평가 스냅샷을 기반으로 별도 `E2E.documents-after-publication`을 저장했다. 생성 시각은 실제 검증 시각이다. 원본 시장 스냅샷이나 과거 평가 스냅샷의 시각을 덮어쓰지 않았다.
- 별도 문서 fixture가 필요한 이유: 기존 시장/평가 스냅샷은 선택한 generation의 게시 시각보다 이르다. HTTP의 observed-v1 검증은 이를503으로 거부한다. 이전 오프라인 평가는 reconstructed-v1이므로 실제 HTTP와 시간 조건이 다르다. 과거 snapshot에서 문서 검색까지 성공했다고 해석하면 안 된다.
- Spring에는 두 저장 스냅샷을 참조하는 완료 토론과 판정 봉인 검사 이벤트만 SQL로 넣었다. 토론 생성 API·실제 모델 생성은 사용하지 않았다.

## 결과와 발견한 오류

실제 UI에서 종가 **242,000 KRW/share**, PER **9.39 x**를 확인했다. 원본 스냅샷과 값이 일치한다.
문서 fixture에서는 PER 설명 문단/적용 범위/한계를 표시했고, 무관 검색어는 no_documents로 표시했다.
날짜 불일치와 단위 불일치는200 insufficient_evidence, 혼합 필드400, 무인증401, 판정 공개403을 확인했다.
동일 수치 조회의 context ID가 일치했으며 판정 내용은 검색 응답/화면에 나타나지 않았다.

초기 실행에서 새 Fact 조회 코드가 종가를 KRW로 잘못 정의한 문제를 발견했다. 기존 snapshot 생성기는
KRW/share를 사용한다. 조회 정의·웹 단위·계약 표·테스트 fixture를 KRW/share로 정정했다.
이로써 종가 및 종가를 의존하는 PER의 계보 검사가 통과한다. 단위 자동 변환이나 검증 우회는 없다.

## 외부 호출과 검증 범위

`scripts/rag-e2e-worker.py`는 실제 앱에 loopback 외 소켓 접속 차단/감사와 조회 전용 경로 제한을 적용한다.
dotenv 읽기와 모델·시장 API 자격 증명을 비활성화하고 shadow/S3를 사용하지 않는다. 검색/Fact 결과를 대체하지 않는다.
Spring 전향 운용·단일 판정은 비활성화하고 채점/전향 cron은 `-`로 껐다.
워커 감사에서 loopback 접속2회(두 번의 프로세스 시작), 외부 접속 시도0회, 새 토론0건, Spring 토큰/비용0을 확인했다.
외부 모델 호출0, S3 연결0. 초기 브라우저 실행은 기존 Google Fonts를 요청했다. 최종 실행은 외부 asset을 차단했다.

`web/tests/rag-live.mjs`는 실제 로컬 HTTP 요청을 통과시키며 API 응답을 모킹하지 않는다.
모바일390px에서 UI와 네트워크 응답을 함께 검증했다. 별도의 워커 HTTP/Fact 회귀 **74 passed (12.70초)**,
Spring bootJar 빌드, 웹 build/lint도 통과했다. 전체 Spring 테스트 스위트를 재실행한 결과는 아니다.
이 검증은 단일 종목의 저장 수치와 작은 개념 corpus에 대한 연결 검증이며 운영 규모/검색 품질 평가가 아니다.

## 재실행

이번 데이터/manifest는 무시되는 `ai-worker/data/rag-live-e2e`에 보존했다. Spring DB는 별도 DB로 보존한다.
원본 snapshot 경로는 로컬 사용자 데이터이므로 저장소만 복제해서 바로 재현할 수 있는 fixture는 아니다.

1. 전용 PostgreSQL을 기동하고 워커 `PYTHONPATH=ai-worker/src`, `RAG_E2E_DATA=.../ai-worker/data/rag-live-e2e`,
   로컬 `WORKER_TOKEN`을 지정해 `scripts/rag-e2e-worker.py`를 실행한다.
2. Spring worker 프로필에 같은 토큰, WORKER_BASE_URL=http://127.0.0.1:18000,
   전용 DB 연결, SERVER_PORT=18080, CORS origin=http://127.0.0.1:15173을 설정한다.
   BULLBEAR_FORWARD_RUN_ENABLED=false, BULLBEAR_SINGLE_ENABLED=false,
   BULLBEAR_SCORING_CRON=-, BULLBEAR_FORWARD_RUN_CRON=-를 반드시 함께 지정한다.
3. VITE_API_BASE_URL=http://127.0.0.1:18080으로 Vite를15173에서 실행한다.
4. RAG_E2E_MANIFEST에 보존 manifest 경로, RAG_E2E_REPORT에 결과 경로를 지정해
   `node web/tests/rag-live.mjs`를 실행한다. Playwright 경로 설정은 기존 smoke 검사와 같다.
   테스트 결과 JSON은 브라우저 실행 때 덮어쓰므로 DB/네트워크 감사는 별도로 수집한다.

검증 후 로컬 서비스는 종료했다. 배포·공동 승인·S3 이전은 수행하지 않았다.

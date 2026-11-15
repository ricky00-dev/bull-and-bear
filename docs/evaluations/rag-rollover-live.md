# 스냅샷별 generation 고정과 색인 교체 검증

2026-11-02. [실제 브라우저 결과](rag-rollover-live.json), [운영 절차](../RAG-PUBLICATION-RUNBOOK.md).

## 구현과 검증 경계

최초 HTTP snapshot 저장과 generation 연결을 같은 SQLite 트랜잭션에 기록한다. 동일 ID 재저장은 원본 시각/연결을
바꾸지 않는다. 연결에는 snapshot 전체 해시와 generation ID, 원본 색인 파일 SHA-256, as_of/committed_at이 들어간다.
검색은 이 연결을 사용하고 매번 게시 무결성·관측 시점을 확인한다. 전역 설정은 새 snapshot의 후보에만 쓰인다.
Spring은 기존 토론 snapshot_id로 요청하며 공개 계약 필드는 추가하지 않았다. 웹은 저장 당시 자료로 검색함을 안내한다.

미연결 기존 snapshot을 현재 generation에 자동 연결하지 않는다. `bind-snapshot`은 저장된 성공/empty observed-v1
문서 context가 원본 snapshot 해시·게시 시각과 일치할 때만 명시적으로 연결한다. 기존 context/감사 행은 덮어쓰지 않는다.
연결된 새 검색 context는 연결 메타데이터 때문에 기존 context와 ID가 다를 수 있다. 원본 재생은 기존 ID로 가능하다.

## 실제 연결 실행

`scripts/rag-rollover-prepare.py`로 정지된 기존 `rag-multistock-e2e-v2` 테스트 자료를 새 `rag-rollover-e2e`에 복사했다.
기존 observed context 두 개를 근거로 G1에 연결한 뒤 G2를 게시하고 워커 전역 설정을 G2로 실행했다.
G1/G2의 정확한 ID, 연결 출처 context ID와 receipt는 JSON에 보존했다.

실제 React/Vite15173 → Spring18080 → FastAPI18000, 전용 PostgreSQL15439/rag_multistock_e2e와 SQLite를 사용했다.
워커를 재시작한 다음 브라우저 검사16개를 통과했다. API 응답을 모킹하지 않았다.

- 두 기존 fixture snapshot 모두 G1의 해당 종목 문서만 검색하고 실제 화면에 표시했다.
- 원본 Fact 재조회, 종목별 동시 요청/반복 context, 클라이언트 snapshot/ticker 덮어쓰기400, 모바일 표시를 검사했다.
- 연결 근거 없는 과거 원본2개는 문서 검색503, Fact 조회200을 유지했다. check-bindings도 bound/ready2개와 unbound2개를 구분했다.
- 원본 snapshot DB 바이트 전부 동일, 이전 context8개 행 모두 보존, 새 워커 토론0개를 확인했다.
- 외부 소켓 시도0, Spring 입력/출력 토큰0·비용0. 모델/임베딩 호출과 S3 연결은 없었다.

삼성전자005930은 기존 실제 수집 저장본(종가242000 KRW/share), SK하이닉스000660은 기존 fake+fake-news 저장본이다.
399는 실제 SK하이닉스 시세가 아니다. 문서도 종목 격리 fixture이며 사람 검수 금융 문서나 운영 검색 품질의 증거가 아니다.
원본 snapshot 생성 시각이나 Fact를 바꾸지 않았다. 이전 검증에서 만든 별도 fixture만 문서 검색 양성 경로에 사용했다.

## 장애·동시성 회귀

`test_rag_binding.py`는 실제 SQLite/HTTP에서 G1→G2 교체·재시작·동일 ID 최초 시각 보존, receipt 변조/누락503과
원본 복원 후 동일 context, 새 snapshot의 G2 연결, 미래 게시 거부,20개 동시 최초 저장의 단일 연결, 트랜잭션 중단 시
snapshot/연결 동시 롤백, 불변 trigger, legacy dry-run/멱등/충돌/reconstructed 거부, 유지보수 시 토론 상태 보존,
관리자에 의한 snapshot 변조 탐지를 검사한다. 별도 Fact 검증과 판정 봉인 회귀도 유지한다.

최종 전체 워커647 passed/외부 Spring5 skipped(130.14초). 이후 실제 PostgreSQL archive와 context 저장소를 함께 사용한
HTTP 고정 generation 검사를 추가하여 binding6개 통과(8.53초). Spring RAG8+HTTP client2개, bootJar, 웹build/lint,
offline wheel(binding 모듈 포함), diff 검사도 통과했다. 최초 전체는 로컬 PostgreSQL 포트 설정을 수정해 재시작했으며,
다음 전체에서 테스트 모형의 새 인자 누락2건을 수정한 뒤 위 최종 전체 결과를 얻었다.

Docker 미설치로 이미지·compose 실제 기동은 검증하지 않았다. Dockerfile의 PostgreSQL 선택 의존성과 opt-in compose
설정은 추가했으며 실제 운영 배포, 클라우드 TLS/IAM/백업 복원, 대규모 부하, 전체 Spring DB 테스트는 미완료다.
운영 품질 승인을 위해 사람이 검수한 다종목 실제 corpus와 독립 평가셋이 필요하다. 현재 결과만으로 운영 준비 전체 완료를
선언하지 않는다. 검증용 서비스는 종료하고 테스트 DB/자료는 보존한다.

# 다종목 문서·Fact 연결 검증 — 2026-11-02

게시·복구 안내에 있던 당시 검증 기록을 내용 변경 없이 분리했다. 현재 절차는 [운영 안내](../RAG-PUBLICATION-RUNBOOK.md)를 따른다.

## 다종목 연결 검증 결과

후속 [PostgreSQL 전체 복원 검사](rag-recovery-postgres.md)는 전용 로컬 DB의 pg_dump/pg_restore,
시퀀스/trigger/합성 pgvector·context/원장 보존, 대응 파일 복원과 재시작 전후8개 HTTP 응답 일치를 검증했다.
운영에서는 DB writer/워커/수집기를 정지하고 DB dump와 로컬 파일 backup의 같은 대응 묶음을 기록한다.
pg_dump는 비밀값을 인자로 출력하지 않도록 PG서비스/환경으로 접속을 제공하고 custom format으로 보관한다.
새 빈 DB에 pg_restore --exit-on-error로 복원한 뒤 역할·권한·extension을 확인하고, 원본 receipt를 포함한 로컬 파일을
복원하여 check-bindings/context replay/대표 검색을 실행한다. 로컬 검증의 no-owner/no-acl 옵션은 운영 권한 복원 검증을
대체하지 않는다. 운영 DB에 테스트 복원을 실행하지 않는다.

후속 [로컬 복원·동시 요청 검사](rag-recovery-load-local.md)에서 SQLite backup/원본 receipt 복원,
재시작 전후8개 동일 응답, 손상 백업 거부, 제한된 동시 요청192개 일치를 확인했다. 이는 로컬 fixture 결과이며
PostgreSQL 전체 복원·Docker/클라우드·운영 규모 검증은 아니다. 사람 검수 다종목 corpus는 사용자 확인상 현재 없다.

[실행 결과 JSON](rag-multistock-live.json)은 실제 웹→Spring→워커와 전용 PostgreSQL/SQLite로 검사했다.
모델/시장 수집 없이 기존 저장 파일 두 종목을 사용했다.

| 종목 | 원본 출처 | 검증 범위 |
|---|---|---|
| 005930 삼성전자 | krx-openapi+opendart+naver-news 저장본 | 원본 종가242000 KRW/share 재조회 |
| 000660 SK하이닉스 | 기존 fake+fake-news 저장본 | 모의 종가399 KRW/share 재조회·종목 분리 |

399는 실제 SK하이닉스 시세가 아니다. 다종목 실데이터 금융 정확도나 검색 품질 평가를 했다는 의미가 아니다.
두 종목 문서는 네트워크에서 가져온 금융 자료가 아니라, 종목 필터 검증용이라고 명시한 전용 문단이다.

실행 순서는 문서2개 적재·검수→게시(member_count2)→준비 확인→새 검증용 snapshot2개 저장이었다.
원본2개는 별도로 보존했고 새 복사본의 Fact는 원본과 동일함을 검사했다. 원본의 시각·ID는 바꾸지 않았다.
브라우저15개 검사: 종목 전용 문서만 반환, 원본/복사본 수치 표시, 동시6요청의 종목 분리(종목별 반복),
같은 조건 context 재사용, 다른 종목 context 구분, 원본에 미래 색인 거부, 클라이언트의 종목/스냅샷 덮어쓰기 거부,
브라우저 예외/가로 넘침 없음. 정상·오류 API 응답은 모킹하지 않았다.

워커 회귀87개 통과 후 색인 교체 검사 추가, readiness3개 재실행 통과. wheel 빌드와 웹 lint 통과.
워커 외부 접속 시도0, 새 토론0, Spring 모델 토큰0, 외부 모델 호출0/S3연결0을 확인했다.
전체 Spring 테스트 스위트나 대규모 부하 검증은 실행하지 않았다.

## 재현 자료

준비 스크립트 `scripts/rag-multistock-prepare.py`는 서로 다른 종목의 --snapshot을2개 이상 받으며 새 데이터 디렉터리만 생성한다.
자료 출처/mock 여부·원본 SHA-256·새 snapshot ID·게시/준비 시각은 manifest에 남긴다. seed는 비어 있는 전용 Spring DB만 허용한다.
`scripts/rag-e2e-worker.py`로 조회 전용 실제 워커를 실행하고, Spring 스케줄을 끈 상태로 연결한다(기존 실제 연동 보고서 참고).
`web/tests/rag-multistock-live.mjs`는 RAG_E2E_MANIFEST/RAG_E2E_REPORT 및 Playwright 경로 환경 변수를 사용한다.

이번 재현 데이터는 `ai-worker/data/rag-multistock-e2e-v2`, 전용 DB는 `rag_multistock_e2e`에 보존했다.
기본 포트는 PostgreSQL15439/워커18000/Spring18080/Vite15173이다. 원본 파일은 로컬 사용자 데이터로 커밋하지 않는다.
검증 뒤 서비스는 종료하고 데이터만 보존했다. S3·운영 배포는 수행하지 않았다.

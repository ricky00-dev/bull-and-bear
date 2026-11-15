# RAG 운영 준비 완료 여부 점검

> 이전 워커의 설계·검증 기록이다. 2026-11-10에 워커 RAG 구현을 제거했으므로 아래 명령과 배포 설정은 당시 리비전에서만 적용된다.

2026-11-02. 결론: 핵심 라우팅 구현과 로컬 복원·권한·연동 검증은 완료했다. 운영 준비 전체는 미완료다.
사용자가 사람이 검수한 corpus/독립 평가셋이 없다고 확인했다. Docker/Podman은 Windows/WSL에서 없으며,
WSL의 비특권 user namespace 실행도 Invalid argument로 실패했다. 운영 환경을 임의로 구축하거나 실제 배포하지 않았다.

## 요청 범위별 근거

| 요구사항 | 현재 근거 | 판정 |
|---|---|---|
| 기존 worktree 변경/원본 snapshot/context 보존 | feat/rag-week-one 기존 변경 유지. rollover 보고서의 원본 snapshot 바이트 비교·context8행 보존. reset/새 worktree/커밋 없음 | 구현·로컬 검증 완료 |
| 최초 snapshot별 generation 고정 | server/store.py의 snapshot+binding 단일 트랜잭션, binding.py의 원본 hash/as_of/committed_at 고정. test_rag_binding의 최초 동시 저장20개·중단 롤백·동일 ID 재저장 | 완료 |
| 저장·검색·HTTP·Spring/웹 과거 라우팅 | 실제 브라우저16개, G2 설정/워커 재시작 후 G1 두 종목 문서 조회. Spring은 저장 snapshot만 전달 | 로컬 완료 |
| 기존 snapshot 이관 | bind-snapshot 기본 검증/명시apply, 기존 observed context/hash/receipt 일치, 재실행 멱등·충돌/재구성 거부. 유지보수 토론 상태 보존 | 완료 |
| 미래 색인/reconstructed 우회 금지 | future publication/receipt 변조·누락503, unbound503, 원본 Fact200. 불변 연결 트리거 | 완료 |
| Fact 검증·판정 봉인·정규식 분류 제거 유지 | 워커647개 전체 통과/외부 Spring5개 생략, 추가 binding6개, Spring RAG8+HTTP2, 명시 search/facts 웹 경로 | 확인한 범위 통과 |
| 재시작·교체·복구 | 원본 receipt 복원·SQLite DB3개/파일19개 복원, PostgreSQL 전체 dump/restore(21테이블·3시퀀스·36trigger·제약/인덱스/컬럼), 재시작8개 동일 응답 | 로컬 완료 |
| 운영 설정·점검·절차 | check-generation/check-bindings, PostgreSQL 의존성 포함 Dockerfile, opt-in compose.rag.yml 기본 비활성, runbook에 교체/복원/권한/롤백 경계 | 구현·문서 완료, 실제 컨테이너 기동 미검증 |
| 제한된 실행 계정 | 새 테스트 계정에 SELECT/INSERT·시퀀스권한만 부여, 실제 문서/Fact2개 동일, UPDATE/DELETE/TRUNCATE/CREATE 거부, 계정 제거 | 로컬 완료, 운영 TLS/IAM/ACL 미검증 |
| 다종목 연동/동시성 | 두 종목 실제 HTTP/웹, 제한 동시1/4/8 총192개 동일 응답 | fixture 범위 완료 |
| 다종목 실제 검색 품질 | 005930 수집본+000660 모의본, 문서/벡터 fixture. 기존 평가셋 human_reviewed=false, 사용자 확인상 검수 corpus 없음 | 미완료, 사람 검수 필요 |
| 운영 규모 지연·부하·복원 환경 | 작은 TestClient/로컬 DB 측정이며 Spring 네트워크 부하·지속부하·Docker·클라우드 환경 없음 | 미완료 |
| 금지 작업 제외 | 외부 모델/임베딩0, S3연결0, 실서비스배포0. 백업 클라이언트만 Ubuntu 서명 패키지 경로에서 다운로드 | 준수 |

## 재현 근거

- [색인 교체·실제 브라우저](evaluations/rag-rollover-live.md): scripts/rag-rollover-prepare.py, web/tests/rag-multistock-live.mjs.
- [SQLite 복원·제한 동시성](evaluations/rag-recovery-load-local.md): scripts/rag-recovery-drill.py, scripts/rag-load-probe.py.
- [PostgreSQL 복원·제한 계정](evaluations/rag-recovery-postgres.md): scripts/rag-postgres-recovery.py.
- [운영 절차](RAG-PUBLICATION-RUNBOOK.md): 게시→준비 점검→최초 snapshot 고정, legacy 이관, 전체 대응 백업/복구.

## 남은 완료 조건

1. 실제 문서의 출처/관측 시점/사용 범위를 확보하고, 사람이 검수한 다종목 corpus와 독립 평가셋을 만든다.
   계획의 사람 검수40~60사례·30종목 확대 가능성은 기존2종목 fixture로 충족되지 않는다. 에이전트 작성 자료를
   사람 검수 자료로 표시하지 않는다. 담당자와 판단 기준을 정한 후 품질 평가·채택 여부를 결정한다.
2. Docker 실행 가능한 검증 환경에서 이미지/compose를 실제 기동하고, 배포 대상의 제한 계정·TLS/IAM·extension과
   백업 저장소 복원을 검증한다. 로컬 no-owner/no-acl 복원은 운영 권한 복원을 대신하지 않는다.
3. 운영 corpus 크기·동시 사용자·허용 지연을 먼저 정하고 Spring/네트워크를 포함한 부하와 복원을 측정한다.
   현재 관측치를 임의의 SLA나 RTO로 채택하지 않는다.

이 조건이 충족되기 전 운영 품질 승인·배포 완료로 표시하지 않는다. 실제 운영 배포와 S3 연결, 외부 모델 호출은
원 요청의 제외 범위다. 여기서의 미완료는 이 제외 범위를 실행하겠다는 의미가 아니다.

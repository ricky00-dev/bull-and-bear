# PostgreSQL 전체 DB와 로컬 파일 복원 검증

2026-11-02. [기계 판독 결과](rag-recovery-postgres.json). 실제 운영 DB·실서비스 배포·S3·외부 모델 호출은 사용하지 않았다.

## 실행과 결과

보존한 rollover fixture를 새 전용 DB `rag_restore_v3_source`로 이관했다. PostgreSQL16.4/pgvector를 사용하며 원본
snapshot·최초 generation 연결·receipt·context를 보존했다. 기존 source DB를 덮어쓰거나 삭제하지 않았다.

Windows 번들에 pg_dump/pg_restore가 없어 Ubuntu 서명 패키지 인덱스로 PostgreSQL16 클라이언트를 작업 데이터 경로에
다운로드·압축 해제했다. 시스템 패키지 설치나 sudo는 사용하지 않았다. 처음 기존 apt 인덱스의16.10 경로는404였으며,
별도 로컬 인덱스를 갱신해16.15 클라이언트를 받았다. 도구 다운로드와 검색/모델 네트워크 호출을 구분한다.

`pg_dump --format=custom --no-owner --no-acl`로 전체 DB를 저장하고, 새 빈 DB `rag_restore_v3_restored`에
`pg_restore --exit-on-error`로 복원했다(최종 DB는 `rag_restore_v3_restored`). dump SHA-256은 JSON에 기록했다.
dump 전후 원본 내용도 동일함을 확인했다.

- rag/public 테이블21개의 행 수·JSON 내용 해시, identity 시퀀스3개의 값/is_called, trigger36개,
  제약조건64개·인덱스36개·컬럼141개 정의, extension 버전이 복원 전과 일치했다.
- archive, contexts, searches, generations, embedding cache·원장·vector generation과 실제 pgvector 행을 포함한다.
- 벡터2개는 고정 벡터를 반환하는 fixture provider로 생성했다. 외부 모델 호출은0이며 검색 품질 평가 자료가 아니다.
- HTTP 저장소/원본 색인·receipt·로컬 객체 파일을 대응하는 새 경로에 복원하고 파일/SQLite 논리 해시를 검증했다.
- PostgreSQL archive/context backend로 실제 앱을 두 번 시작하여 두 종목 문서/Fact8개 응답을 기존 브라우저 결과와 전체 비교했다.
  context ID까지 동일했고 G2 설정에도 기존 스냅샷은 G1을 사용했다.
- 기존 context 행은 동일하며 검색 감사만10건 늘었다(재시작 검사8개+제한 계정2개). 복원 시퀀스의 신규 쓰기도 검사했다.
- 복원 DB에서 context UPDATE는 불변 trigger가 거부했다.
- 새 임시 LOGIN 계정에 rag schema USAGE, 테이블 SELECT/INSERT, 시퀀스 USAGE/SELECT만 부여했다. 실제 문서/Fact
  응답이 기존 값과 일치했고 감사도 저장됐다. UPDATE/DELETE/TRUNCATE/CREATE는 권한 거부였다. 검증 후 권한과 임시 계정은 제거했다.

첫 비교는 information_schema.sequences가 identity 시퀀스를 제외해0개만 검사한 한계가 있었다. pg_class로 수정하고
시퀀스가 비어 있으면 실패하도록 보강한 뒤 새 DB에서 재실행했다. 최종 결과는 그 보강과 제한 계정 검사를 모두 포함한다.
dump 약0.915초/restore 약0.794초는 약70KB dump와 작은 fixture의 관측값이다. 운영 RTO·처리량 보장이 아니다.
검증 후 모든 앱/전용 PostgreSQL을 종료하고 DB와 파일을 보존했다.

## 재현과 제한

스크립트 `scripts/rag-postgres-recovery.py`는 localhost15439/rag_test 전용 cluster와 `rag_restore_`로 시작하는 새 DB만
사용한다. DB 이름이나 출력 경로가 이미 있으면 거부하며 기존 DB 삭제/교체 옵션이 없다. 모델 runner/시장 접근은 금지했다.
Python 외부 소켓은 차단했고 WSL 클라이언트는 명시된 loopback DB만 연결했다.

worktree 루트에서 PYTHONPATH=ai-worker/src, PYTHON_DOTENV_DISABLED=1을 지정한다. 전용 PostgreSQL을 먼저 시작한다.

```sh
python scripts/rag-postgres-recovery.py ai-worker/data/rag-rollover-e2e ai-worker/data/new-pg-recovery \
  --client-dir ai-worker/data/pg-client-tools --database-prefix rag_restore_new \
  --baseline docs/evaluations/rag-rollover-live.json --report recovery-postgres.json
```

이 검증은 정지된 writer·로컬 trust·동일 서버 extension이라는 조건이다. dump/restore는 로컬 관리자 역할로 수행했고
별도로 제한된 실행 계정을 확인했다. 역할/ACL 자체는 dump에 포함하지 않았으며 운영 TLS/IAM, 운영 역할 재설정,
관리형 DB extension 제공 여부, 클라우드 스토리지 복원, 온라인 일관 백업은
미검증이다. 두 종목 중000660은 모의 저장본이며 문서도 fixture다. Docker 이미지/compose 기동, 운영 부하 및 사람 검수
corpus에 기반한 검색 품질 승인을 대신하지 않는다.

# 공통·단기 RAG 구현 근거 조사

2026-10-30. 조사 세션 `01a18be8-d9cd-7f93-baab-1f89702fabe7`을 구현 세션과 분리해
공식 문서·논문·GitHub 원문을 확인했다. 추가 독립 검토 세션 생성은 자동 승인 정책으로
차단되어 코드 검토·통합 검증은 구현 세션에서 수행했다. 아래 권고는 자료의 사실과 구분한다.

## 1. BM25와 후보 제한

- 확인: FTS5 BM25는 전체 FTS 테이블의 문서 수·평균 길이·구문별 문서 빈도를 사용한다.
  일반 `WHERE generation_id=...`는 이 통계를 세대별로 분리하지 않는다.
  [SQLite FTS5 문서](https://www.sqlite.org/fts5.html#the_bm25_function),
  [SQLite BM25 구현](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_aux.c).
- 적용: 세대마다 별도 읽기 전용 SQLite 파일, 고정 corpus, 파일 SHA256·manifest 검증.
  SQLite/인덱스/정규화 버전을 manifest에 기록한다. 다른 세대 자료 추가 뒤 점수·묶음 불변 회귀를 둔다.
- 확인: WHERE가 필터링한 결과에 LIMIT가 적용된다. 전체 상위 20개를 먼저 자른 뒤
  시장·시점 조건을 걸면 적격 문서가 누락될 수 있다. 물리적 쿼리 실행 순서 보장은 아니다.
  [SQLite SELECT](https://www.sqlite.org/lang_select.html).
- 적용: 당시 활성 revision·검수·유효 기간·시장·종목을 통과한 rowid만 SELECT에 제공하고
  경로별 20개 LIMIT. 고정 corpus 통계는 유지한다. 적합성(종목 지정→KR/KOSPI→global),
  BM25 오름차순, chunk_id 순으로 정렬한다. 검수된 출처 간 우선순위는 동일하게 두고 감사에 명시한다.
- 한계: 세대 간 BM25 원점수는 같은 척도로 비교하지 않는다. 후보 20개는 실행 비용 20행을 뜻하지 않는다.

## 2. 한국어 토큰화

- 확인: unicode61은 문자·숫자 연속 구간을 토큰으로 만들며 한국어 형태소 분석이 아니다.
  조사 결합·복합명사·띄어쓰기 차이에 검색 누락이 생길 수 있다. Porter는 영어용이며
  trigram에도 짧은 검색어 제약이 있다.
  [토크나이저 문서](https://www.sqlite.org/fts5.html#unicode61_tokenizer),
  [토크나이저 구현](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_tokenize.c).
- 적용: 문서와 질의에 NFC 정규화, PER/PBR/ROE/변동성/실적의 작은 고정 별칭 사전.
  질문은 종목명·티커·Fact ID/개념 라벨과 7거래일 KOSPI 목표에서 결정론적으로 만든다.
  뉴스 본문이나 매수·매도 결론으로 질의를 만들지 않는다.
- 보류: 형태소 분석기·벡터·n-gram은 이 변경에 추가하지 않았다. 한국어 자연 질문 정답 집합에서
  Recall@K/MRR과 오탐을 측정하기 전 현재 fixture를 운영 검색 품질로 일반화하지 않는다.
  현재 Snapshot에 업종 필드가 없으므로 업종을 추정해 넣지 않는다.

## 3. 1초 제한과 취소

- 확인: Future timeout은 대기 시간 제한이며 실행 중 스레드의 강제 종료가 아니다.
  executor 종료가 작업 완료를 기다릴 수도 있다.
  [Python futures](https://docs.python.org/3.13/library/concurrent.futures.html),
  [CPython thread executor](https://github.com/python/cpython/blob/3.13/Lib/concurrent/futures/thread.py).
- 확인: SQLite progress handler는 VM 명령 수 기준의 협력적 중단이다. interrupt도
  가장 빠른 가능한 시점에 중단하며 연결 종료와의 경합에 주의해야 한다.
  SQLite connection timeout은 잠금 대기 한도다.
  [progress handler](https://www.sqlite.org/c3ref/progress_handler.html),
  [interrupt](https://www.sqlite.org/c3ref/interrupt.html),
  [Python sqlite3](https://docs.python.org/3.13/library/sqlite3.html).
- 적용: monotonic deadline, SQL progress handler, 짧은 잠금 대기, 단계별 deadline 검사,
  최대 4개의 daemon reader, 호출자 1초 대기 제한, 늦은 결과 폐기. 검색 스레드는 결과 저장을 하지 않는다.
  컨텍스트/검색 감사 저장이 실패하면 성공을 반환하지 않는다.
- 한계: OS 파일 I/O의 강제 중단·정확한 실시간 1.000초 반환 보장은 아니다. 검색 시간과
  저장을 포함한 호출 시간을 따로 측정한다. 감사 저장은 검색 한도 밖이며 SQLite 잠금 대기는 1초다.
  자원 실행 자체를 강제 종료해야 한다면 프로세스 격리와 종료·복구 설계가 별도로 필요하다.

## 4. 검색·생성·예측 평가의 분리

- 확인: RAGAS/ARES는 문맥 관련성·답변 충실성·관련성 같은 RAG 품질을 평가한다.
  금융 예측 성과를 증명하지 않는다. ARES의 prediction-powered inference도 금융 예측 지표가 아니다.
  [RAGAS](https://arxiv.org/abs/2309.15217), [ARES](https://arxiv.org/abs/2311.09476),
  [ARES 코드](https://github.com/stanford-futuredata/ARES).
- 적용: 검색 정답 fixture와 시점/원문 추적 검증, 실제 저장층을 사용하는 HTTP/benchmark 연결,
  지연·완료율을 기록한다. 생성기는 fixture이고 cost_usd/accuracy는 null이다.
  RAGAS/ARES 패키지·추가 LLM 판정기는 설치하지 않는다.
- 후속: 실제 모델·검수된 운영 corpus·실제 입력 여유·가격표를 고정한 작은 비교가 필요하다.
  7거래일 KOSPI 초과수익 본판정, 3거래일 보조와 날짜별 운영 토론 재사용은 유지한다.
- 시간순 분리와 반복 실험 선택에 따른 과적합도 별개로 고려해야 한다.
  [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html),
  [백테스트 과적합 논문](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
  본 서비스의 교육용 상대수익 판정을 거래 수익·슬리피지 실험으로 바꾸지는 않는다.

GitHub 링크는 조사 시 확인한 원문 위치다. 외부 master의 영구 불변 스냅샷으로 주장하지 않는다.
상세 실제 검증 결과·실행 방법은 [검색 구현 평가](worker-rag-retrieval.md)에 기록한다.

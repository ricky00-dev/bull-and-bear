# RAG 자료 입력·검증 절차 v1

> 이전 워커의 설계·검증 기록이다. 2026-11-10에 워커 RAG 구현을 제거했으므로 아래 명령과 배포 설정은 당시 리비전에서만 적용된다.

2026-11-01. 현재 구현인 `rag/corpus.py`, `RagStore`, `GenerationIndex`, `Retriever`를 사용한다.
출처 없는 PDF 대량 투입이나 새 벡터 DB 도입에 앞서 출처·검수·시점이 연결된 작은 corpus로 검증한다.
이 문서의 corpus 입력 절차는 SQLite FTS5/BM25를 사용하며 임베딩 API를 호출하지 않는다.
선택적 PostgreSQL·pgvector·S3 설정과 평가 명령은 [RAG 실행 안내](RAG-OPERATIONS.md), 게시·교체·복구는 [운영 절차](RAG-PUBLICATION-RUNBOOK.md)를 따른다.

## 넣는 자료와 넣지 않는 자료

| 종류 | 입력 방식 | 사용 범위 |
|---|---|---|
| 금융 개념·해석 한계 | 공식 교육자료를 확인한 한국어 자체 설명 JSON | 비공개 배경지식 |
| 연구 결과 | 연구 원문 확인 후 시장·표본·관측/예측 기간·한계가 붙은 문단 | 해당 조건의 가설 설명. 이번 seed에는 없음 |
| 최신 주가·실적 수치·뉴스·공시 | 기존 공급자→Snapshot Fact 경로 | 종목의 관측 근거/[E#] |
| 서비스의 7거래일/KOSPI 기준 | 계약·코드·프롬프트 | 검색에서 빠지면 안 되는 고정 정책 |

RAG 문장을 현재 종목의 사실로 승격하거나, 미국 교육 사례를 한국 7거래일 성과로 설명하지 않는다.
뉴스/공시 로컬 캡처는 `rag sync`로 아카이브할 수 있지만 현재 배경 색인은 knowledge/research만 받는다.
제목만 있는 공시를 본문으로 표시하지 않는다. 자동 웹 크롤링·수집 스케줄은 이번에 활성화하지 않았다.

## 입력 단위와 필수 항목

정식 예시는 `ai-worker/knowledge/common-short-v1.json`, 스키마는 `rag/corpus.py`다.

- 파일: UTF-8 JSON, `schema_version=knowledge-corpus-v1`, 고유 corpus_version.
- 출처: id, 공식 URL, 제목, 발행기관, 공개일(모르면 null), 실제 확인 시각.
- 설명: 고정 note id, 제목, 한국어 자체 설명, source_id, 원문 절/페이지 위치.
- 한 문단은 한 개념과 적용 조건/한계를 담고 기존 스키마의 최대1000자를 지킨다.
  PDF의 페이지 경계를 기계적으로 자르기보다 개념 단위를 우선하며, 표는 단위·기간을 함께 남긴다.
- 검색 태그: topics에 공식 용어·약어·통상적인 동의어, horizons에 common 또는 short.
  검색 점수를 맞추려고 테스트 문장을 그대로 태그로 추가하지 않는다.
- 적용 조건(applicability)과 한계(limitations)는 필수. 연구는 원문 자료형으로 별도 수집해야 하며
  이 간단한 editorial importer가 연구 표본 전체를 구조화해 준다고 가정하지 않는다.
- 작성일/검토일/관측일을 원문 발행일로 소급하지 않는다.

원문 전체를 복사한 자료와 출처를 참고해 작성한 설명을 구분한다. 현재 seed는 후자다.
AI 검토는 `review_kind=agent_source_review`, `human_reviewed=false`, `release_status=experimental`로 기록한다.
`--allow-agent-reviewed`는 실험 opt-in이며 사람 승인이나 운영 활성화가 아니다.
현재 Corpus 모델은 사람 검수 완료 패키지를 지원하지 않으므로, 운영 승인 기록/워크플로는 별도 보완 대상이다.

## 최초 seed: 이미 작성된 설명 6개

| 문단 | 근거 |
|---|---|
| PER 정의·영업이익률/보고 기간 | [SEC 재무제표 안내](https://www.sec.gov/investor/pubs/begfinstmtguide.htm) |
| 변동성과 방향 구분 | [Investor.gov 위험 안내](https://www.investor.gov/introduction-investing/investing-basics/what-risk) |
| 실적 발표와 기대·발표와 공시 시점 | [FINRA 실적 발표 안내](https://syndication.finra.org/content/what-earnings-season) |
| 과거 추세의 한계 | [FINRA 모멘텀 안내](https://syndication.finra.org/content/what-momentum-investing) |

위 4개 공식 페이지는 이번 작업에서도 열어 대조했다. 원문 전체의 불변 HTML 스냅샷을 새로
보관한 것은 아니며, 적재된 자체 설명과 metadata의 해시는 보관한다. 기존 작성/검토 날짜를 바꾸지 않았다.

## 실행

프로젝트 루트에서 설치된 Python 환경을 사용한다. 운영 데이터와 분리한 pilot 폴더를 사용한다.

```powershell
$env:PYTHONPATH = (Resolve-Path ai-worker/src).Path
python scripts/test-rag-corpus.py `
  --corpus ai-worker/knowledge/common-short-v1.json `
  --data-dir ai-worker/data/rag-corpus-pilot `
  --allow-agent-reviewed
```

실행기는 import→동일 작업 재import→현재 관측 시점의 generation 발행→실제 검색/재생→보고서 저장을 수행한다.
모델·시장 API 호출이 없다. JSON 검증은 쓰기 전에 수행한다. 기존 DB와 보고서를 삭제/덮어쓰지 않는다.
생성물은 다음과 같다.

- `data/rag-corpus-pilot/rag/rag.sqlite3`: 문서/버전/관측/검수/검색 이력.
- `rag/objects/`: 내용 해시로 고정한 자료.
- `rag/generations/<generation_id>/`: 읽기 전용 검색 색인과 발행 영수증.
- `reports/corpus-<고유값>.json`: 검증 결과와 generation/context ID.

generation ID는 보고서에서 선택한다. `.env`의 RAG 스위치를 자동으로 켜지 않는다.
기존 과거 snapshot의 시각을 오늘로 바꾸어 새 지식을 과거 자료인 것처럼 사용하지 않는다.
현재 발행 세대를 과거 판단에 넣으면 차단돼야 하며, 이번 테스트도 그 경계를 확인한다.

## 변경·검수·갱신 규칙

1. 같은 note id의 내용과 태그가 그대로면 기존 revision과 검수 상태를 재사용한다.
2. 내용/출처/태그가 바뀌면 새 revision이 생기며 기존 문단의 변경본은 proposed로 들어간다.
3. 변경된 문단은 원문 대조 후 해당 문단 수준에서 검수하고 새 generation을 발행한다.
   패키지를 재import하는 것만으로 거절 상태가 승인으로 돌아가면 안 된다.
4. 모델 입력에는 하나의 고정 generation에서 검색한 context만 사용하고 ID를 감사 기록에 남긴다.
5. 현재 검색 한도(common2/short3, 전체 배경 예산)를 유지한다. 배경을 늘려 통과율만 높이지 않는다.
6. 기초 설명은 변경 시 검수, 정기 출처 재확인은 월1회를 제안한다. 자동 예약은 아직 없다.
   최신 뉴스/공시 갱신은 이 배경 corpus와 분리해 공급자의 실제 공개/관측 시각을 따른다.

## 입력 검증 근거

상세: [실제 적재 검증](evaluations/rag-corpus-pilot.md).
직접 개념6/6, 표현 변형4/6이며 단기 배경은 무관 입력에도 반환될 수 있다.
따라서 임의 자연어 검색 품질이나 실제 Claude 답변 개선을 입증한 결과가 아니다.

이 보고서는 해당 corpus 버전의 입력 검증 기록이다. 현재 확장 조건은 [설계 방향](RAG-LONG-TERM.md),
후속 검색 평가와 운영 판단은 [평가 색인](evaluations/README.md)과 [준비 감사](RAG-READINESS-AUDIT.md)를 따른다.
RAG 유무의 실제 모델 비교는 같은 스냅샷·고정 세대·별도 명시된 호출 범위/예산으로 수행한다.

# 공통·단기 RAG 후속 구현·평가 기록

2026-10-30. 이관 `2f6af9f` → 검색 구현 `838f1ee`의 후속 작업이다.
독립 worktree `feat/worker-rag-retrieval`에서 총괄 세션과 검색 평가·예산·Spring 하위 세션으로 나누어
구현하고 서로 다른 담당자가 검토했다. 운영 기본 `BULLBEAR_RAG_ENABLED=false`를 유지한다.

## 기능과 조사 기록

| 작업 | 구현·평가 | 별도 기록 |
|---|---|---|
| 실제 Spring 연결 | 격리 PostgreSQL/Flyway/Spring/HTTP 워커, 판정 봉인·공개·당일 재사용·3일 보조/7일 본판정 | [Spring 통합](worker-spring-integration.md) |
| 검색 평가 실행기 | 실제 저장→세대→검색→재생, 실패와 empty 분리, recall/MRR/선택 precision·분모 | [검색 품질](worker-rag-search-quality.md) |
| 출처 연결 지식 | SEC/FINRA 공식 자료를 참조한 자체 한국어 설명 common 3/short 3개, 실험용 AI 검수 표시 | [독립 내용 검토](worker-rag-editorial-quality.md) |
| 호출·금액 예산 | gpt-5-mini 공식 가격/한도, 영속 승인 원장, 호출 전 최악 비용 예약·실제 사용량 정산 | [모델 예산](worker-model-budget.md) |
| 비교 CLI | 동일 snapshot의 none/common_short × single/debate, 기존 단일/토론 CLI 유지 | [비교 사용법](worker-rag-comparison-cli.md) |

공식 출처의 주장, 자체 적용 해석, synthetic 검사 결과를 각 문서에서 구분했다.
기존 SQLite/BM25·시점·문단 검색 논문/GitHub 조사는 [검색 조사](worker-rag-retrieval-research.md)에 있다.
위 연구와 fixture의 성공을 단기 주가 예측 성과로 해석하지 않는다.
검토기 반려와 선택 precision의 해석은 [LLM judge 논문·Ragas 후속 조사](worker-rag-evaluation-research.md)에
별도로 정리했다.

## 실험용 지식의 적재·시간 의미

`ai-worker/knowledge/common-short-v1.json`은 공개 원문 복제나 시장 데이터 덤프가 아니라 이 작업에서
작성한 6개 짧은 한국어 설명과 출처 metadata다. 시장 Fact·공개 `[E#]`·새 근거 수에 추가하지 않는다.
사람 검수 완료를 주장하지 않고 `human_reviewed=false`, `release_status=experimental`을 저장한다.
명시적 `--allow-agent-reviewed` 없이는 적재하지 않는다.

```powershell
cd ai-worker
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m bullbear.rag.corpus knowledge/common-short-v1.json --data-dir data/knowledge-trial --allow-agent-reviewed
```

공식 원문의 오래된 발행일은 basis metadata로만 남긴다. 자체 설명의 발행 시각은 자체 작성 시각이며,
archive 최초 관측과 검수 주석은 실제 import 시각에 시작한다. 새로운 설명을 오래된 원문 발행일부터
알고 있던 지식처럼 과거 snapshot에 적용하지 않는다. 테스트의 재구성 시각은 별도 모드로 표시한다.
공식 원문 페이지의 불변 본문 캡처/해시는 아직 없고, URL·제목·절·명시 날짜를 직접 대조했다.

## 독립 검토에서 발견·보완한 사항

1. source 공개일이 관측일보다 미래인 입력을 거부하는 검증과 회귀를 추가했다.
2. 같은 corpus를 나중에 다시 적재하면 새로운 승인 주석 때문에 기존 세대가 empty로 바뀌던 문제를
   발견했다. 최초 주석만 원자적으로 생성하고 기존 승인·거절·제안을 보존하도록 고쳤다.
   또한 무관한 문단 변경이 전체 corpus hash를 바꾸어 거절 문단까지 새 chunk로 재승인하던 문제를
   고쳤다. note fingerprint는 해당 내용·basis·태그만 포함하고 패키지 정보는 관측에 보존한다.
   변경된 기존 문단은 proposed이며 별도 검수가 필요하다. 기존 형식의 거절도 보존한다.
3. 질의 128개를 사전순으로 자르면서 많은 뉴스·공시 식별자가 핵심 개념을 밀어내던 문제를 실제
   삼성전자 snapshot에서 확인했다. `filtered-bm25-v3-concept-priority`는 고정 목표→종목→구조화
   Fact의 별칭→기타 개념 순서로 제한한다. 뉴스·공시 제목과 opaque ID는 개념 질의에서 제외한다.
   수정 전 128개에서 PER·변동성·코스피 일부가 없었고, 수정 후 98개에 핵심어가 모두 보존됐다.
4. 정산이 거부된 공급자 응답을 어댑터가 집계하지 못했는데 `usage_status=reported`로 표시하던
   문제를 고쳤다. 수신 원문 usage/model과 어댑터 집계를 분리하고 미가격·정산 거절 상태를 명시한다.
5. 긴 비교 실행 도중 작업 파일이 바뀌면 각 조건이 다른 디스크 소스 hash를 읽던 문제를 보완했다.
   비교/배치 시작 identity를 공유하고 종료 시 변경을 기록한다. 변경 감지 시 비교 가능 판정을
   취소하되 실제 결과·비용은 남긴다. 실행 중 소스 편집을 피해야 하며 체크 사이 완전 원복이나
   진입 전 이미 로드된 모듈과 파일 차이까지 검출하는 메모리 코드 증명은 아니다.

모든 수정 전후의 실행 산출물은 로컬에 별도로 보존한다. 원문 시장 입력·키·.env·API 원시 응답·
SQLite·다운로드 런타임은 커밋하지 않는다.

## 운영 판정

작은 개발용 정답 집합에서의 검색 성공은 독립 자연 질문 평가가 아니다. 특히 short 경로는 고정된
7거래일 과제 배경을 반환하므로, 추가 개념에 무관한 입력에서도 일반 배경이 선택될 수 있다.
개념 관련성과 과제 공통 관련성을 별도로 판단해야 한다. 인간 검수, 실제 분포의 충분한 품질 표본,
모델 완료율·지연·비용의 운영 허용 기준, 실제 3/7거래일 결과는 현재 결과로 대체할 수 없다.

운영 활성화는 보류한다. P2 위험 검토 노드·LangGraph는 시작하지 않는다.

## 최종 로컬 회귀

Python 3.12.15, 기존 venv, 현재 worktree에서 `-o pythonpath=src`로 실행했다.
전체 **296 passed, 2 skipped, 35.21초**. 2 skipped는 별도 실행 환경을 요구하는 Spring 외부 테스트다.
문단 import/승인 보존, 한글 별칭과 큰 snapshot 질의 예산, 검색/재생, HTTP 경계, 비교 CLI,
가격·입력 한도·동시 승인 예약·사용량 실패 보고·실행 중 소스 변경 검사를 포함한다.
별도 실제 Spring/PostgreSQL/HTTP 실행은 **2 passed, 4.85초**였고 자식 프로세스·리스너 정리를
확인했다. 모델·시장·거래일은 fixture이며 이를 실제 예측 결과나 실제 모델 비용으로 계산하지 않는다.

실제 삼성전자 snapshot에서 v3 검색을 다시 실행해 98개 질의어, common 2/short 2문단을 얻었다.
PER·영업이익률·발표/공시 시각·모멘텀 한계가 선택됐고 원래 context의 SHA256은 그대로였다.
로컬 `data/rag-p1-live/preparation-v3.json`에 원래 context 보존과 새 context ID를 기록했다.
실제 모델 비교와 독립 오류 검토는 [실모델 파일럿](worker-rag-live-pilot.md)에 기록했다.
최초 v2 개발 중 진단은 0/4, 커밋된 v3의 최종 검증은 1/4 완료였다. 전체 61요청 사용량 가격
**$0.49036**(승인 $3), 미확정 0건. 최종 비교 중 소스 변경 없음·입력/배경 주입 경계는 확인했으나
운영 활성화와 예측 성과 검증은 통과하지 못했다. 기본 비활성 유지가 이번 운영 판정이다.

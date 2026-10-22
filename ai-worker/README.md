# 불앤베어 AI 워커

Spring API 서버가 호출하는 Python 서비스. API 계약은 [`../docs/worker-api.md`](../docs/worker-api.md).

매수 에이전트와 매도 에이전트가 실제 시장 데이터를 근거로 토론하고, 사용자가 먼저 판정한 뒤
AI 중재자의 판정과 실제 주가로 채점받으며 투자 근거 읽는 법을 배우는 모의투자 교육 서비스.

현재 단계: **핵심 파이프라인** (스냅샷 고정 → 3라운드 토론 → 근거 검증 → 중재자 판정, CLI).
모의체결 원장, 채점 스케줄러, 웹소켓, 웹 화면은 아직 없다.

## 시작하기

```bash
brew install uv            # 또는 https://docs.astral.sh/uv/
cd ai-worker
uv sync                    # Python 3.12 + 의존성 설치
cp .env.example .env       # ANTHROPIC_API_KEY, OPENDART_API_KEY, NAVER_CLIENT_ID/SECRET 입력

uv run bullbear universe           # 대상 30종목
uv run bullbear snapshot 삼성전자   # 데이터만 확인 (LLM 호출 없음)
uv run bullbear debate 005930      # 토론 → 내 판정 → 중재자 판정 공개
uv run bullbear replay <debate_id> # 기록 재생
uv run pytest                      # 테스트 (네트워크·API 키 불필요)
```

## 구조

```
src/bullbear/
  data/base.py        MarketDataSource 인터페이스 (시세·재무·발행주식수·공시)
  data/pykrx_dart.py  구현체: pykrx(시세) + OpenDART(재무·공시)
  data/kis.py         구현체: 한국투자증권 (미구현 자리)
  data/naver_news.py  NewsSource 구현체: 네이버 검색 API 뉴스 (제목·요약·링크만)
  snapshot.py         판단 시점 스냅샷. 모든 수치를 ID 붙은 Fact로 고정, 파생 지표 계산
  tools.py            에이전트 도구. 스냅샷에 묶여 있어 같은 시점 데이터만 반환
  verifier.py         근거 검증기 (결정론적). 근거 값을 원본과 대조해 반려
  agents.py           매수·매도 토론자, 중재자
  llm.py              Claude 호출: 스트리밍, 도구 루프, 구조화 출력, 거절 시 폴백
  debate.py           토론 진행: 3라운드, 검증 재시도, 추가 질문 라운드, 판정 봉인
  events.py           JSONL 이벤트 기록 (재현용, 덧붙이기만)
  cli.py
```

흐름:

1. `build_snapshot`이 데이터 소스에서 한 번 받아와 스냅샷을 고정한다. ID는 내용 해시라서 같은 데이터면 같은 ID다.
2. 매수 → 매도 순으로 주장, 반박, 최종 변론. 토론자는 도구로 스냅샷 Fact를 조회하고,
   발언을 `{claim, argument, evidence[{ref, source_id, value, interpretation}]}` 형식으로 낸다.
3. 검증기가 근거의 `source_id`와 `value`를 스냅샷과 대조한다. 틀리면 같은 대화에 피드백을 붙여
   최대 2번 다시 쓰게 한다.
4. 중재자가 기준표(관련성·중요도·반박·리스크 인식)와 검증 통계로 평가한다. 쟁점이 남았다고 보면
   추가 질문 라운드를 요청한다 (기본 최대 1회).
5. 중재자 판정은 봉인된 채 기록되고, 사용자 판정이 기록된 뒤에 공개된다.

## 데이터 소스 메모

- pykrx 일봉은 정상. KRX 정보데이터시스템 API(PER/PBR, 시가총액)는 2026-10 기준 빈 응답이다.
  그래서 밸류에이션은 `snapshot.py`에서 시세 × DART 발행주식수, DART 재무로 직접 계산하고 계산 입력을 `inputs`에 남긴다.
- PER은 당기순이익(연결, 비지배지분 포함) 기준이라 증권사 PER(지배주주 순이익)과 다를 수 있다.
- 시가총액은 보통주만 센다.
- 뉴스는 `NewsSource`로 따로 둔다. 네이버 검색 API로 최근 7일 기사 중 제목에 종목명이 있는 것만, 재전송 기사는 하나로 합쳐 최대 30건.
  스냅샷 생성 시각 이후 기사는 넣지 않는다. 본문은 가져오지 않는다 (저작권·약관).
- LG, SK처럼 이름이 짧은 종목은 관련 없는 기사가 섞인다. `naver_news.QUERY_OVERRIDES`로 보정한다.
- 새 공급자는 `MarketDataSource`를 구현하고 `cli.py`의 `_make_snapshot`에서 고르면 된다.

## 테스트

- 파이프라인 동작을 바꾸면 `tests/fakes.py`의 가짜 소스·에이전트로 테스트를 추가한다.

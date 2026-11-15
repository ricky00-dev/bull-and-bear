# HTTP 워커 실행 감사 검증

2026-10-30 · `feat/worker-run-audit` · 기준 develop `83247f2`

## 동작

새 HTTP 토론을 시작하면 `Settings.data_dir/audits/<debate_id>/manifest.json`을 먼저 만든다.
`running` 상태와 설정·코드·정책·프롬프트/스키마 해시를 저장한 뒤 스냅샷 생성과 모델 클라이언트 초기화를 진행한다.
스냅샷 전체, 원본 snapshot ID·payload SHA-256, `created_at`과 동일한 `decision_at`을 유료 호출 전에 기록한다.
기존 Fact 해시·날짜별 토론 재사용·HTTP/SSE 필드와 판정 봉인 책임은 바꾸지 않는다.

manifest에는 다음이 들어간다.

- 코드의 전체 commit SHA와 dirty 여부, 고정 정책 버전·정책 해시, prompts/semantic 소스 해시와 세 출력 스키마 해시.
- 선택한 토론자·중재자 모델과 effort, 추가 라운드 한도 및 매수 선공 조건.
- 스냅샷·클라이언트 생성·토론 단계별 시작/종료·소요 시간, 전체 소요 시간 및 `success/failure`.
- `LiveRunner`의 structured 호출별 토론자·중재자·의미 검토 역할, 이를 실행한 클라이언트 역할, 실제 사용한 system/messages/schema/tools 해시와 effort.
- 호출 시작 기록, 완료/실패 기록, 실제 응답 모델별 사용량 차이 및 역할별 누계, 전체 사용량.
- 확정/반려/라운드 진행 메타데이터와 최종 결과; 오류는 예외 종류만 기록.

같은 실행 디렉터리 안의 임시 파일을 flush/fsync한 뒤 원자적으로 교체한다.
호출 시작 기록 저장에 실패하면 다음 유료 호출을 시작하지 않는다.
클라이언트 하나를 만든 뒤 다음 클라이언트 생성에 실패한 경우에도 첫 클라이언트를 닫고 실패 manifest를 보존한다.
서로 다른 토론은 서로 다른 디렉터리와 manifest를 사용한다.

## 민감정보와 공개 경계

환경 전체·인증 헤더·원시 예외 메시지·원시 스트리밍 토큰·대화 프롬프트 본문은 감사 기록에 넣지 않는다.
알려진 인증 환경변수와 설정의 키 값, 일반적인 키/토큰 표현을 문자열에서 가린다.
스냅샷의 선택적 공급자 오류 경고에 기존 코드가 붙인 예외 상세도 감사 사본에서는 생략한다.
이 경우 `redactions_applied`와 `snapshot_warning_details_omitted`를 표시한다.
원본 스냅샷 ID와 원본 payload 해시는 유지하지만 가려진 감사 사본의 내용으로 그 해시를 다시 계산할 수는 없다.
시장 스냅샷 저장소·기존 토론 JSONL을 수정하거나 새 외부 조회 경로를 추가하지 않는다.

감사는 공개 SSE에 새 이벤트·필드를 추가하지 않는다.
검증된 발언만 공개하는 기존 필터와 Spring의 중재자 판정 봉인은 그대로다.
`runner_factory` 테스트 fixture는 그대로 동작하며 `llm_call_observation=false`로 세부 모델 호출을 관측하지 않았음을 명시한다.

## 검증

루트의 기존 Python 가상환경 실행 파일을 사용하되, 작업 디렉터리는 이 worktree의 `ai-worker`,
`PYTHONPATH`는 이 worktree의 `ai-worker/src`로 지정했다.
실제 import 경로가 이 worktree의 audit.py임을 확인했고 코드 revision은 기준 commit의 전체 SHA로 읽혔다.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& 'C:\Users\weun2\OneDrive\문서\ChatGPT\BAB\ai-worker\.venv\Scripts\python.exe' -m pytest -q
```

회귀 시나리오는 다음과 같다.

- 성공 스냅샷의 전체 내용·정확한 ID/시각·원본 해시·코드/정책 해시 보존과 기존 HTTP/SSE 필드 유지.
- 스냅샷 실패, runner factory 실패, 두 번째 모델 클라이언트 생성 실패 및 첫 클라이언트 정리.
- 검증 재시도 소진 시 실패·반려 메타데이터·사용량 보존 및 미검증 발언 비공개.
- 서로 다른 종목의 동시 실행 격리와 멱등 요청의 추가 감사 실행 방지.
- `LiveRunner`의 6개 발언·중재·의미 검토 연결, fallback 실제 모델·역할별 사용량 및 호출 전 영속 기록.
- 호출 실패 후 이미 받은 사용량 보존, 알려진 키·인증 표현·원시 예외·원시 토큰 비기록.
- optional 공급자 오류의 경고 상세 제거 및 초기 fsync 실패 시 유료 runner 미시작.
- 사용량 수집 자체가 실패해도 원래 토론의 성공/실패를 확정하고 누락을 명시; cleanup 오류의 후속 기록 실패가 확정 결과를 바꾸지 않음.

타깃: `tests/test_run_audit.py tests/test_server.py` 20개 통과 후, 공급자 경고·사용량 수집·cleanup 저장 실패 회귀를 추가했다.
최종 전체: **106개 통과, 외부 Spring 통합 2개 건너뜀 (35.06초)**. `git diff --check` 통과.

## 확인하지 않은 범위와 한계

- 실제 키·유료 LLM·외부 시장 API 호출과 Docker/Spring/PostgreSQL 통합은 실행하지 않았다.
- Python 전체 테스트 중 외부 Spring 통합 2개는 실행 환경 미설정으로 건너뛴다.
- 기록은 HTTP `LiveRunner`에 연결했다; 기존 CLI/선공 비교 실행기는 이번 변경 범위가 아니다.
- structured 호출 하나 안의 공급자 도구 루프·SDK 내부 네트워크 재시도는 개별 요청으로 기록하지 않는다; 응답이 보고한 사용량을 논리 호출별로 누적한다.
- 응답을 받기 전 연결이 끊기거나 응답 뒤 로컬 저장 전에 종료되면 실제 청구량을 복구할 수 없다; 기록된 양은 관측한 응답 기준이다.
- runner의 최종 사용량 수집이 실패하면 관측된 호출 누계만 사용하고 `usage_complete=false` 및 예외 종류를 기록한다; 아무 호출도 관측하지 못한 fixture는 빈 calls를 반환한다.
- 프로세스 종료 시 마지막 manifest의 `running` 상태가 남을 수 있다; 실행 재개나 감사 파일의 자동 상태 보정은 구현하지 않았다.
- 파일 fsync와 원자적 교체를 사용하지만 저장장치·파일시스템의 전원 장애 내구성을 검증하지 않았다; 디스크 자체가 쓰기 불능이면 실패 상태조차 새로 저장하지 못할 수 있다.
- 기존 원본 스냅샷·토론 감사 JSONL의 보존 정책과 접근 통제는 이번 변경에서 바꾸지 않았다.

-- 3거래일 결과도 기록한다 (실험 보조 지표). 토론 하나에 기간별 한 줄.
alter table debate_outcomes drop constraint debate_outcomes_pkey;
alter table debate_outcomes add primary key (debate_id, horizon_days);

-- 실험 조건 B: 짝이 되는 토론과 같은 스냅샷으로 단일 에이전트가 바로 판정한다 (docs/experiment.md).
-- 사용자에게는 보이지 않고 AI 성적표 집계에만 쓴다.
create table single_verdicts (
    debate_id     uuid primary key references debates (id),
    worker_id     text,
    status        text          not null, -- RUNNING | COMPLETED | FAILED
    attempts      int           not null default 1,
    decision      text,
    confidence    numeric(4, 3),
    reasoning     text,
    payload       jsonb,
    cost_usd      numeric(10, 4),
    error         text,
    run_day       date          not null, -- 비용 상한을 셀 날 (KST)
    created_at    timestamptz   not null,
    completed_at  timestamptz
);

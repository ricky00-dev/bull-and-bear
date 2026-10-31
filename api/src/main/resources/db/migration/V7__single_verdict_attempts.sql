-- Keep every execution's cost/date, including unknown usage, across retries.
-- single_verdicts remains the latest-result projection used by the report.
create table single_verdict_attempts (
    debate_id uuid not null references single_verdicts(debate_id),
    attempt int not null,
    request_id text not null unique,
    worker_id text,
    status text not null,
    cost_usd numeric(10, 4),
    run_day date not null,
    created_at timestamptz not null,
    completed_at timestamptz,
    primary key (debate_id, attempt)
);
create index single_verdict_attempts_run_day_idx on single_verdict_attempts(run_day);

-- V6 retained only the latest attempt. Preserve that evidence verbatim;
-- earlier overwritten charges cannot be reconstructed from this table.
insert into single_verdict_attempts
    (debate_id, attempt, request_id, worker_id, status, cost_usd, run_day, created_at, completed_at)
select debate_id, attempts, 'single-' || debate_id::text || '-' || attempts::text,
       worker_id, status, cost_usd, run_day, created_at, completed_at
from single_verdicts;

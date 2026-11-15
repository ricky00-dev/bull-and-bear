-- 채점 결과 상세. 거래일 달력을 따로 두지 않고, 판정 기준일 이후 실제 시세가 있는 날을 세어 N거래일째로 채점한다.
-- scheduled_date는 주말만 뺀 예상일 (화면 안내용). 실제 채점일은 scored_trade_date.
alter table judgment_scores
    add column base_index         numeric(12, 2),
    add column stock_close        numeric(18, 2),
    add column index_close        numeric(12, 2),
    add column scored_trade_date  date,
    add column created_at         timestamptz not null default now();

create index judgment_scores_pending_idx on judgment_scores (status) where status = 'PENDING';

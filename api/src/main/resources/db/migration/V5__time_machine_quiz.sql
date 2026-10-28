-- 토론별 실제 결과 (7거래일, 코스피 대비). 사용자 판정과 상관없이 토론 하나에 한 줄.
-- 타임머신 퀴즈 문제와 실험 집계(토론 vs 단일)의 기준이 된다.
create table debate_outcomes (
    debate_id          uuid primary key references debates (id),
    horizon_days       int           not null,
    scored_trade_date  date          not null,
    stock_return       numeric(9, 4) not null, -- %
    index_return       numeric(9, 4) not null, -- %
    excess_return      numeric(9, 4) not null, -- %p
    created_at         timestamptz   not null default now()
);

-- 타임머신 퀴즈. 실제 판정 통계(judgments)와 섞지 않는다.
create table quiz_rounds (
    id          uuid primary key,
    user_id     uuid        not null references users (id),
    created_at  timestamptz not null
);
create index quiz_rounds_user_idx on quiz_rounds (user_id);

create table quiz_questions (
    round_id       uuid       not null references quiz_rounds (id),
    idx            int        not null, -- 0부터
    debate_id      uuid       not null references debates (id),
    decision       varchar(4),          -- 답하기 전엔 null
    user_hit       boolean,
    moderator_hit  boolean,
    answered_at    timestamptz,
    primary key (round_id, idx)
);
create index quiz_questions_debate_idx on quiz_questions (debate_id);

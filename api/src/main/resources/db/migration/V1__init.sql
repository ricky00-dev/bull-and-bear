-- 사용자. 첫 접속 시 게스트로 만들고, 카카오 가입 시 같은 행을 승격한다.
create table users (
    id          uuid primary key,
    guest       boolean      not null,
    token_hash  varchar(64)  not null unique, -- 접근 토큰의 SHA-256. 원문은 저장하지 않는다
    nickname    varchar(40),
    kakao_id    varchar(64) unique,
    created_at  timestamptz  not null
);

-- 토론. 같은 종목·같은 날 토론은 재사용한다.
create table debates (
    id                uuid primary key,
    ticker            varchar(6)   not null,
    stock_name        varchar(100) not null,
    status            varchar(16)  not null, -- RUNNING, COMPLETED, FAILED
    worker_debate_id  varchar(100),
    snapshot_id       varchar(100),
    trade_date        date,                  -- 스냅샷 기준일
    base_price        numeric(18, 2),        -- 스냅샷 종가 = 채점 기준 가격
    requested_by      uuid references users (id),
    last_event_seq    bigint       not null default 0,
    created_at        timestamptz  not null,
    completed_at      timestamptz
);
create index debates_ticker_created_idx on debates (ticker, created_at desc);

-- 워커에서 받은 이벤트 원본. 재생·재연결·감사용. 고치지 않고 덧붙이기만 한다.
create table debate_events (
    id          bigserial primary key,
    debate_id   uuid        not null references debates (id),
    seq         bigint      not null,
    type        varchar(40) not null,
    payload     jsonb       not null,
    created_at  timestamptz not null,
    unique (debate_id, seq)
);

-- 중재자 판정. 사용자가 판정을 내기 전에는 API로 내보내지 않는다.
create table moderator_verdicts (
    debate_id   uuid primary key references debates (id),
    decision    varchar(4)    not null, -- BUY, HOLD, SELL
    confidence  numeric(3, 2) not null,
    reasoning   text          not null,
    payload     jsonb         not null, -- 기준표 점수, 결정적 근거 등 원본
    created_at  timestamptz   not null
);

-- 사용자 판정. 한 사용자는 한 토론에 한 번만 판정한다.
create table judgments (
    id              uuid primary key,
    user_id         uuid        not null references users (id),
    debate_id       uuid        not null references debates (id),
    decision        varchar(4)  not null,
    confidence      smallint    not null check (confidence between 50 and 100),
    evidence_picks  text[]      not null, -- 가장 설득력 있던 근거의 Fact ID (최대 2개)
    memo            varchar(200),
    created_at      timestamptz not null,
    unique (user_id, debate_id)
);

-- 채점 (3·7거래일 뒤). 스케줄러는 다음 단계에서 구현한다.
create table judgment_scores (
    id              bigserial primary key,
    judgment_id     uuid        not null references judgments (id),
    horizon_days    smallint    not null,
    scheduled_date  date        not null,
    status          varchar(16) not null, -- PENDING, SCORED
    stock_return    numeric(8, 4),
    index_return    numeric(8, 4),
    excess_return   numeric(8, 4),
    user_hit        boolean,
    moderator_hit   boolean,
    scored_at       timestamptz,
    unique (judgment_id, horizon_days)
);

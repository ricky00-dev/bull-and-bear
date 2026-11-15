-- 비용 상한과 중복 방지.

-- 토론 출처. USER: 사용자가 시작, SCHEDULED: 전향 운용 스케줄러. 비용 상한을 따로 건다.
alter table debates add column origin varchar(16) not null default 'USER';

-- 토론을 만든 날 (KST). 같은 종목은 하루에 한 번만 토론한다.
alter table debates add column debate_day date;
update debates set debate_day = (created_at at time zone 'Asia/Seoul')::date;
alter table debates alter column debate_day set not null;

-- 실패한 토론이 남아 있어도 다시 시작할 수 있게 실패는 빼고 건다.
-- 동시에 두 요청이 와도 하나만 들어가고, 나머지는 먼저 들어간 토론을 재사용한다.
create unique index debates_one_per_day on debates (ticker, debate_day) where status <> 'FAILED';
create index debates_day_idx on debates (debate_day);

-- LLM 사용량. 워커가 debate_completed / debate_failed의 usage로 알려 준다.
alter table debates add column input_tokens bigint;
alter table debates add column output_tokens bigint;
alter table debates add column cost_usd numeric(10, 4);

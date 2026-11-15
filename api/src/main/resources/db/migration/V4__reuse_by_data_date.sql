-- 토론 재사용 기준을 "만든 날(KST)"에서 "데이터 기준일"로 바꾼다.
-- 장 마감 뒤 만든 토론은 다음 날 장 마감 전까지 같은 종가 데이터를 쓰므로 그대로 재사용할 수 있다.
-- (예: 10/22 16:40에 만든 10/22 종가 토론을 10/23 오전 사용자도 기다림 없이 본다)

-- 토론을 시작할 때 워커가 알려 준 최신 종가 날짜 (= 스냅샷 기준일)
alter table debates add column data_date date;

-- 기존 행: 스냅샷 기준일, 없으면 만든 날. 같은 종목·같은 기준일이 겹치면 먼저 만든 것만 그 날짜를 갖는다 (개발 DB용)
with ranked as (
    select id, coalesce(trade_date, debate_day) as d,
           row_number() over (partition by ticker, coalesce(trade_date, debate_day)
                              order by (status = 'FAILED'), created_at) as rn
    from debates
)
update debates set data_date = case when ranked.rn = 1 then ranked.d else debates.debate_day end
from ranked where ranked.id = debates.id;
alter table debates alter column data_date set not null;

drop index debates_one_per_day;
create unique index debates_one_per_data_date on debates (ticker, data_date) where status <> 'FAILED';

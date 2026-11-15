#!/usr/bin/env bash
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -c \"
select count(distinct t.fund_code) tracker_funds,
       count(distinct t.fund_code) filter (where q.symbol is not null) with_quote,
       count(distinct t.index_code) indices
from bp_index_tracker_fund t
left join (select distinct symbol from bp_index_quote_daily) q on q.symbol = t.fund_code\""
su - postgres -c "psql -d postgres -c \"
select symbol, adjust, count(*) from bp_index_quote_daily where symbol in ('510300','510310','159919') group by 1,2\""
su - postgres -c "psql -d postgres -c \"
select t.index_code, count(distinct t.fund_code) funds,
       count(distinct t.fund_code) filter (where q.symbol is not null) with_quote
from bp_index_tracker_fund t
left join (select distinct symbol from bp_index_quote_daily) q on q.symbol = t.fund_code
where t.index_code in ('000300','000905','000016') group by 1\""

#!/usr/bin/env bash
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -c \"
select count(distinct t.fund_code) total,
       count(distinct t.fund_code) filter (where q.symbol is not null) with_quote
from bp_index_tracker_fund t
left join (select distinct symbol from bp_index_quote_daily) q
  on q.symbol = regexp_replace(t.fund_code, '^(SH|SZ|OF)', '')\""
su - postgres -c "psql -d postgres -c \"
select count(*) from bp_index_tracker_fund where fund_code not like 'SH%' and fund_code not like 'SZ%'\""
su - postgres -c "psql -d postgres -c \"
select t.index_code, count(distinct t.fund_code) funds,
       count(distinct t.fund_code) filter (where q.symbol is not null) with_quote
from bp_index_tracker_fund t
left join (select distinct symbol from bp_index_quote_daily) q
  on q.symbol = regexp_replace(t.fund_code, '^(SH|SZ|OF)', '')
where t.index_code in ('000300','000905','000016') group by 1\""

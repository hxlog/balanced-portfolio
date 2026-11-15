select count(*) total,
       count(*) filter (where raw->>'intro' is not null and raw->>'intro' <> '') as with_intro
from bp_index_valuation_daily
where is_primary and trade_date = (select max(trade_date) from bp_index_valuation_daily where is_primary);
select index_code, left(raw->>'intro', 80) as intro_head
from bp_index_valuation_daily
where is_primary and trade_date = (select max(trade_date) from bp_index_valuation_daily where is_primary)
  and raw->>'intro' is not null and raw->>'intro' <> '' limit 3;
-- 行情最新日期分布（找死数据/滞后）
select last_date, count(*) idx from (
  select q.symbol, max(q.trade_date) last_date from bp_index_quote_daily q
  join bp_index_master m on m.index_code = q.symbol and m.is_active and m.is_tracked
  group by 1
) t group by 1 order by 1 desc limit 10;

-- 无任何行情的指数（按市场）
select m.market, count(*) n from bp_index_master m
where m.is_active and m.is_tracked
  and not exists (select 1 from bp_index_quote_daily q where q.symbol = m.index_code)
group by 1 order by 2 desc;

-- 52周位置为空的指数样例（前 12）
select m.index_code, m.name, m.market, m.index_type,
       (select count(*) from bp_index_quote_daily q where q.symbol = m.index_code and q.adjust='bfq') as quote_rows
from bp_index_master m
where m.is_active and m.is_tracked
  and not exists (select 1 from bp_index_quote_extremes e where e.symbol = m.index_code and e.close_52w_ago is not null)
order by quote_rows desc limit 12;

-- 分位为空但估值有值的指数（pe 5y）样例
select m.index_code, m.name, (select count(*) from bp_index_valuation_series s where s.index_code=m.index_code and s.metric='pe_ttm') as pe_series
from bp_index_master m
where m.is_active and m.is_tracked
  and exists (select 1 from bp_index_percentile p where p.index_code=m.index_code and p.metric='pe_ttm' and p.window_key='5y' and p.as_of_date=(select max(as_of_date) from bp_index_percentile) and p.pct is null)
limit 8;
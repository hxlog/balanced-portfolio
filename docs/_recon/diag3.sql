-- 直接测试行情 LATERAL
select (array_agg(t.close order by t.trade_date desc))[1] as close_last,
       count(*) as obs,
       max(t.trade_date) as last_date
from (
    select q.close, q.trade_date from bp_index_quote_daily q
    where q.symbol = '930598' and q.adjust = 'bfq' and q.trade_date >= current_date - 400
) t;
-- 同 symbol 在 master 中是否存在
select index_code, name, market from bp_index_master where index_code = '930598';
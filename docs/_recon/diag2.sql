select q.symbol, q.source, q.adjust, count(*), max(q.trade_date)
from bp_index_quote_daily q
where q.symbol in ('930598','930601','930604')
group by 1,2,3;
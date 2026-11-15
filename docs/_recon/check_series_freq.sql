select index_code, metric, count(*) rows, min(trade_date), max(trade_date)
from bp_index_valuation_series
where index_code in ('000001','000300','930641') and metric = 'pe_ttm' and trade_date >= date '2025-11-14'
group by 1,2 order by 1;
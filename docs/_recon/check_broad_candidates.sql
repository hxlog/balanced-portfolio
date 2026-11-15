select m.index_code, m.name, m.index_type,
       count(d.trade_date) filter (where d.is_primary and d.pe_ttm is not null) as pe_points,
       min(d.trade_date) filter (where d.is_primary) as start_date,
       max(d.trade_date) filter (where d.is_primary) as end_date
from bp_index_master m
left join bp_index_valuation_daily d on d.index_code = m.index_code
where m.index_code in ('000001','000016','000300','000510','000852','000905','000906','000985','000922','000688','399006','000932','000933')
group by 1,2,3 order by 1;
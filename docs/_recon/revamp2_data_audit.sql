-- 1) 52 周位置/股息率分位为空的原因分布
select '52w_pos_empty' as metric, count(*) as n from bp_index_master m
where m.is_active and m.is_tracked and not exists (
  select 1 from bp_index_quote_extremes e where e.symbol = m.index_code and e.close_52w_ago is not null);

-- 2) 估值滞后（主口径最大日期分布）
select v.max_date, count(*) as idx_count from (
  select index_code, max(trade_date) as max_date from bp_index_valuation_daily where is_primary group by 1
) v group by 1 order by 1 desc limit 8;

-- 3) 各指标分位覆盖（最新 as_of）
select metric, window_key, count(*) filter (where pct is not null) as with_pct,
       count(*) filter (where pct is null) as null_pct, max(sample_size) as max_sample
from bp_index_percentile
where as_of_date = (select max(as_of_date) from bp_index_percentile)
group by 1,2 order by 1,2;

-- 4) 指数主数据基础信息覆盖
select count(*) total, count(base_date) base_date_ok, count(base_point) base_point_ok,
       count(nullif(btrim(coalesce(income_method,'')),'')) income_method_ok,
       count(nullif(btrim(coalesce(weight_method,'')),'')) weight_method_ok,
       count(nullif(btrim(coalesce(intro,'')),'')) intro_ok
from bp_index_master where is_active and is_tracked;

-- 5) 跟踪基金数据字段与规模覆盖
select count(*) rows, count(aum) aum_ok, count(distinct fund_code) funds
from bp_index_tracker_fund;

-- 6) roe/ps 序列是否存在
select metric, count(*) rows, count(distinct index_code) idx from bp_index_valuation_series
where metric in ('ps','ps_ttm','roe','roe_ttm') group by 1;

-- 7) 红利类指数（名称含红利/股息）及其跟踪基金规模
select m.index_code, m.name, m.index_type, m.industry,
       (select count(*) from bp_index_tracker_fund t where t.index_code = m.index_code) as fund_cnt,
       (select sum(aum) from bp_index_tracker_fund t where t.index_code = m.index_code) as aum_sum
from bp_index_master m
where m.is_active and m.is_tracked and (m.name like '%红利%' or m.name like '%股息%' or m.name like '%高股息%')
order by aum_sum desc nulls last limit 15;
-- 估值序列覆盖（按指标/指数数/起止）
select metric, count(distinct index_code) idx, min(trade_date) start, max(trade_date) end, count(*) rows
from bp_index_valuation_series group by metric order by metric;
-- 分位表窗口
select metric, window, count(*) rows from bp_index_percentile group by 1,2 order by 1,2;
-- 成分权重日期
select count(distinct index_code) idx, min(effective_date) start, max(effective_date) end, count(*) rows from bp_index_constituent;
-- 跟踪基金
select count(distinct index_code) idx, count(*) rows from bp_index_fund;
-- 指数简介字段非空
select count(*) total, count(*) filter (where raw->>'indexIntro' is not null and raw->>'indexIntro' <> '') with_intro from bp_index_valuation_daily where is_primary and trade_date = (select max(trade_date) from bp_index_valuation_daily where is_primary);
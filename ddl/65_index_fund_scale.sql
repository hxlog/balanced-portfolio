-- 65: 指数基金规模预计算表（ETF/联接基金最新规模合计）
-- 用途：指数列表新增「ETF/基金规模」列并按规模排序、红利指数图气泡大小；
-- 避免每次列表查询对 bp_index_tracker_fund 做 521 次 LATERAL 聚合。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_index_fund_scale (
    index_code text PRIMARY KEY REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    fund_count integer NOT NULL DEFAULT 0,
    aum_sum numeric(20, 2),
    as_of date,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_index_fund_scale IS
    '每个指数的跟踪基金数量与最新规模合计（元）；由每日任务刷新，API 只读';

TRUNCATE bp_index_fund_scale;

INSERT INTO bp_index_fund_scale (index_code, fund_count, aum_sum, as_of)
SELECT t.index_code,
       count(*) AS fund_count,
       sum(t.aum) AS aum_sum,
       max(t.trade_date) AS as_of
FROM bp_index_tracker_fund t
JOIN (
    SELECT index_code, max(trade_date) AS d
    FROM bp_index_tracker_fund
    GROUP BY index_code
) latest ON latest.index_code = t.index_code AND latest.d = t.trade_date
GROUP BY t.index_code;

COMMIT;

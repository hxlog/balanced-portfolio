-- 68: 基金净值历史 + 基金风险指标（年化收益/波动/最大回撤/跟踪误差/信息比率）
BEGIN;

CREATE TABLE IF NOT EXISTS bp_fund_nav_daily (
    fund_code text NOT NULL,
    trade_date date NOT NULL,
    nav numeric(16, 6),
    acc_nav numeric(16, 6),
    source text NOT NULL DEFAULT 'em_pingzhongdata',
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fund_code, trade_date)
);
COMMENT ON TABLE bp_fund_nav_daily IS '基金单位净值/累计净值日序列（天天基金 pingzhongdata），仅作风险指标计算';

CREATE TABLE IF NOT EXISTS bp_fund_risk (
    fund_code text PRIMARY KEY,
    as_of date,
    benchmark_code text,
    ret_1y numeric(10, 4),
    ret_3y_ann numeric(10, 4),
    ret_5y_ann numeric(10, 4),
    ytd numeric(10, 4),
    ann_vol_1y numeric(10, 4),
    max_dd_1y numeric(10, 4),
    tracking_error_1y numeric(10, 4),
    info_ratio_1y numeric(10, 4),
    n_obs integer,
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bp_fund_risk IS '基金风险指标（基于净值序列，vs 主跟踪指数）；收益为百分数点';

COMMIT;

-- 66: 基金全字段（经理/类型/费率/成立日/规模）+ 基金业绩表 + 指数行情健康表
BEGIN;

ALTER TABLE bp_fund_master
    ADD COLUMN IF NOT EXISTS manager text,
    ADD COLUMN IF NOT EXISTS fund_type text,
    ADD COLUMN IF NOT EXISTS management_fee numeric(6, 3),
    ADD COLUMN IF NOT EXISTS custody_fee numeric(6, 3),
    ADD COLUMN IF NOT EXISTS established_date date,
    ADD COLUMN IF NOT EXISTS fund_scale numeric(20, 2);

CREATE TABLE IF NOT EXISTS bp_fund_performance (
    fund_code text NOT NULL REFERENCES bp_fund_master(fund_code) ON DELETE CASCADE,
    as_of date NOT NULL,
    aum numeric(20, 2),
    ret_1m numeric(10, 2),
    ret_3m numeric(10, 2),
    ret_6m numeric(10, 2),
    ret_12m numeric(10, 2),
    ret_2y numeric(10, 2),
    ret_3y numeric(10, 2),
    ret_5y numeric(10, 2),
    ytd numeric(10, 2),
    manager text,
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fund_code, as_of)
);

COMMENT ON TABLE bp_fund_performance IS
    '基金业绩与规模（平安 queryOnsiteFundInfoList 全字段）；收益为百分数点';

CREATE TABLE IF NOT EXISTS bp_index_quote_health (
    symbol text PRIMARY KEY REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    last_trade_date date,
    expected_trade_date date,
    lag_trading_days integer,
    has_quote boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'ok',
    checked_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_index_quote_health IS
    '指数行情覆盖率看护：last=最后有行情的交易日，expected=最新交易日，status=ok/stale/dead/missing';

COMMIT;

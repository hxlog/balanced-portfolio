-- 73: 场内基金（ETF/LOF/封闭式）全量行情与主数据
-- 背景：A股个股 bp_stock_quote_daily、场外基金 bp_fund_nav_daily 已全量；场内 ETF 行情缺失。
-- 口径：btfq/qfq/hfq 三口径；数据源腾讯 fqkline/qt（source 区分）。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_etf_master (
    etf_code    text PRIMARY KEY,
    name        text,
    market      text,              -- SH / SZ
    category    text,              -- etf / lof / closed
    source      text NOT NULL DEFAULT 'sina_fund_list',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_etf_master IS '场内基金主数据（ETF/LOF/封闭式），列表来自新浪基金行情分类';

CREATE TABLE IF NOT EXISTS bp_etf_quote_daily (
    etf_code    text NOT NULL,
    trade_date  date NOT NULL,
    source      text NOT NULL,
    adjust      text NOT NULL DEFAULT 'bfq',
    open        numeric(20, 6),
    high        numeric(20, 6),
    low         numeric(20, 6),
    close       numeric(20, 6) NOT NULL,
    volume      bigint,
    amount      numeric(24, 4),
    pct_change  numeric(14, 6),
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (etf_code, trade_date, source, adjust)
);

COMMENT ON TABLE bp_etf_quote_daily IS '场内基金日线（ETF/LOF/封闭式），三口径 bfq/qfq/hfq；腾讯 hfq 为单位累计净值口径';
COMMENT ON COLUMN bp_etf_quote_daily.adjust IS 'bfq 不复权 / qfq 前复权 / hfq 后复权（腾讯口径=单位累计净值）';

CREATE INDEX IF NOT EXISTS idx_etf_quote_date
    ON bp_etf_quote_daily (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_etf_quote_symbol
    ON bp_etf_quote_daily (etf_code, adjust, trade_date DESC);

COMMIT;

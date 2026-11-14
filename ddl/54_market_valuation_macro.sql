-- 54: 全市场估值与宏观序列
BEGIN;

CREATE TABLE IF NOT EXISTS bp_market_valuation_daily (
    board       TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    pe_median   NUMERIC(14,4),
    pe_equal    NUMERIC(14,4),
    pb_median   NUMERIC(14,4),
    pb_equal    NUMERIC(14,4),
    pct_pe      NUMERIC(8,4),
    pct_pb      NUMERIC(8,4),
    sample_size INTEGER NOT NULL DEFAULT 0,
    calc_src    TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (board, trade_date),
    CONSTRAINT ck_mkt_board CHECK (board IN ('all','main','chinext','star','bse'))
);
CREATE INDEX IF NOT EXISTS idx_market_val_date ON bp_market_valuation_daily (trade_date DESC);

CREATE TABLE IF NOT EXISTS bp_macro_series (
    series_code TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    value       NUMERIC(16,8) NOT NULL,
    unit        TEXT,
    source      TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, trade_date)
);

COMMIT;

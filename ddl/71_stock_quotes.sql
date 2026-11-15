-- 71: A 股全量日线（不复权/前复权/后复权三口径）
BEGIN;

CREATE TABLE IF NOT EXISTS bp_stock_quote_daily (
    symbol text NOT NULL,
    trade_date date NOT NULL,
    source text NOT NULL,
    adjust text NOT NULL,
    open numeric(20, 4),
    high numeric(20, 4),
    low numeric(20, 4),
    close numeric(20, 4),
    volume bigint,
    amount numeric(24, 2),
    pct_change numeric(10, 4),
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date, source, adjust)
);

CREATE INDEX IF NOT EXISTS idx_stock_quote_date ON bp_stock_quote_daily (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_quote_symbol ON bp_stock_quote_daily (symbol, adjust);

COMMENT ON TABLE bp_stock_quote_daily IS 'A 股个股日线（腾讯行情，三口径：bfq 不复权 / qfq 前复权 / hfq 后复权）';
COMMENT ON COLUMN bp_stock_quote_daily.adjust IS 'bfq=不复权 / qfq=前复权 / hfq=后复权（回测默认 hfq）';

COMMIT;

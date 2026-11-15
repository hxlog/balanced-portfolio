-- 64: 指数行情极值预计算表（全历史最高 / 52 周前收盘）
-- 目的：/api/valuation/indices 的「区间最高 / 52 周涨跌」不再对每只指数全历史扫 bp_index_quote_daily，
-- 改为读这张小表，冷启动延迟从 6s 降到毫秒级。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_index_quote_extremes (
    symbol        text PRIMARY KEY,
    high_all      numeric,
    close_52w_ago numeric,
    first_date    date,
    last_date     date,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

TRUNCATE bp_index_quote_extremes;

INSERT INTO bp_index_quote_extremes (symbol, high_all, close_52w_ago, first_date, last_date)
SELECT
    q.symbol,
    max(q.close) AS high_all,
    (array_agg(q.close ORDER BY q.trade_date DESC))[251] AS close_52w_ago,
    min(q.trade_date),
    max(q.trade_date)
FROM bp_index_quote_daily q
WHERE q.adjust = 'bfq'
GROUP BY q.symbol;

COMMIT;

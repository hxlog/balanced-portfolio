-- 53: 行情复权维度 —— 第二阶段（主键与 row_hash 重建）
-- 必须与新版 bp-ingest / bp_api 代码同一发布窗口执行：
--   旧代码的 ON CONFLICT (symbol,source,trade_date) 在换主键后会失效。
-- 执行顺序：备份 → 停 bp-ingest/bp-worker → 跑 53 → 部署新代码 → 启动进程。
BEGIN;

-- 原始行情：重建 row_hash（含 adjust）
ALTER TABLE bp_index_quote_daily DROP COLUMN IF EXISTS row_hash;
ALTER TABLE bp_index_quote_daily ADD COLUMN row_hash CHAR(32) GENERATED ALWAYS AS (
    md5(symbol || '|' || source || '|' || adjust || '|' || (trade_date - DATE '1970-01-01')::text)
) STORED;

ALTER TABLE bp_index_quote_daily DROP CONSTRAINT IF EXISTS pk_bp_index_quote_daily;
ALTER TABLE bp_index_quote_daily ADD CONSTRAINT pk_bp_index_quote_daily
    PRIMARY KEY (symbol, source, adjust, trade_date);
DROP INDEX IF EXISTS idx_bp_quote_symbol_source_date;
CREATE INDEX IF NOT EXISTS idx_bp_quote_symbol_source_adj_date
    ON bp_index_quote_daily (symbol, source, adjust, trade_date DESC);

-- 清洗表：同构
ALTER TABLE bp_quote_clean DROP CONSTRAINT IF EXISTS pk_bp_quote_clean;
ALTER TABLE bp_quote_clean ADD CONSTRAINT pk_bp_quote_clean
    PRIMARY KEY (symbol, source, adjust, trade_date);
DROP INDEX IF EXISTS idx_bp_quote_clean_symbol_source_date;
CREATE INDEX IF NOT EXISTS idx_bp_quote_clean_symbol_source_adj_date
    ON bp_quote_clean (symbol, source, adjust, trade_date DESC);

COMMIT;

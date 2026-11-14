-- 51: 行情复权维度 —— 第一阶段（向后兼容，可边跑旧代码边执行）
-- 只加列 / 回填 / 约束；主键与 row_hash 的重建放到 53 号（需与代码发布同一窗口）。
BEGIN;

ALTER TABLE bp_index_quote_daily ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
ALTER TABLE bp_quote_clean ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS adjust_modes TEXT[] NOT NULL DEFAULT ARRAY['bfq']::TEXT[];
ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS index_code TEXT;
ALTER TABLE bp_portfolio_asset ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'hfq';

UPDATE bp_index_config SET adjust = COALESCE(extra_params->>'adjust', adjust) WHERE extra_params ? 'adjust';
UPDATE bp_index_config SET adjust_modes = ARRAY[COALESCE(extra_params->>'adjust', adjust)] WHERE extra_params ? 'adjust';

UPDATE bp_index_quote_daily SET adjust = 'hfq' WHERE source IN ('etf_em','etf_tx') AND adjust = 'bfq';
UPDATE bp_quote_clean SET adjust = 'hfq' WHERE source IN ('etf_em','etf_tx') AND adjust = 'bfq';
UPDATE bp_index_config SET adjust = 'hfq', adjust_modes = ARRAY['hfq'] WHERE source IN ('etf_em','etf_tx') AND adjust = 'bfq';

ALTER TABLE bp_index_quote_daily DROP CONSTRAINT IF EXISTS ck_quote_adjust;
ALTER TABLE bp_index_quote_daily ADD CONSTRAINT ck_quote_adjust CHECK (adjust IN ('bfq','qfq','hfq'));
ALTER TABLE bp_quote_clean DROP CONSTRAINT IF EXISTS ck_clean_adjust;
ALTER TABLE bp_quote_clean ADD CONSTRAINT ck_clean_adjust CHECK (adjust IN ('bfq','qfq','hfq'));
ALTER TABLE bp_index_config DROP CONSTRAINT IF EXISTS ck_config_adjust;
ALTER TABLE bp_index_config ADD CONSTRAINT ck_config_adjust CHECK (adjust IN ('bfq','qfq','hfq'));
ALTER TABLE bp_portfolio_asset DROP CONSTRAINT IF EXISTS ck_asset_adjust;
ALTER TABLE bp_portfolio_asset ADD CONSTRAINT ck_asset_adjust CHECK (adjust IN ('bfq','qfq','hfq'));

COMMIT;

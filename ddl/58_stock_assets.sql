-- 58: 个股资产（全 A 三复权）接入
BEGIN;

-- 1) 注册新浪主源 / 腾讯备源（个股日线）
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('stock_sina', 'A股个股日线(新浪, 支持 bfq/qfq/hfq)', 'stock_zh_a_daily', 'stock',
     TRUE, TRUE, '600036', TRUE, 'sina', 'stock_sina', FALSE, TRUE),
    ('stock_tx', 'A股个股日线(腾讯备源)', 'tencent_fqkline', 'stock',
     TRUE, TRUE, '600036', TRUE, 'tencent', 'stock_sina', TRUE, TRUE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    akshare_func = EXCLUDED.akshare_func,
    asset_class = EXCLUDED.asset_class,
    has_volume = EXCLUDED.has_volume,
    supports_date_range = EXCLUDED.supports_date_range,
    symbol_hint = EXCLUDED.symbol_hint,
    is_enabled = EXCLUDED.is_enabled,
    vendor = EXCLUDED.vendor,
    logical_source = EXCLUDED.logical_source,
    is_backup = EXCLUDED.is_backup,
    is_addable = EXCLUDED.is_addable,
    updated_at = now();

-- 2) adjust_modes 只允许三个合法口径
ALTER TABLE bp_index_config DROP CONSTRAINT IF EXISTS ck_config_adjust_modes;
ALTER TABLE bp_index_config ADD CONSTRAINT ck_config_adjust_modes
    CHECK (adjust_modes <@ ARRAY['bfq','qfq','hfq']::TEXT[]);

-- 3) 个股清洁表复用既有 bp_quote_clean（含 adjust 维度，53 号迁移后主键已带 adjust）
--    仅登记索引，方便回测按 source 前缀快速筛个股
CREATE INDEX IF NOT EXISTS idx_quote_clean_stock
    ON bp_quote_clean (source, symbol, trade_date) WHERE source LIKE 'stock_%';

COMMIT;

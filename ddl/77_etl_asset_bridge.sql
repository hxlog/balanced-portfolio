-- 77: 统一 ETL 资产接入桥接（managed_by + 新数据源注册）
-- 说明：只加列/注册源；9,430 条资产配置由 scripts/seed_etl_assets.py 显式执行（可 --dry-run 预演），
-- 避免迁移在未验证时自动放大资产池。
BEGIN;

ALTER TABLE bp_index_config
    ADD COLUMN IF NOT EXISTS managed_by text;

COMMENT ON COLUMN bp_index_config.managed_by IS
    '资产由谁管理：NULL=旧链路(bp_ingest)；bp_etl=统一 ETL（行情来自 bp_stock_quote_daily/bp_etf_quote_daily，清洗仍写 bp_quote_clean）';

INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('etl_a_stock', '统一ETL-A股个股（bfq/hfq 多源锚定聚合）', '', 'stock',
     TRUE, TRUE, '600036', TRUE, 'bp-etl', 'etl_a_stock', FALSE, FALSE),
    ('etl_hk_stock', '统一ETL-港股个股（bfq/hfq 多源锚定聚合）', '', 'stock',
     TRUE, TRUE, '00700', TRUE, 'bp-etl', 'etl_hk_stock', FALSE, FALSE),
    ('etl_etf', '统一ETL-场内基金（bfq/hfq 多源锚定聚合）', '', 'etf',
     TRUE, TRUE, '510300', TRUE, 'bp-etl', 'etl_etf', FALSE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
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

CREATE INDEX IF NOT EXISTS idx_bp_index_config_managed
    ON bp_index_config (managed_by, is_deleted)
    WHERE managed_by IS NOT NULL;

COMMIT;

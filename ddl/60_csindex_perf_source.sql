-- 60: 注册中证官网行情源（东财不可达时的备用行情口径）
BEGIN;

INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('csindex_perf', '中证指数官网日线行情(index-perf)', 'csindex_index_perf', 'index',
     TRUE, TRUE, '930641', TRUE, 'csindex', 'csindex_perf', TRUE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    is_enabled = EXCLUDED.is_enabled,
    is_backup = EXCLUDED.is_backup,
    updated_at = now();

COMMIT;

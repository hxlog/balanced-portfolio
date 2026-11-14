-- 61: 注册雪球指数行情源（东财/中证官网限流时的境内可用备用口径）
BEGIN;

INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('cn_index_xueqiu', '雪球指数日线(v5 kline)', 'xueqiu_index_kline', 'index',
     TRUE, TRUE, 'CSI930641', TRUE, 'xueqiu', 'cn_index_xueqiu', TRUE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    is_enabled = EXCLUDED.is_enabled,
    is_backup = EXCLUDED.is_backup,
    updated_at = now();

COMMIT;

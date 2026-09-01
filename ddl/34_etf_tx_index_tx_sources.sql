-- 34: 新增腾讯 fqkline 数据源(ETF 后复权/前复权/不复权 + 指数不复权),
-- 用于多源聚合降级链(东财被 IP 封禁时 ETF/指数可降级腾讯)。
-- 幂等: ON CONFLICT (code) DO UPDATE 保证可重复执行。
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume,
     supports_date_range, symbol_hint, vendor)
VALUES
    ('etf_tx',   'ETF行情-腾讯 fqkline(后复权/前复权/不复权)', 'tencent_fqkline', 'etf',      TRUE, TRUE, 'ETF代码, 如 518880(自动加 sh/sz 前缀)', '腾讯'),
    ('index_tx', '指数行情-腾讯 fqkline(不复权)',             'tencent_fqkline', 'cn_index', TRUE, TRUE, '带市场前缀, 如 sh000300 / sz399552', '腾讯')
ON CONFLICT (code) DO UPDATE SET
    description         = EXCLUDED.description,
    akshare_func        = EXCLUDED.akshare_func,
    asset_class         = EXCLUDED.asset_class,
    has_volume          = EXCLUDED.has_volume,
    supports_date_range = EXCLUDED.supports_date_range,
    symbol_hint         = EXCLUDED.symbol_hint,
    vendor              = EXCLUDED.vendor;

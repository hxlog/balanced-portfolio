-- 79: 全局数据新鲜度（8 类数据 SLA）+ 指数行情免费源注册
-- 用途：
--   1) bp_data_freshness 为「全局行情数据更新至 YYYY-MM-DD」徽标与 8 类数据明细
--      tooltip 的唯一事实源；由各数据任务完成时写入（bp_etl 状态同步、CFFEX、
--      估值/MVI 收尾、scripts/index_quotes_free.py），API GET /api/v1/market/data-freshness
--      只读该表（另有源表兜底推导），请求路径永不计算；
--   2) 注册腾讯 fqkline 港股指数行情源 hk_index_tx（bp_index_master 中 HK 跟踪指数的
--      免费源降级链：腾讯 -> 东财）。
-- 幂等：CREATE/INSERT ... ON CONFLICT，可重复执行。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_data_freshness (
    dataset       TEXT        PRIMARY KEY,
    label         TEXT        NOT NULL,
    as_of         DATE,
    expected_date DATE,
    status        TEXT        NOT NULL DEFAULT 'missing',
    note          TEXT,
    source        TEXT,
    meta          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_data_freshness_status CHECK (
        status IN ('ok', 'lagging', 'stale', 'missing', 'unavailable', 'error')
    )
);

COMMENT ON TABLE bp_data_freshness IS
    '全局数据新鲜度：每类数据最新完整日期 as_of / 应到日期 expected_date / 状态；'
    '由各数据任务完成时写入，GET /api/v1/market/data-freshness 只读。';
COMMENT ON COLUMN bp_data_freshness.dataset IS
    '数据类别 key：a_stock/hk_stock/etf/fund_nav/cffex/index_quotes/index_valuation/mvi（8 类），'
    '以及 market_valuation/risk_free 等扩展类别（不在 8 类徽标返回内）。';
COMMENT ON COLUMN bp_data_freshness.as_of IS '该类数据最新完整日期（无数据为 NULL）';
COMMENT ON COLUMN bp_data_freshness.expected_date IS '写入方给出的应到交易日（可由交易日历重算）';
COMMENT ON COLUMN bp_data_freshness.status IS
    'ok/lagging/stale/missing/unavailable/error；前三个由读取侧按 as_of 与 expected_date 重算覆盖。';
COMMENT ON COLUMN bp_data_freshness.meta IS '扩展 JSON（条数/覆盖率/失败原因等，供 admin 排查）';

CREATE INDEX IF NOT EXISTS idx_bp_data_freshness_status
    ON bp_data_freshness (status, updated_at DESC);

-- 8 类数据的初始行：as_of/status 待各任务首次写入；缺失时 API 会按源表兜底推导。
INSERT INTO bp_data_freshness (dataset, label, status, source) VALUES
    ('a_stock',         'A股行情',     'missing', 'bp_etl'),
    ('hk_stock',        '港股行情',    'missing', 'bp_etl'),
    ('etf',             'ETF行情',     'missing', 'bp_etl'),
    ('fund_nav',        '基金净值',    'missing', 'bp_etl'),
    ('cffex',           '股指期货',    'missing', 'bp_ingest.cffex'),
    ('index_quotes',    '指数行情',    'missing', 'scripts/index_quotes_free.py'),
    ('index_valuation', '指数估值',    'missing', 'bp_ingest.valuation_ingest'),
    ('mvi',             '市场估值指数', 'missing', 'scripts/compute_mvi.py')
ON CONFLICT (dataset) DO NOTHING;

-- 指数行情免费源：腾讯 fqkline 港股指数（hkHSI/hkHSTECH 等）。
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('hk_index_tx', '港股指数-腾讯 fqkline(免费源降级链首选)', 'tencent_fqkline', 'hk_index',
     TRUE, TRUE, 'hkHSTECH / hkHSI', TRUE, '腾讯', 'hk_index', TRUE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    is_enabled = EXCLUDED.is_enabled,
    is_backup = EXCLUDED.is_backup,
    updated_at = now();

COMMIT;

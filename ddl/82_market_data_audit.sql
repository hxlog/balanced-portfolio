-- 82: 每日数据体检结果表（09:30 audit）+ 中证官网 OSS perf.xls 行情源注册
--
-- 用途：
--   1) bp_data_audit_daily 存 scripts/daily_data_audit.py 的逐条检查结果
--      （dataset, stat_date, metric, value, threshold, status, detail），
--      GET /api/v1/market/data-health 只读最近一次体检；
--   2) 注册 csindex_oss（中证官网 OSS perf.xls，滚动约 24 交易日、WAF 免疫），
--      作为 scripts/index_quotes_free.py 中证系指数（930/931/932/H3/950 等无腾讯/
--      新浪前缀）在 index-perf JSON 被拦截后的稳定免费兜底源。
--
-- 幂等：CREATE/INSERT ... ON CONFLICT，可重复执行。
BEGIN;

CREATE TABLE IF NOT EXISTS bp_data_audit_daily (
    dataset    TEXT        NOT NULL,
    stat_date  DATE        NOT NULL,
    metric     TEXT        NOT NULL,
    value      NUMERIC,
    threshold  NUMERIC,
    status     TEXT        NOT NULL DEFAULT 'ok',
    detail     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset, stat_date, metric),
    CONSTRAINT ck_data_audit_status CHECK (status IN ('ok', 'warn', 'error'))
);

COMMENT ON TABLE bp_data_audit_daily IS
    '每日 09:30 全站数据体检结果（覆盖率/时效/准确性逐条 metric）；由 scripts/daily_data_audit.py 写入，GET /api/v1/market/data-health 只读。';
COMMENT ON COLUMN bp_data_audit_daily.dataset IS
    '数据类别：a_stock/hk_stock/etf/fund_nav/cffex/index_quotes/index_valuation/mvi，以及 clean/backlog 等派生检查';
COMMENT ON COLUMN bp_data_audit_daily.metric IS
    '检查项：as_of_lag_trading_days/coverage/clean_raw_lag_days/trading_days_YYYY/ohlc_bad_ratio/return_jump_ratio/cross_source_bad_pairs/pe_cross_source_max_rel_diff/backlog_total 等';
COMMENT ON COLUMN bp_data_audit_daily.status IS 'ok/warn/error；error 时脚本 exit 1 触发 cron 告警';
COMMENT ON COLUMN bp_data_audit_daily.detail IS '补充信息（as_of/covered/total/样本数与阈值依据等）';

CREATE INDEX IF NOT EXISTS idx_data_audit_stat_date
    ON bp_data_audit_daily (stat_date DESC, dataset, metric);

-- 中证官网 OSS perf.xls 行情源（index_quotes_free 降级链：... -> csindex_perf -> csindex_oss -> cn_index_em）
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('csindex_oss', '中证指数官网 OSS perf.xls(滚动24交易日, WAF免疫兜底)', 'csindex_oss_perf',
     'index', TRUE, FALSE, '930641 / 000985', TRUE, 'csindex', 'csindex_perf', TRUE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    is_enabled = EXCLUDED.is_enabled,
    is_backup = EXCLUDED.is_backup,
    updated_at = now();

COMMIT;

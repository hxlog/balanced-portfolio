-- 40: currency 列 + row_count + demo/premium 索引 + btc_cme_sina 降级源 + futures_cffex 不可添加
-- 幂等: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / ON CONFLICT DO NOTHING 可重复执行。
-- 依赖: ddl/schema.sql 基线(01-32 + 34-39 已应用)。

BEGIN;

SET LOCAL statement_timeout = 0;

ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'CNY';
COMMENT ON COLUMN bp_index_config.currency IS
  '资产计价币种。CNY=人民币可直接回测; 非CNY(USD/HKD/JPY等)=外币计价指数, 无外汇数据换算, builder 沉底并弹确认';

ALTER TABLE bp_data_source ADD COLUMN IF NOT EXISTS is_addable BOOLEAN NOT NULL DEFAULT TRUE;
COMMENT ON COLUMN bp_data_source.is_addable IS 'FALSE=不可在 /admin/assets 添加资产(如 futures_cffex 走独立 pipeline)';

ALTER TABLE bp_asset_data_status ADD COLUMN IF NOT EXISTS row_count BIGINT;

-- 非 CNY 标记: 港股指数=HKD, 全球指数默认 USD, 日经系=JPY, crypto/外汇/COMEX=USD
UPDATE bp_index_config SET currency='HKD' WHERE source IN ('hk_index_em','hk_index_sina');
UPDATE bp_index_config SET currency='JPY'
  WHERE source IN ('global_index_em','global_index_sina') AND name LIKE '%日经%';
UPDATE bp_index_config SET currency='USD'
  WHERE source IN ('global_index_em','global_index_sina') AND currency='CNY';
UPDATE bp_index_config SET currency='USD' WHERE source IN ('crypto_yfinance','dxy_em','gold_comex_em');
-- cmdty_main_sina(沪金/沪铜等国内期货主力) 与境内指数/ETF 保持 CNY 默认值

-- futures_cffex 走 bp_ingest/cffex.py 独立 pipeline, 通用 adapter 注册表无此 source, 禁止从 admin 添加
UPDATE bp_data_source SET is_addable=FALSE WHERE code='futures_cffex';

-- btc_cme_sina: CME 比特币期货(BTC 主力) 降级源(crypto_yfinance 限流时的备源)。
-- 列序与 bp_data_source 建表一致(schema.sql L25-39); 仿 gold_comex_em 行语义。
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume,
     supports_date_range, symbol_hint, is_enabled, vendor,
     logical_source, is_backup, is_addable)
VALUES
    ('btc_cme_sina', 'CME比特币期货(BTC主力)-akshare futures_foreign_hist',
     'futures_foreign_hist', 'alternative', TRUE, TRUE,
     'BTC-USD', TRUE, '新浪财经', 'crypto', TRUE, TRUE)
ON CONFLICT (code) DO NOTHING;

COMMIT;

-- 索引 + row_count 回填(全 hypertable GROUP BY, 分钟级, 只跑一次)放在事务外。
SET statement_timeout = 0;

CREATE INDEX IF NOT EXISTS idx_bp_portfolio_demo_order
  ON bp_portfolio (display_order, portfolio_id) WHERE is_demo = TRUE;
CREATE INDEX IF NOT EXISTS idx_cffex_premium_variety_type_date
  ON bp_cffex_premium_daily (variety, contract_type, trade_date);

-- row_count 一次性回填(全表 GROUP BY 一遍, 分钟级, 只跑一次)
UPDATE bp_asset_data_status st
SET row_count = sub.c
FROM (SELECT symbol, source, COUNT(*) AS c FROM bp_index_quote_daily GROUP BY symbol, source) sub
WHERE st.symbol = sub.symbol AND st.source = sub.source;

ANALYZE bp_portfolio; ANALYZE bp_cffex_premium_daily;
ANALYZE bp_index_config; ANALYZE bp_asset_data_status; ANALYZE bp_data_source;

-- 52: 指数估值域（主数据 + 日频估值 + 历史序列 + 分位预计算）
-- 依赖：51（bp_index_config.adjust / index_code 列）
BEGIN;

-- 1) 数据源注册（不可从 admin 添加）
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume, supports_date_range,
     symbol_hint, is_enabled, vendor, logical_source, is_backup, is_addable)
VALUES
    ('pingan_index', '平安证券指数估值数据仓库(INDEX_DATA/INDEX_DATA_V2)', 'none', 'index', false, false,
     'ZI930641 / SH000300', true, '平安证券', 'index_valuation', false, false),
    ('csindex_value', '中证指数官网估值文件(滚动20交易日)', 'stock_zh_index_value_csindex', 'index', false, false,
     '930641 / H30374', true, '中证指数', 'index_valuation', false, false),
    ('binance_futures', 'Binance USDT 永续合约公开数据', 'none', 'alternative', true, true,
     'BTCUSDT', true, 'Binance', 'crypto', false, false)
ON CONFLICT (code) DO NOTHING;

-- 2) 任务类型扩展
ALTER TABLE bp_task DROP CONSTRAINT IF EXISTS ck_bp_task_type;
ALTER TABLE bp_task ADD CONSTRAINT ck_bp_task_type CHECK (task_type = ANY (ARRAY[
    'backtest','daily_update','ingest','ingest_all','clean','asset_probe','asset_ingest','otc_price',
    'valuation_ingest','crypto_futures_ingest'
]));

-- 3) 指数主数据
CREATE TABLE IF NOT EXISTS bp_index_master (
    index_code     TEXT PRIMARY KEY,
    market         TEXT NOT NULL,
    wind_code      TEXT,
    name           TEXT NOT NULL,
    short_name     TEXT,
    index_type     TEXT,
    publisher      TEXT,
    base_date      DATE,
    base_point     NUMERIC(20,6),
    income_method  TEXT,
    weight_method  TEXT,
    intro          TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    is_tracked     BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_index_master_market CHECK (market IN ('CSI','SH','SZ','CNI','HK','US','BJ','GLOBAL')),
    CONSTRAINT ck_index_master_code CHECK (index_code <> '')
);
-- 表已存在时 CREATE TABLE IF NOT EXISTS 不会更新约束，显式重建（升级安全）
ALTER TABLE bp_index_master DROP CONSTRAINT IF EXISTS ck_index_master_market;
ALTER TABLE bp_index_master ADD CONSTRAINT ck_index_master_market
    CHECK (market IN ('CSI','SH','SZ','CNI','HK','US','BJ','GLOBAL'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_index_master_wind ON bp_index_master (wind_code) WHERE wind_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_index_master_code_market ON bp_index_master (index_code, market);
CREATE INDEX IF NOT EXISTS idx_index_master_tracked ON bp_index_master (is_tracked, index_type);

-- 4) 日频估值宽表
CREATE TABLE IF NOT EXISTS bp_index_valuation_daily (
    index_code         TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    trade_date         DATE NOT NULL,
    calc_src           TEXT NOT NULL REFERENCES bp_data_source(code),
    pe_ttm             NUMERIC(14,4),
    pe_static          NUMERIC(14,4),
    pb                 NUMERIC(14,4),
    dividend_yield_ttm NUMERIC(10,6),
    dividend_yield_lyr NUMERIC(10,6),
    roe_ttm            NUMERIC(10,4),
    roa_ttm            NUMERIC(10,4),
    bond10y            NUMERIC(10,6),
    erp                NUMERIC(10,6),
    pe_basis           TEXT,
    pb_basis           TEXT,
    div_basis          TEXT,
    level_pe           TEXT,
    level_pb           TEXT,
    level_dividend     TEXT,
    is_primary         BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw                JSONB,
    PRIMARY KEY (index_code, trade_date, calc_src),
    CONSTRAINT ck_val_pe  CHECK (pe_ttm IS NULL OR pe_ttm > 0),
    CONSTRAINT ck_val_pb  CHECK (pb IS NULL OR pb > 0),
    CONSTRAINT ck_val_div CHECK (dividend_yield_ttm IS NULL OR (dividend_yield_ttm BETWEEN -100 AND 100)),
    CONSTRAINT ck_val_level CHECK (
        (level_pe IS NULL OR level_pe IN ('低估','中性','高估')) AND
        (level_pb IS NULL OR level_pb IN ('低估','中性','高估')) AND
        (level_dividend IS NULL OR level_dividend IN ('低估','中性','高估')))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_val_primary ON bp_index_valuation_daily (index_code, trade_date) WHERE is_primary;
CREATE INDEX IF NOT EXISTS idx_val_date ON bp_index_valuation_daily (trade_date DESC, is_primary);
CREATE INDEX IF NOT EXISTS idx_val_code ON bp_index_valuation_daily (index_code, trade_date DESC);

-- 5) 历史序列长表（平安 5 年周频 + 中证官网日频）
CREATE TABLE IF NOT EXISTS bp_index_valuation_series (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    trade_date  DATE NOT NULL,
    metric      TEXT NOT NULL,
    calc_src    TEXT NOT NULL REFERENCES bp_data_source(code),
    value       NUMERIC(16,6) NOT NULL,
    is_weekly   BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, trade_date, metric, calc_src),
    CONSTRAINT ck_series_metric CHECK (metric IN
        ('pe_ttm','pe_static','pb','dividend_yield_ttm','dividend_yield_lyr','erp'))
);
CREATE INDEX IF NOT EXISTS idx_series_lookup ON bp_index_valuation_series (index_code, metric, trade_date DESC);

-- 6) 分位预计算
CREATE TABLE IF NOT EXISTS bp_index_percentile (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    as_of_date  DATE NOT NULL,
    metric      TEXT NOT NULL,
    window_key  TEXT NOT NULL,
    calc_src    TEXT NOT NULL,
    pct         NUMERIC(8,4),
    mean        NUMERIC(16,6),
    sd          NUMERIC(16,6),
    p20         NUMERIC(16,6),
    p50         NUMERIC(16,6),
    p80         NUMERIC(16,6),
    min_value   NUMERIC(16,6),
    max_value   NUMERIC(16,6),
    sample_size INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, as_of_date, metric, window_key, calc_src),
    CONSTRAINT ck_pct_window CHECK (window_key IN ('5y','10y','all')),
    CONSTRAINT ck_pct_sample CHECK (sample_size >= 0)
);
CREATE INDEX IF NOT EXISTS idx_pct_scan ON bp_index_percentile (as_of_date DESC, metric, window_key);

-- 7) 配置表桥接主数据（可空）
ALTER TABLE bp_index_config DROP CONSTRAINT IF EXISTS fk_bp_index_config_index_code;
ALTER TABLE bp_index_config ADD CONSTRAINT fk_bp_index_config_index_code
    FOREIGN KEY (index_code) REFERENCES bp_index_master(index_code) ON DELETE SET NULL;

-- 8) updated_at 触发器（复用现有函数）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'bp_set_updated_at') THEN
        DROP TRIGGER IF EXISTS trg_bp_index_master_updated_at ON bp_index_master;
        CREATE TRIGGER trg_bp_index_master_updated_at
            BEFORE UPDATE ON bp_index_master
            FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();
    END IF;
END $$;

COMMIT;

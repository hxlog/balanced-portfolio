-- =====================================================================
-- Balanced Portfolio - consolidated schema
-- Target: PostgreSQL 18 + TimescaleDB >= 2.23
-- Equivalent to applying legacy migrations 01-32 to an empty database.
-- Also includes 34-42 merged (data sources, permissions, display order,
-- logical source grouping, recommended ETF seeds, edit-flow params,
-- currency / is_addable + btc_cme_sina; 42 dropped the redundant
-- bp_asset_data_status.row_count, superseded by raw_rows/clean_rows).
-- 43 merged: fx_sina 汇率源 + bp_quote_clean.fx_rate 折算审计列 + 汇率标的配置行(45 扩充至 10 个币种对)。
-- 44 merged: 错误 ETF 名称纠正(38 号按「指数名→代码」假设写入, 18 条名称与真实产品不符)
--            + 推荐清单 17 只 ETF 全量补齐(4 类: 宽基/红利/固收/海外, 每指数恰好一只场内 ETF)。
-- 45 merged: 补齐资产池出现过的全部外币币种人民币汇率对(EUR/GBP/AUD/KRW/INR/RUB/BRL),
--            汇率标的共 10 个; VND 因新浪报价精度不足(4 位小数)不可用, 不种。
-- 47 merged: 资产池与生产库对齐 —— 补 16 个生产既有品种、停用 9 个生产不存在的幽灵键、
--            修正恒生综合中小型股指数错代码(HSSCI→HSMSI)、消除 4 行 extra_params 的兜底误加键;
--            另把 ETF 复权判定从按 source 改成按 category(588000/513310@etf_sina 因此落到 hfq)。
--            已部署环境的同款修复见 ddl/47_reconcile_asset_pool.sql(那边逐行注释判定依据)。
-- 48 merged: 修正 bp_index_config.currency 的列注释 —— 40 号写的「无外汇数据换算」在 43-45
--            接入 fx_sina 后已不成立, 列注释会误导运维与任何读 pg_description 的工具。
--            已部署环境见 ddl/48_fix_currency_column_comment.sql。
-- 49 merged: bp_asset_data_status.last_probe_kind —— probe 结论分三类(ok/unreachable/invalid),
--            让「接口可达但本次被反爬/限频挡住」的品种也能保存, 由后台 ingest 补拉。
--            已部署环境见 ddl/49_asset_probe_kind.sql。
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION bp_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------
-- Market-data metadata and prices
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_data_source (
    code                TEXT        PRIMARY KEY,
    description         TEXT        NOT NULL,
    akshare_func        TEXT        NOT NULL,
    asset_class         TEXT        NOT NULL,
    has_volume          BOOLEAN     NOT NULL DEFAULT TRUE,
    supports_date_range BOOLEAN     NOT NULL DEFAULT FALSE,
    symbol_hint         TEXT,
    is_enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    vendor              TEXT,
    logical_source      TEXT,                        -- 37: UI 逻辑源分组(物理 source 不变)
    is_backup           BOOLEAN     NOT NULL DEFAULT FALSE,  -- 37: 是否备源(非主源)
    is_addable          BOOLEAN     NOT NULL DEFAULT TRUE,   -- 40: FALSE=不可在 /admin/assets 添加资产
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_bp_data_source_updated_at ON bp_data_source;
CREATE TRIGGER trg_bp_data_source_updated_at
    BEFORE UPDATE ON bp_data_source
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

COMMENT ON COLUMN bp_data_source.is_addable IS 'FALSE=不可在 /admin/assets 添加资产(如 futures_cffex 走独立 pipeline)';

-- 34: 新增腾讯 fqkline 数据源(ETF 后复权/前复权/不复权 + 指数不复权),
-- 用于多源聚合降级链(东财被 IP 封禁时 ETF/指数可降级腾讯)。
-- 37: logical_source 逻辑源分组与 is_backup 备源标记(展示元数据, 聚合取数在 bp_ingest 完成)。
-- 40: btc_cme_sina 降级源(crypto_yfinance 限流时备源); futures_cffex is_addable=FALSE。
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume,
     supports_date_range, symbol_hint, vendor, logical_source, is_backup, is_addable)
VALUES
    ('cn_index_em',       'A股/中证指数-东财通用(字段最全, 含成交额/换手率/涨跌幅, 默认推荐)', 'index_zh_a_hist',           'cn_index',     TRUE,  TRUE,  '无市场前缀, 如 000300 / 930914', '东财', 'cn_index', FALSE, TRUE),
    ('cn_index_sina',     'A股指数-新浪',                                                    'stock_zh_index_daily',      'cn_index',     TRUE,  FALSE, '带市场前缀, 如 sh000300 / sz399552', '新浪', 'cn_index', TRUE, TRUE),
    ('cn_index_tx',       'A股指数-腾讯(支持日期范围)',                                       'stock_zh_index_daily_tx',   'cn_index',     FALSE, TRUE,  '带市场前缀, 如 sh000001', '腾讯', 'cn_index', TRUE, TRUE),
    ('cn_index_em_px',    'A股指数-东财(带前缀/csi)',                                         'stock_zh_index_daily_em',   'cn_index',     TRUE,  TRUE,  '带前缀, 如 sh000300 / csi000905', '东财', 'cn_index', TRUE, TRUE),
    ('index_tx',          '指数行情-腾讯 fqkline(不复权)',                                    'tencent_fqkline',           'cn_index',     TRUE,  TRUE,  '带市场前缀, 如 sh000300 / sz399552', '腾讯', 'cn_index', TRUE, TRUE),
    ('hk_index_em',       '港股指数-东财(close=最新价, 无成交量)',                             'stock_hk_index_daily_em',   'hk_index',     FALSE, FALSE, 'symbol 如 HSI / HSTECF2L, 见 stock_hk_index_spot_em', '东财', 'hk_index', FALSE, TRUE),
    ('hk_index_sina',     '港股指数-新浪(含成交量)',                                          'stock_hk_index_daily_sina', 'hk_index',     TRUE,  FALSE, 'symbol 如 CES100', '新浪', 'hk_index', TRUE, TRUE),
    ('global_index_em',   '全球指数-东财(中文名 symbol, close=最新价, 无成交量)',              'index_global_hist_em',      'global_index', FALSE, FALSE, '中文名, 如 标普500 / 日经225, 见 index_global_spot_em', '东财', 'global_index', FALSE, TRUE),
    ('global_index_sina', '全球指数-新浪(中文名 symbol, 近1000条)',                            'index_global_hist_sina',    'global_index', TRUE,  FALSE, '中文名, 见 index_global_name_table', '新浪', 'global_index', TRUE, TRUE),
    ('cmdty_main_sina',   '商品期货主力连续合约-新浪(OHLCV)',                                  'futures_main_sina',         'commodity',    TRUE,  TRUE,  '合约代码, 如 M0/CU0/MA0, 见 futures_display_main_sina', '新浪', 'cmdty_main_sina', FALSE, TRUE),
    ('bond_csi_treasury', '中债国债指数(财富/全收益)',                                         'bond_treasury_index_cbond', 'bond',         FALSE, FALSE, '期限标识, 如 10Y / 30Y / 0-3Y', '中债', 'bond_csi_treasury', FALSE, TRUE),
    ('etf_em',            'ETF行情-东财(后复权)',                                             'fund_etf_hist_em',          'etf',          TRUE,  TRUE,  'ETF代码, 如 518880(黄金ETF)', '东财', 'etf', FALSE, TRUE),
    ('etf_sina',          'ETF行情-新浪(全量, 自动加市场前缀)',                                 'fund_etf_hist_sina',        'etf',          TRUE,  FALSE, 'ETF代码, 如 510050 / 518880(自动加 sh/sz 前缀)', '新浪', 'etf', TRUE, TRUE),
    ('etf_tx',            'ETF行情-腾讯 fqkline(后复权/前复权/不复权)',                          'tencent_fqkline',           'etf',          TRUE,  TRUE,  'ETF代码, 如 518880(自动加 sh/sz 前缀)', '腾讯', 'etf', TRUE, TRUE),
    ('futures_cffex',     '中金所期货日行情(IF/IH/IC/IM)',                                    'get_futures_daily',         'futures',      TRUE,  TRUE,  '品种代码如 IF/IH/IC/IM', '中金所', 'futures_cffex', FALSE, FALSE),
    ('crypto_yfinance',   '加密/外汇/商品-Yahoo Finance日线(OHLCV)',                             'yfinance.download',         'alternative',  TRUE,  TRUE,  'BTC-USD / DX-Y.NYB / GC=F', 'Yahoo Finance', 'crypto_yfinance', FALSE, TRUE),
    ('dxy_em',            '美元指数(DXY)-东方财富直连 push2his (secid 100.UDI)',                 'em_push2his_kline',         'forex',        FALSE, TRUE,  'DX-Y.NYB', '东方财富', 'dxy_em', FALSE, TRUE),
    ('gold_comex_em',     'COMEX黄金(GC)-akshare futures_foreign_hist',                           'futures_foreign_hist',      'commodity',    TRUE,  TRUE,  'GC=F',     '东方财富', 'gold_comex_em', FALSE, TRUE),
    ('btc_cme_sina',      'CME比特币期货(BTC主力)-akshare futures_foreign_hist',                 'futures_foreign_hist',      'alternative',  TRUE,  TRUE,  'BTC-USD',  '新浪财经', 'crypto', TRUE, TRUE),
    ('fx_sina',           '人民币汇率-新浪(日 K, 直连 NewForexService.getDayKLine; 清洗期折算唯一汇率口径)', 'NewForexService.getDayKLine', 'fx',     FALSE, FALSE, '币种+CNY, 如 USDCNY / HKDCNY / JPYCNY', '新浪财经', 'fx_sina', FALSE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description         = EXCLUDED.description,
    akshare_func        = EXCLUDED.akshare_func,
    asset_class         = EXCLUDED.asset_class,
    has_volume          = EXCLUDED.has_volume,
    supports_date_range = EXCLUDED.supports_date_range,
    symbol_hint         = EXCLUDED.symbol_hint,
    vendor              = EXCLUDED.vendor,
    logical_source      = EXCLUDED.logical_source,
    is_backup           = EXCLUDED.is_backup,
    is_addable          = EXCLUDED.is_addable;

CREATE TABLE IF NOT EXISTS bp_index_config (
    config_id     BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol        TEXT        NOT NULL,
    source        TEXT        NOT NULL REFERENCES bp_data_source(code),
    category      TEXT,
    name          TEXT,
    start_date    DATE,
    extra_params  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    is_deleted    SMALLINT    NOT NULL DEFAULT 0,
    is_selectable BOOLEAN     NOT NULL DEFAULT TRUE,
    last_sync_at  TIMESTAMPTZ,
    last_error    TEXT,
    row_hash      CHAR(32)    GENERATED ALWAYS AS (md5(lower(symbol) || '|' || source)) STORED,
    currency      TEXT        NOT NULL DEFAULT 'CNY',   -- 40: 资产计价币种
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_bp_index_config_symbol_source UNIQUE (symbol, source),
    CONSTRAINT uq_bp_index_config_row_hash UNIQUE (row_hash),
    CONSTRAINT ck_bp_index_config_is_deleted CHECK (is_deleted IN (0, 1))
);

COMMENT ON COLUMN bp_index_config.currency IS
  '资产计价币种。CNY=人民币计价; 非CNY(USD/HKD/JPY等)=外币计价, 清洗阶段按每日汇率(fx_rate 列)折算成人民币后进回测面板。builder 把非 CNY 沉底并在添加前二次确认。';

CREATE INDEX IF NOT EXISTS idx_bp_index_config_active
    ON bp_index_config (source, symbol) WHERE is_deleted = 0;

DROP TRIGGER IF EXISTS trg_bp_index_config_updated_at ON bp_index_config;
CREATE TRIGGER trg_bp_index_config_updated_at
    BEFORE UPDATE ON bp_index_config
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_index_quote_daily (
    trade_date    DATE          NOT NULL,
    symbol        TEXT          NOT NULL,
    source        TEXT          NOT NULL REFERENCES bp_data_source(code),
    category      TEXT,
    name          TEXT,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6) NOT NULL,
    volume        BIGINT,
    amount        NUMERIC(24,4),
    turnover_rate NUMERIC(12,6),
    pct_change    NUMERIC(12,6),
    row_hash      CHAR(32) GENERATED ALWAYS AS (
        md5(symbol || '|' || source || '|' || (trade_date - DATE '1970-01-01')::text)
    ) STORED,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_index_quote_daily PRIMARY KEY (symbol, source, trade_date)
);

SELECT create_hypertable(
    'bp_index_quote_daily',
    by_range('trade_date', INTERVAL '90 days'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_bp_quote_symbol_source_date
    ON bp_index_quote_daily (symbol, source, trade_date DESC);

DROP TRIGGER IF EXISTS trg_bp_index_quote_updated_at ON bp_index_quote_daily;
CREATE TRIGGER trg_bp_index_quote_updated_at
    BEFORE UPDATE ON bp_index_quote_daily
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_quote_clean (
    trade_date  DATE          NOT NULL,
    symbol      TEXT          NOT NULL,
    source      TEXT          NOT NULL REFERENCES bp_data_source(code),
    close       NUMERIC(20,6) NOT NULL,
    open        NUMERIC(20,6),
    high        NUMERIC(20,6),
    low         NUMERIC(20,6),
    volume      BIGINT,
    ret         DOUBLE PRECISION,
    fx_rate     NUMERIC(18,8),   -- 43: 折算所用汇率(外币→CNY); CNY 资产=1, 无汇率日=NULL
    fill_flag   TEXT          NOT NULL DEFAULT 'real',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_quote_clean PRIMARY KEY (symbol, source, trade_date),
    CONSTRAINT ck_bp_quote_clean_fill CHECK (fill_flag IN ('real', 'interp'))
);

SELECT create_hypertable(
    'bp_quote_clean',
    by_range('trade_date', INTERVAL '90 days'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_bp_quote_clean_symbol_source_date
    ON bp_quote_clean (symbol, source, trade_date DESC);

DROP TRIGGER IF EXISTS trg_bp_quote_clean_updated_at ON bp_quote_clean;
CREATE TRIGGER trg_bp_quote_clean_updated_at
    BEFORE UPDATE ON bp_quote_clean
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

-- ---------------------------------------------------------------------
-- Users, portfolios, backtests and asynchronous jobs
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_admin_user (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_bp_admin_user_updated_at ON bp_admin_user;
CREATE TRIGGER trg_bp_admin_user_updated_at
    BEFORE UPDATE ON bp_admin_user
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_user (
    user_id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT        NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL,
    role            TEXT        NOT NULL DEFAULT 'user',
    status          TEXT        NOT NULL DEFAULT 'active',
    portfolio_limit INTEGER     DEFAULT 3,   -- 39: NULL = 无限
    totp_enabled    BOOLEAN     NOT NULL DEFAULT FALSE,
    totp_secret     TEXT,
    can_manage_assets BOOLEAN  NOT NULL DEFAULT FALSE,  -- 35: 资产编辑者权限(/admin/assets)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bp_user_role CHECK (role IN ('user', 'admin')),
    CONSTRAINT ck_bp_user_status CHECK (status IN ('active', 'disabled'))
);

DROP TRIGGER IF EXISTS trg_bp_user_updated_at ON bp_user;
CREATE TRIGGER trg_bp_user_updated_at
    BEFORE UPDATE ON bp_user
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_portfolio (
    portfolio_id         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 TEXT         NOT NULL,
    method               TEXT         NOT NULL DEFAULT 'quadrant_inner_sharpe_outer_rp',
    ratio                TEXT         NOT NULL DEFAULT 'sharpe',
    lookback_days        INTEGER      NOT NULL DEFAULT 156,
    start_date           DATE         NOT NULL,
    effective_start_date DATE,
    benchmark_symbol     TEXT         NOT NULL DEFAULT '000300',
    benchmark_source     TEXT         NOT NULL DEFAULT 'cn_index_em',
    benchmark_key        TEXT         NOT NULL DEFAULT '000300',
    max_weight           NUMERIC(6,4),
    rebalance_band       NUMERIC(6,4) NOT NULL DEFAULT 0.05,
    description          TEXT         NOT NULL DEFAULT '组合描述',
    is_demo              BOOLEAN      NOT NULL DEFAULT FALSE,
    status               TEXT         NOT NULL DEFAULT 'pending',
    error                TEXT,
    last_run_params      JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 39: 最后一次回测参数快照(编辑免重算)
    owner_user_id        BIGINT       REFERENCES bp_user(user_id),
    created_by           BIGINT       REFERENCES bp_user(user_id),
    updated_by           BIGINT       REFERENCES bp_user(user_id),
    risk_free_rate       NUMERIC(10,6) NOT NULL DEFAULT 0,
    fee_rate             NUMERIC(10,6) NOT NULL DEFAULT 0,
    slippage_rate        NUMERIC(10,6) NOT NULL DEFAULT 0,
    stamp_duty_rate      NUMERIC(10,6) NOT NULL DEFAULT 0,
    result_version       INTEGER      NOT NULL DEFAULT 1,
    result_updated_at    TIMESTAMPTZ,
    data_as_of_date      DATE,
    display_order        INTEGER,     -- 36: demo 全局展示顺序(匿名默认展示最小值)
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_bp_portfolio_method CHECK (method IN (
        'quadrant_inner_sharpe_outer_rp', 'all_risk_parity',
        'all_max_sharpe', 'sharpe_sq_risk_budget'
    )),
    CONSTRAINT ck_bp_portfolio_ratio CHECK (ratio IN ('sharpe', 'sortino')),
    CONSTRAINT ck_bp_portfolio_status CHECK (status IN ('pending', 'running', 'done', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_bp_portfolio_demo
    ON bp_portfolio (portfolio_id) WHERE is_demo = TRUE;
CREATE INDEX IF NOT EXISTS idx_bp_portfolio_demo_order        -- 40: demo 排序取首位
    ON bp_portfolio (display_order, portfolio_id) WHERE is_demo = TRUE;
CREATE INDEX IF NOT EXISTS idx_bp_portfolio_owner
    ON bp_portfolio (owner_user_id);

DROP TRIGGER IF EXISTS trg_bp_portfolio_updated_at ON bp_portfolio;
CREATE TRIGGER trg_bp_portfolio_updated_at
    BEFORE UPDATE ON bp_portfolio
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_portfolio_asset (
    portfolio_id BIGINT  NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    symbol       TEXT    NOT NULL,
    source       TEXT    NOT NULL REFERENCES bp_data_source(code),
    quadrant     TEXT    NOT NULL,
    display_name TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT pk_bp_portfolio_asset PRIMARY KEY (portfolio_id, symbol, source, quadrant),
    CONSTRAINT ck_bp_portfolio_asset_quadrant CHECK (
        quadrant IN ('overheat', 'stagflation', 'recovery', 'recession')
    )
);

CREATE TABLE IF NOT EXISTS bp_backtest_nav (
    portfolio_id  BIGINT           NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method        TEXT             NOT NULL,
    trade_date    DATE             NOT NULL,
    nav           DOUBLE PRECISION NOT NULL,
    benchmark_nav DOUBLE PRECISION,
    ret           DOUBLE PRECISION,
    bench_ret     DOUBLE PRECISION,
    CONSTRAINT pk_bp_backtest_nav PRIMARY KEY (portfolio_id, method, trade_date)
);

CREATE TABLE IF NOT EXISTS bp_backtest_rebalance (
    portfolio_id     BIGINT NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method           TEXT   NOT NULL,
    trade_date       DATE   NOT NULL,
    reason           TEXT,
    target_weights   JSONB  NOT NULL,
    prev_weights     JSONB,
    delta            JSONB,
    quadrant_weights JSONB,
    max_deviation    DOUBLE PRECISION,
    CONSTRAINT pk_bp_backtest_rebalance PRIMARY KEY (portfolio_id, method, trade_date)
);

CREATE TABLE IF NOT EXISTS bp_backtest_metric (
    portfolio_id BIGINT NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method       TEXT   NOT NULL,
    scope        TEXT   NOT NULL,
    metrics      JSONB  NOT NULL,
    CONSTRAINT pk_bp_backtest_metric PRIMARY KEY (portfolio_id, method, scope),
    CONSTRAINT ck_bp_backtest_metric_scope CHECK (scope IN ('portfolio', 'benchmark'))
);

CREATE TABLE IF NOT EXISTS bp_backtest_cov (
    portfolio_id             BIGINT NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method                   TEXT   NOT NULL,
    as_of_date               DATE   NOT NULL,
    labels                   JSONB  NOT NULL,
    corr_matrix              JSONB  NOT NULL,
    cov_matrix               JSONB,
    optimal_weights          JSONB,
    optimal_quadrant_weights JSONB,
    CONSTRAINT pk_bp_backtest_cov PRIMARY KEY (portfolio_id, method)
);

CREATE TABLE IF NOT EXISTS bp_backtest_benchmark (
    portfolio_id  BIGINT           NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    benchmark_key TEXT             NOT NULL,
    trade_date    DATE             NOT NULL,
    nav           DOUBLE PRECISION NOT NULL,
    ret           DOUBLE PRECISION,
    CONSTRAINT pk_bp_backtest_benchmark PRIMARY KEY (portfolio_id, benchmark_key, trade_date)
);

CREATE TABLE IF NOT EXISTS bp_backtest_attribution (
    portfolio_id  BIGINT NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method        TEXT   NOT NULL,
    benchmark_key TEXT   NOT NULL DEFAULT 'bond6040',
    payload       JSONB  NOT NULL,
    CONSTRAINT pk_bp_backtest_attribution PRIMARY KEY (portfolio_id, method, benchmark_key)
);

CREATE TABLE IF NOT EXISTS bp_task (
    task_id          UUID        PRIMARY KEY,
    celery_id        TEXT,
    task_type        TEXT        NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'queued',
    portfolio_id     BIGINT      REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    owner_user_id    BIGINT      REFERENCES bp_user(user_id),
    progress_current INTEGER     NOT NULL DEFAULT 0,
    progress_total   INTEGER     NOT NULL DEFAULT 1,
    progress_message TEXT,
    result           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bp_task_status CHECK (
        status IN ('queued', 'running', 'success', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_bp_task_type CHECK (task_type IN (
        'backtest', 'daily_update', 'ingest', 'ingest_all', 'clean',
        'asset_probe', 'asset_ingest', 'otc_price'
    ))
);

CREATE INDEX IF NOT EXISTS idx_bp_task_portfolio_status
    ON bp_task (portfolio_id, status, created_at DESC);

DROP TRIGGER IF EXISTS trg_bp_task_updated_at ON bp_task;
CREATE TRIGGER trg_bp_task_updated_at
    BEFORE UPDATE ON bp_task
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_asset_data_status (
    symbol          TEXT        NOT NULL,
    source          TEXT        NOT NULL REFERENCES bp_data_source(code),
    last_raw_date   DATE,
    last_clean_date DATE,
    raw_rows        BIGINT      NOT NULL DEFAULT 0,
    clean_rows      BIGINT      NOT NULL DEFAULT 0,
    last_success_at TIMESTAMPTZ,
    last_error      TEXT,
    last_probe_ms   INTEGER,
    -- 49: 上次测试读取的结论类别。ok=成功; unreachable=接口可达但本次被反爬/限频/超时挡住
    -- (允许保存, 由后台 ingest 补拉); invalid=未知源/代码不存在(拦截保存); NULL=从未测试。
    last_probe_kind TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_asset_data_status PRIMARY KEY (symbol, source),
    CONSTRAINT ck_bp_asset_data_status_probe_kind
        CHECK (last_probe_kind IS NULL OR last_probe_kind IN ('ok', 'unreachable', 'invalid'))
);

DROP TRIGGER IF EXISTS trg_bp_asset_data_status_updated_at ON bp_asset_data_status;
CREATE TRIGGER trg_bp_asset_data_status_updated_at
    BEFORE UPDATE ON bp_asset_data_status
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_data_refresh_run (
    run_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id           UUID REFERENCES bp_task(task_id),
    target_trade_date DATE,
    status            TEXT        NOT NULL DEFAULT 'running',
    error             TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    CONSTRAINT ck_bp_data_refresh_run_status CHECK (status IN ('running', 'success', 'failed'))
);

CREATE TABLE IF NOT EXISTS bp_portfolio_update_state (
    portfolio_id           BIGINT PRIMARY KEY REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    last_result_trade_date DATE,
    last_data_trade_date   DATE,
    last_task_id           UUID REFERENCES bp_task(task_id),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_bp_portfolio_update_state_updated_at ON bp_portfolio_update_state;
CREATE TRIGGER trg_bp_portfolio_update_state_updated_at
    BEFORE UPDATE ON bp_portfolio_update_state
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_audit_log (
    audit_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id BIGINT REFERENCES bp_user(user_id),
    action        TEXT        NOT NULL,
    entity_type   TEXT        NOT NULL,
    entity_id     TEXT,
    detail        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bp_audit_log_actor_time
    ON bp_audit_log (actor_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bp_user_portfolio_order (
    user_id       BIGINT      NOT NULL REFERENCES bp_user(user_id) ON DELETE CASCADE,
    portfolio_id  BIGINT      NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    display_order INTEGER     NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_user_portfolio_order PRIMARY KEY (user_id, portfolio_id)
);

CREATE INDEX IF NOT EXISTS idx_bp_user_portfolio_order_user
    ON bp_user_portfolio_order (user_id, display_order);

-- ---------------------------------------------------------------------
-- CFFEX daily data
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_cffex_contract_daily (
    trade_date    DATE          NOT NULL,
    symbol        TEXT          NOT NULL,
    variety       TEXT          NOT NULL,
    open          NUMERIC(20,4),
    high          NUMERIC(20,4),
    low           NUMERIC(20,4),
    close         NUMERIC(20,4) NOT NULL,
    settle        NUMERIC(20,4),
    volume        BIGINT,
    open_interest BIGINT,
    pre_settle    NUMERIC(20,4),
    turnover      NUMERIC(20,4),
    row_hash      CHAR(32) GENERATED ALWAYS AS (
        md5(symbol || '|' || (trade_date - DATE '1970-01-01')::text)
    ) STORED,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_cffex_contract_daily PRIMARY KEY (symbol, trade_date)
);

SELECT create_hypertable(
    'bp_cffex_contract_daily',
    by_range('trade_date', INTERVAL '90 days'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_cffex_contract_variety_date
    ON bp_cffex_contract_daily (variety, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_cffex_contract_symbol_date
    ON bp_cffex_contract_daily (symbol, trade_date DESC);

DROP TRIGGER IF EXISTS trg_cffex_contract_updated_at ON bp_cffex_contract_daily;
CREATE TRIGGER trg_cffex_contract_updated_at
    BEFORE UPDATE ON bp_cffex_contract_daily
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_cffex_premium_daily (
    trade_date       DATE          NOT NULL,
    variety          TEXT          NOT NULL,
    contract_symbol  TEXT          NOT NULL,
    contract_type    TEXT          NOT NULL,
    days_to_expiry   INTEGER       NOT NULL,
    spot_price       NUMERIC(20,4) NOT NULL,
    futures_price    NUMERIC(20,4) NOT NULL,
    basis            NUMERIC(20,4) NOT NULL,
    premium_rate     NUMERIC(12,6),
    ann_premium_rate NUMERIC(12,6),
    composite_rate   NUMERIC(12,6),
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_cffex_premium_daily PRIMARY KEY (trade_date, variety, contract_symbol)
);

CREATE INDEX IF NOT EXISTS idx_cffex_premium_variety_date
    ON bp_cffex_premium_daily (variety, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_cffex_premium_type_date
    ON bp_cffex_premium_daily (contract_type, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_cffex_premium_variety_type_date   -- 40: 品种×类型×日期点查
    ON bp_cffex_premium_daily (variety, contract_type, trade_date);

-- ---------------------------------------------------------------------
-- Crypto correlation dashboard (预计算, 镜像 CFFEX premium 模式)
-- ---------------------------------------------------------------------
-- 清理旧 /crypto 实验遗留的孤儿表 (无代码引用, grep 全仓 0 命中)
DROP TABLE IF EXISTS bp_crypto_correlation_snapshot;

-- 注: 若从 JSONB series-per-row 旧版迁移, 先手动 DROP 旧表再跑本 schema:
--   psql -c "DROP TABLE IF EXISTS bp_crypto_corr_daily, bp_crypto_price_daily;"
-- (CREATE IF NOT EXISTS 不会改已存在表的列; 旧 JSONB bp_crypto_corr_daily 必须先 DROP)
CREATE TABLE IF NOT EXISTS bp_crypto_corr_daily (
    trade_date DATE        NOT NULL,
    pair_key   TEXT        NOT NULL,    -- 'btc_vs_comex_gold' / 'btc_vs_au0_gold' / 'btc_vs_sp500' / 'btc_vs_nasdaq'
    asset_a    TEXT        NOT NULL,    -- 'BTC-USD' (相关系数的 A 腿, 便于多币种扩展)
    asset_b    TEXT        NOT NULL,    -- 'GC=F' / 'AU0' / '标普500' / '纳斯达克'
    method     TEXT        NOT NULL,    -- 'pearson' | 'spearman' | 'kendall' | 'hoeffding'
    corr_3m    NUMERIC(12,6),           -- 4 个窗口作列 (CFFEX 式, 一行=一日×一对×一方法)
    corr_6m    NUMERIC(12,6),
    corr_9m    NUMERIC(12,6),
    corr_12m   NUMERIC(12,6),
    as_of_ts   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_crypto_corr_daily PRIMARY KEY (trade_date, pair_key, method),
    CONSTRAINT ck_bp_crypto_corr_method CHECK (method IN ('pearson','spearman','kendall','hoeffding'))
);
CREATE INDEX IF NOT EXISTS idx_bp_crypto_corr_pair_method_date
    ON bp_crypto_corr_daily (pair_key, method, trade_date);

-- 6 资产 NYSE 对齐收盘 (供快照 + DXY 滞后图 + BTC 叠加, 不再用 meta 存 JSON 数组)
CREATE TABLE IF NOT EXISTS bp_crypto_price_daily (
    trade_date DATE          NOT NULL,
    symbol     TEXT          NOT NULL,
    source     TEXT          NOT NULL,
    close      NUMERIC(20,4) NOT NULL,
    as_of_ts   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_crypto_price_daily PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_bp_crypto_price_symbol_date
    ON bp_crypto_price_daily (symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS bp_crypto_meta (
    key        TEXT        NOT NULL,
    value      TEXT        NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_crypto_meta PRIMARY KEY (key)
);

-- ---------------------------------------------------------------------
-- Trading calendar and OTC bookkeeping
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_trading_calendar (
    market     TEXT        NOT NULL DEFAULT 'CN',
    cal_date   DATE        NOT NULL,
    is_trading BOOLEAN     NOT NULL,
    confidence TEXT        NOT NULL DEFAULT 'official',
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_trading_calendar PRIMARY KEY (market, cal_date),
    CONSTRAINT ck_bp_trading_calendar_conf CHECK (
        confidence IN ('official', 'estimated', 'custom')
    )
);

CREATE INDEX IF NOT EXISTS idx_bp_trading_calendar_trading
    ON bp_trading_calendar (market, cal_date) WHERE is_trading;

DROP TRIGGER IF EXISTS trg_bp_trading_calendar_updated_at ON bp_trading_calendar;
CREATE TRIGGER trg_bp_trading_calendar_updated_at
    BEFORE UPDATE ON bp_trading_calendar
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_otc_deal (
    deal_id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  TEXT        NOT NULL,
    product_type          TEXT        NOT NULL,
    engine                TEXT        NOT NULL DEFAULT 'mc',
    underlying_symbol     TEXT        NOT NULL,
    underlying_source     TEXT        NOT NULL DEFAULT 'cn_index_em',
    terms                 JSONB       NOT NULL DEFAULT '{}'::jsonb,
    is_example            BOOLEAN     NOT NULL DEFAULT FALSE,
    owner_user_id         BIGINT      REFERENCES bp_user(user_id) ON DELETE CASCADE,
    last_price            NUMERIC(20,4),
    last_present_notional NUMERIC(24,4),
    last_greeks           JSONB,
    last_status           TEXT,
    last_valued_at        TIMESTAMPTZ,
    last_result           JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bp_otc_deal_type CHECK (
        product_type IN ('snowball', 'phoenix', 'airbag', 'barrier')
    ),
    CONSTRAINT ck_bp_otc_deal_engine CHECK (
        engine IN ('mc', 'analytic', 'quad', 'pde')
    )
);

CREATE INDEX IF NOT EXISTS idx_bp_otc_deal_example
    ON bp_otc_deal (is_example) WHERE is_example;
CREATE INDEX IF NOT EXISTS idx_bp_otc_deal_owner
    ON bp_otc_deal (owner_user_id);

DROP TRIGGER IF EXISTS trg_bp_otc_deal_updated_at ON bp_otc_deal;
CREATE TRIGGER trg_bp_otc_deal_updated_at
    BEFORE UPDATE ON bp_otc_deal
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

CREATE TABLE IF NOT EXISTS bp_otc_deal_price_history (
    history_id  BIGSERIAL PRIMARY KEY,
    deal_id     BIGINT      NOT NULL REFERENCES bp_otc_deal(deal_id) ON DELETE CASCADE,
    priced_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    price       DOUBLE PRECISION,
    status      TEXT,
    current_pnl DOUBLE PRECISION,
    result      JSONB       NOT NULL,
    task_id     TEXT
);

CREATE INDEX IF NOT EXISTS idx_bp_otc_deal_price_history_deal
    ON bp_otc_deal_price_history (deal_id, priced_at DESC);

CREATE TABLE IF NOT EXISTS bp_user_otc_deal_order (
    user_id       BIGINT      NOT NULL REFERENCES bp_user(user_id) ON DELETE CASCADE,
    deal_id       BIGINT      NOT NULL REFERENCES bp_otc_deal(deal_id) ON DELETE CASCADE,
    display_order INTEGER     NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_user_otc_deal_order PRIMARY KEY (user_id, deal_id)
);

CREATE INDEX IF NOT EXISTS idx_bp_user_otc_deal_order_user
    ON bp_user_otc_deal_order (user_id, display_order);

-- Keep all three hypertables converged to the final 90-day chunk interval
-- when the script is rerun against an already-created canonical schema.
SELECT set_chunk_time_interval('bp_index_quote_daily', INTERVAL '90 days');
SELECT set_chunk_time_interval('bp_quote_clean', INTERVAL '90 days');
SELECT set_chunk_time_interval('bp_cffex_contract_daily', INTERVAL '90 days');

-- ---------------------------------------------------------------------
-- Asset seeds in their final corrected state.
-- Non-ETF active assets are explicitly marked bfq; ETF assets are hfq.
-- Known invalid aliases/periods remain soft-deleted and non-selectable.
-- ---------------------------------------------------------------------
WITH asset_seed (symbol, source, category, name, base_params, start_date) AS (
    VALUES
        ('000300', 'cn_index_em', 'index', '沪深300', '{}'::jsonb, NULL),
        ('000905', 'cn_index_em', 'index', '中证500', '{}'::jsonb, NULL),
        ('000852', 'cn_index_em', 'index', '中证1000', '{}'::jsonb, NULL),
        ('000688', 'cn_index_em', 'index', '科创50', '{}'::jsonb, NULL),
        ('000510', 'cn_index_em', 'index', '中证A500', '{}'::jsonb, NULL),
        ('930914', 'cn_index_em', 'index', '中证港股通高股息', '{}'::jsonb, NULL),
        ('000825', 'cn_index_em', 'index', '央企红利', '{}'::jsonb, NULL),
        ('931722', 'cn_index_em', 'index', '国新港股通央企红利', '{}'::jsonb, NULL),
        ('HSI', 'hk_index_em', 'index', '恒生指数', '{}'::jsonb, NULL),
        ('标普500', 'global_index_em', 'index', '标普500', '{}'::jsonb, NULL),
        ('日经225', 'global_index_em', 'index', '日经225', '{}'::jsonb, NULL),
        ('CU0', 'cmdty_main_sina', 'commodity', '沪铜主力(有色代表, 替上期有色)', '{}'::jsonb, NULL),
        ('MA0', 'cmdty_main_sina', 'commodity', '甲醇主力(能化代表, 替易盛能化)', '{}'::jsonb, NULL),
        ('M0', 'cmdty_main_sina', 'commodity', '豆粕主力', '{}'::jsonb, NULL),
        ('SC0', 'cmdty_main_sina', 'commodity', '原油主力(INE)', '{}'::jsonb, NULL),
        ('10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(10年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('30Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(30年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-3年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('518880', 'etf_em', 'etf', '黄金ETF(华安)', '{"adjust":"hfq"}'::jsonb, NULL),
        ('000001', 'cn_index_em', 'index', '上证综合指数', '{}'::jsonb, NULL),
        ('000010', 'cn_index_em', 'index', '上证180指数', '{}'::jsonb, NULL),
        ('000015', 'cn_index_em', 'index', '上证红利指数', '{}'::jsonb, NULL),
        ('000016', 'cn_index_em', 'index', '上证50指数', '{}'::jsonb, NULL),
        ('000309', 'cn_index_em', 'index', '上证380指数', '{}'::jsonb, NULL),
        ('000698', 'cn_index_em', 'index', '上证科创板100指数', '{}'::jsonb, NULL),
        ('000814', 'cn_index_em', 'index', '中证国有企业红利指数', '{}'::jsonb, NULL),
        ('000846', 'cn_index_em', 'index', '中证ESG100指数', '{}'::jsonb, NULL),
        ('000903', 'cn_index_em', 'index', '中证100指数', '{}'::jsonb, NULL),
        ('000904', 'cn_index_em', 'index', '中证200指数', '{}'::jsonb, NULL),
        ('000906', 'cn_index_em', 'index', '中证800指数', '{}'::jsonb, NULL),
        ('000907', 'cn_index_em', 'index', '中证700指数', '{}'::jsonb, NULL),
        ('000918', 'cn_index_em', 'index', '沪深300成长指数', '{}'::jsonb, NULL),
        ('000919', 'cn_index_em', 'index', '中证医药卫生指数', '{}'::jsonb, NULL),
        ('000922', 'cn_index_em', 'index', '中证红利指数', '{}'::jsonb, NULL),
        ('000925', 'cn_index_em', 'index', '中证锐联基本面50指数', '{}'::jsonb, NULL),
        ('000931', 'cn_index_em', 'index', '中证全指可选消费指数', '{}'::jsonb, NULL),
        ('000932', 'cn_index_em', 'index', '中证主要消费指数', '{}'::jsonb, NULL),
        ('000933', 'cn_index_em', 'index', '中证全指医药卫生指数', '{}'::jsonb, NULL),
        ('000935', 'cn_index_em', 'index', '中证全指信息技术指数', '{}'::jsonb, NULL),
        ('000949', 'cn_index_em', 'index', '中证金融地产指数', '{}'::jsonb, NULL),
        ('000974', 'cn_index_em', 'index', '中证800金融指数', '{}'::jsonb, NULL),
        ('000982', 'cn_index_em', 'index', '中证500等权重指数', '{}'::jsonb, NULL),
        ('000984', 'cn_index_em', 'index', '沪深300等权重指数', '{}'::jsonb, NULL),
        ('399001', 'cn_index_em', 'index', '深证成份指数', '{}'::jsonb, NULL),
        ('399006', 'cn_index_em', 'index', '创业板指数', '{}'::jsonb, NULL),
        ('399324', 'cn_index_em', 'index', '深证红利指数', '{}'::jsonb, NULL),
        ('399330', 'cn_index_em', 'index', '深证100指数', '{}'::jsonb, NULL),
        ('399368', 'cn_index_em', 'index', '深证300指数', '{}'::jsonb, NULL),
        ('399378', 'cn_index_em', 'index', '国证ESG300指数', '{}'::jsonb, NULL),
        ('399673', 'cn_index_em', 'index', '创业板50指数', '{}'::jsonb, NULL),
        ('399709', 'cn_index_em', 'index', '深证基本面60指数', '{}'::jsonb, NULL),
        ('399808', 'cn_index_em', 'index', '中证新能源指数', '{}'::jsonb, NULL),
        ('399812', 'cn_index_em', 'index', '中证养老产业指数', '{}'::jsonb, NULL),
        ('399974', 'cn_index_em', 'index', '中证国有企业改革指数', '{}'::jsonb, NULL),
        ('399976', 'cn_index_em', 'index', '中证新能源汽车指数', '{}'::jsonb, NULL),
        ('399977', 'cn_index_em', 'index', '中证内地低碳经济主题指数', '{}'::jsonb, NULL),
        ('399986', 'cn_index_em', 'index', '中证银行指数', '{}'::jsonb, NULL),
        ('399991', 'cn_index_em', 'index', '国证一带一路指数', '{}'::jsonb, NULL),
        ('399997', 'cn_index_em', 'index', '中证白酒指数', '{}'::jsonb, NULL),
        ('930000', 'cn_index_em', 'index', '中证A100指数', '{}'::jsonb, NULL),
        ('930009', 'cn_index_em', 'index', '中证机器人产业指数', '{}'::jsonb, NULL),
        ('930050', 'cn_index_em', 'index', '中证A50指数', '{}'::jsonb, NULL),
        ('930091', 'cn_index_em', 'index', '中证民营企业红利指数', '{}'::jsonb, NULL),
        ('930104', 'cn_index_em', 'index', '中证全指证券公司指数', '{}'::jsonb, NULL),
        ('930651', 'cn_index_em', 'index', '中证计算机主题指数', '{}'::jsonb, NULL),
        ('930653', 'cn_index_em', 'index', '中证食品饮料指数', '{}'::jsonb, NULL),
        ('930697', 'cn_index_em', 'index', '中证家电指数', '{}'::jsonb, NULL),
        ('930713', 'cn_index_em', 'index', '中证人工智能主题指数', '{}'::jsonb, NULL),
        ('930719', 'cn_index_em', 'index', '中证证券公司指数', '{}'::jsonb, NULL),
        ('930758', 'cn_index_em', 'index', '中证生物医药指数', '{}'::jsonb, NULL),
        ('930782', 'cn_index_em', 'index', '中证沪港深红利低波动指数', '{}'::jsonb, NULL),
        ('930788', 'cn_index_em', 'index', '中证智能汽车主题指数', '{}'::jsonb, NULL),
        ('930842', 'cn_index_em', 'index', '中证保险主题指数', '{}'::jsonb, NULL),
        ('930875', 'cn_index_em', 'index', '中证A800指数', '{}'::jsonb, NULL),
        ('930901', 'cn_index_em', 'index', '中证传媒指数', '{}'::jsonb, NULL),
        ('930902', 'cn_index_em', 'index', '中证大数据产业指数', '{}'::jsonb, NULL),
        ('930916', 'cn_index_em', 'index', '中证医疗指数', '{}'::jsonb, NULL),
        ('930950', 'cn_index_em', 'index', '中证红利潜力指数', '{}'::jsonb, NULL),
        ('930955', 'cn_index_em', 'index', '中证红利低波动100指数', '{}'::jsonb, NULL),
        ('930997', 'cn_index_em', 'index', '中证新能源汽车产业指数', '{}'::jsonb, NULL),
        ('931071', 'cn_index_em', 'index', '中证物联网主题指数', '{}'::jsonb, NULL),
        ('931079', 'cn_index_em', 'index', '中证5G通信主题指数', '{}'::jsonb, NULL),
        ('931151', 'cn_index_em', 'index', '中证光伏产业指数', '{}'::jsonb, NULL),
        ('931152', 'cn_index_em', 'index', '中证上海环交所碳中和指数', '{}'::jsonb, NULL),
        ('931160', 'cn_index_em', 'index', '中证芯片产业指数', '{}'::jsonb, NULL),
        ('931468', 'cn_index_em', 'index', '中证云计算主题指数', '{}'::jsonb, NULL),
        ('931590', 'cn_index_em', 'index', '中证锂电池指数', '{}'::jsonb, NULL),
        ('931643', 'cn_index_em', 'index', '中证科创创业50指数', '{}'::jsonb, NULL),
        ('931768', 'cn_index_em', 'index', '中证红利低波动50指数', '{}'::jsonb, NULL),
        ('931775', 'cn_index_em', 'index', '中证全指房地产指数', '{}'::jsonb, NULL),
        ('931865', 'cn_index_em', 'index', '中证半导体产业指数', '{}'::jsonb, NULL),
        ('932000', 'cn_index_em', 'index', '中证2000指数', '{}'::jsonb, NULL),
        ('932051', 'cn_index_em', 'index', '中证现金流指数', '{}'::jsonb, NULL),
        ('932351', 'cn_index_em', 'index', '中证全指自由现金流指数', '{}'::jsonb, NULL),
        ('980092', 'cn_index_em', 'index', '国证自由现金流指数', '{}'::jsonb, NULL),
        ('H30269', 'cn_index_em', 'index', '中证红利低波动指数', '{}'::jsonb, NULL),
        ('H30352', 'cn_index_em', 'index', '中证500价值指数', '{}'::jsonb, NULL),
        ('H30356', 'cn_index_em', 'index', '中证800价值指数', '{}'::jsonb, NULL),
        ('159653', 'etf_em', 'etf', 'ESG300ETF国联安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159755', 'etf_em', 'etf', '广发国证新能源车电池ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159781', 'etf_em', 'etf', '科创创业ETF易方达', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159790', 'etf_em', 'etf', '华夏中证内地低碳经济主题ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159819', 'etf_em', 'etf', '人工智能ETF易方达', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159901', 'etf_em', 'etf', '深证100ETF易方达', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159905', 'etf_em', 'etf', '红利ETF工银', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159916', 'etf_em', 'etf', '基本面ETF建信', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159928', 'etf_em', 'etf', '汇添富中证主要消费ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159936', 'etf_em', 'etf', '广发中证全指可选消费ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159939', 'etf_em', 'etf', '广发中证全指信息技术ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159943', 'etf_em', 'etf', '深证成指ETF大成', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159949', 'etf_em', 'etf', '创业板50ETF华安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159985', 'etf_em', 'etf', '豆粕ETF(华夏)', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159995', 'etf_em', 'etf', '芯片ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159996', 'etf_em', 'etf', '家电ETF国泰', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159997', 'etf_em', 'etf', '电子ETF天弘', '{"adjust":"hfq"}'::jsonb, NULL),
        ('161129', 'etf_em', 'etf', '易方达原油A', '{"adjust":"hfq"}'::jsonb, NULL),
        ('161226', 'etf_em', 'etf', '国投瑞银白银期货(LOF)A', '{"adjust":"hfq"}'::jsonb, NULL),
        ('161725', 'etf_em', 'etf', '鹏华中证白酒(LOF)', '{"adjust":"hfq"}'::jsonb, NULL),
        ('164824', 'etf_em', 'etf', '印度基金LOF工银瑞信', '{"adjust":"hfq"}'::jsonb, NULL),
        ('510180', 'etf_em', 'etf', '上证180ETF华安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('510210', 'etf_em', 'etf', '上证指数ETF富国', '{"adjust":"hfq"}'::jsonb, NULL),
        ('510880', 'etf_em', 'etf', '红利ETF华泰柏瑞', '{"adjust":"hfq"}'::jsonb, NULL),
        ('510900', 'etf_em', 'etf', '恒生中国企业ETF易方达', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511010', 'etf_em', 'etf', '国债ETF国泰', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511020', 'etf_em', 'etf', '国债ETF平安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511030', 'etf_em', 'etf', '公司债ETF平安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511180', 'etf_em', 'etf', '可转债ETF海富通', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511220', 'etf_em', 'etf', '城投债ETF海富通', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511360', 'etf_em', 'etf', '短融ETF海富通', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511380', 'etf_em', 'etf', '可转债ETF博时', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511520', 'etf_em', 'etf', '政金债ETF富国', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512010', 'etf_em', 'etf', '易方达中证医药ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512170', 'etf_em', 'etf', '医疗ETF华宝', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512200', 'etf_em', 'etf', '房地产ETF南方', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512260', 'etf_em', 'etf', '中证500低波动ETF华安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512400', 'etf_em', 'etf', '有色金属ETF(南方)', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512480', 'etf_em', 'etf', '半导体ETF国联安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512640', 'etf_em', 'etf', '金融地产ETF嘉实', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512720', 'etf_em', 'etf', '计算机ETF国泰', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512750', 'etf_em', 'etf', '基本面50ETF嘉实', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512800', 'etf_em', 'etf', '银行ETF华宝', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512880', 'etf_em', 'etf', '证券ETF国泰', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512890', 'etf_em', 'etf', '红利低波ETF华泰柏瑞', '{"adjust":"hfq"}'::jsonb, NULL),
        ('512980', 'etf_em', 'etf', '传媒ETF广发', '{"adjust":"hfq"}'::jsonb, NULL),
        ('513030', 'etf_em', 'etf', '德国DAX30ETF华安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('513060', 'etf_em', 'etf', '恒生医疗ETF博时', '{"adjust":"hfq"}'::jsonb, NULL),
        ('513080', 'etf_em', 'etf', '法国CAC40ETF华安', '{"adjust":"hfq"}'::jsonb, NULL),
        ('513180', 'etf_em', 'etf', '恒生科技ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('513330', 'etf_em', 'etf', '恒生互联网ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515030', 'etf_em', 'etf', '华夏中证新能源汽车ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515050', 'etf_em', 'etf', '通信ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515080', 'etf_em', 'etf', '中证红利ETF招商', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515100', 'etf_em', 'etf', '红利低波100ETF景顺', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515150', 'etf_em', 'etf', '一带一路ETF富国', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515170', 'etf_em', 'etf', '食品饮料ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515230', 'etf_em', 'etf', '软件ETF国泰', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515250', 'etf_em', 'etf', '智能汽车ETF富国', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515290', 'etf_em', 'etf', '银行ETF天弘', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515400', 'etf_em', 'etf', '大数据ETF富国', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515450', 'etf_em', 'etf', '红利低波50ETF南方', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515590', 'etf_em', 'etf', '500等权ETF前海开源', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515700', 'etf_em', 'etf', '平安中证新能源汽车产业ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515790', 'etf_em', 'etf', '华泰柏瑞中证光伏产业ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515800', 'etf_em', 'etf', '中证800ETF汇添富', '{"adjust":"hfq"}'::jsonb, NULL),
        ('515910', 'etf_em', 'etf', '质量ETF中金', '{"adjust":"hfq"}'::jsonb, NULL),
        ('516160', 'etf_em', 'etf', '南方中证新能源ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('516510', 'etf_em', 'etf', '云计算ETF易方达', '{"adjust":"hfq"}'::jsonb, NULL),
        ('516560', 'etf_em', 'etf', '养老ETF华宝', '{"adjust":"hfq"}'::jsonb, NULL),
        ('560030', 'etf_em', 'etf', '800价值ETF汇添富', '{"adjust":"hfq"}'::jsonb, NULL),
        ('562310', 'etf_em', 'etf', '沪深300成长ETF银华', '{"adjust":"hfq"}'::jsonb, NULL),
        ('562320', 'etf_em', 'etf', '沪深300价值ETF银华', '{"adjust":"hfq"}'::jsonb, NULL),
        ('562330', 'etf_em', 'etf', '中证500价值ETF银华', '{"adjust":"hfq"}'::jsonb, NULL),
        ('562500', 'etf_em', 'etf', '机器人ETF华夏', '{"adjust":"hfq"}'::jsonb, NULL),
        ('562990', 'etf_em', 'etf', '易方达中证上海环交所碳中和ETF', '{"adjust":"hfq"}'::jsonb, NULL),
        ('HSAHP', 'hk_index_em', 'index', '恒生AH股溢价指数', '{}'::jsonb, NULL),
        ('HSCEI', 'hk_index_em', 'index', '恒生中国企业指数', '{}'::jsonb, NULL),
        ('HSCONSI', 'hk_index_em', 'index', '恒生消费指数', '{}'::jsonb, NULL),
        ('HSHCI', 'hk_index_em', 'index', '恒生医疗保健指数', '{}'::jsonb, NULL),
        ('HSHDYI', 'hk_index_em', 'index', '恒生高股息率指数', '{}'::jsonb, NULL),
        ('HSIII', 'hk_index_em', 'index', '恒生互联网科技业指数', '{}'::jsonb, NULL),
        ('HSISC', 'hk_index_em', 'index', '恒生港股通指数', '{}'::jsonb, NULL),
        -- 47: 恒生综合中小型股指数的真实东财代码是 HSMSI(HSSCI 系错代码, 恒生综合指数族
        -- 无此代码, 生产库从未取到过数据)。生产库该键即为 HSMSI, 此处写正确代码。
        -- start_date 按生产库现值写死(其余 hk_index_em 行仍为 NULL, 由 ingest 回写)。
        ('HSMSI', 'hk_index_em', 'index', '恒生综合中小型股指数', '{}'::jsonb, DATE '2017-01-01'),
        ('HSTECH', 'hk_index_em', 'index', '恒生科技指数', '{}'::jsonb, NULL),
        ('俄罗斯RTS', 'global_index_em', 'index', '俄罗斯RTS', '{}'::jsonb, NULL),
        ('孟买SENSEX', 'global_index_em', 'index', '孟买SENSEX', '{}'::jsonb, NULL),
        ('富时100', 'global_index_em', 'index', '富时100', '{}'::jsonb, NULL),
        ('巴西IBOVESPA', 'global_index_em', 'index', '巴西IBOVESPA', '{}'::jsonb, NULL),
        ('德国DAX', 'global_index_em', 'index', '德国DAX', '{}'::jsonb, NULL),
        ('标普中国A股大盘红利低波50指数', 'global_index_em', 'index', '标普中国A股大盘红利低波50指数', '{}'::jsonb, NULL),
        ('法国CAC40', 'global_index_em', 'index', '法国CAC40', '{}'::jsonb, NULL),
        ('澳大利亚ASX200', 'global_index_em', 'index', '澳大利亚ASX200', '{}'::jsonb, NULL),
        ('胡志明', 'global_index_em', 'index', '胡志明', '{}'::jsonb, NULL),
        ('荷兰AEX', 'global_index_em', 'index', '荷兰AEX', '{}'::jsonb, NULL),
        ('道琼斯', 'global_index_em', 'index', '道琼斯', '{}'::jsonb, NULL),
        ('韩国KOSPI', 'global_index_em', 'index', '韩国KOSPI', '{}'::jsonb, NULL),
        ('A0', 'cmdty_main_sina', 'commodity', '豆一主力', '{}'::jsonb, NULL),
        ('AG0', 'cmdty_main_sina', 'commodity', '沪银主力', '{}'::jsonb, NULL),
        ('AL0', 'cmdty_main_sina', 'commodity', '沪铝主力', '{}'::jsonb, NULL),
        ('AP0', 'cmdty_main_sina', 'commodity', '苹果主力', '{}'::jsonb, NULL),
        ('AU0', 'cmdty_main_sina', 'commodity', '沪金主力', '{}'::jsonb, NULL),
        ('B0', 'cmdty_main_sina', 'commodity', '豆二主力', '{}'::jsonb, NULL),
        ('BC0', 'cmdty_main_sina', 'commodity', '国际铜主力', '{}'::jsonb, NULL),
        ('BR0', 'cmdty_main_sina', 'commodity', '丁二烯橡胶主力', '{}'::jsonb, NULL),
        ('BU0', 'cmdty_main_sina', 'commodity', '沥青主力', '{}'::jsonb, NULL),
        ('C0', 'cmdty_main_sina', 'commodity', '玉米主力', '{}'::jsonb, NULL),
        ('CF0', 'cmdty_main_sina', 'commodity', '棉花主力', '{}'::jsonb, NULL),
        ('CJ0', 'cmdty_main_sina', 'commodity', '红枣主力', '{}'::jsonb, NULL),
        ('CS0', 'cmdty_main_sina', 'commodity', '玉米淀粉主力', '{}'::jsonb, NULL),
        ('CY0', 'cmdty_main_sina', 'commodity', '棉纱主力', '{}'::jsonb, NULL),
        ('FG0', 'cmdty_main_sina', 'commodity', '玻璃主力', '{}'::jsonb, NULL),
        ('FU0', 'cmdty_main_sina', 'commodity', '燃油主力', '{}'::jsonb, NULL),
        ('HC0', 'cmdty_main_sina', 'commodity', '热卷主力', '{}'::jsonb, NULL),
        ('I0', 'cmdty_main_sina', 'commodity', '铁矿石主力', '{}'::jsonb, NULL),
        ('J0', 'cmdty_main_sina', 'commodity', '焦炭主力', '{}'::jsonb, NULL),
        ('JD0', 'cmdty_main_sina', 'commodity', '鸡蛋主力', '{}'::jsonb, NULL),
        ('JM0', 'cmdty_main_sina', 'commodity', '焦煤主力', '{}'::jsonb, NULL),
        ('L0', 'cmdty_main_sina', 'commodity', '塑料主力', '{}'::jsonb, NULL),
        ('LU0', 'cmdty_main_sina', 'commodity', '低硫燃油主力', '{}'::jsonb, NULL),
        ('NI0', 'cmdty_main_sina', 'commodity', '沪镍主力', '{}'::jsonb, NULL),
        ('NR0', 'cmdty_main_sina', 'commodity', '20号胶主力', '{}'::jsonb, NULL),
        ('OI0', 'cmdty_main_sina', 'commodity', '菜油主力', '{}'::jsonb, NULL),
        ('P0', 'cmdty_main_sina', 'commodity', '棕榈油主力', '{}'::jsonb, NULL),
        ('PB0', 'cmdty_main_sina', 'commodity', '沪铅主力', '{}'::jsonb, NULL),
        ('PF0', 'cmdty_main_sina', 'commodity', '短纤主力', '{}'::jsonb, NULL),
        ('PP0', 'cmdty_main_sina', 'commodity', 'PP主力', '{}'::jsonb, NULL),
        ('RB0', 'cmdty_main_sina', 'commodity', '螺纹钢主力', '{}'::jsonb, NULL),
        ('RI0', 'cmdty_main_sina', 'commodity', '早籼稻主力', '{}'::jsonb, NULL),
        ('RU0', 'cmdty_main_sina', 'commodity', '橡胶主力', '{}'::jsonb, NULL),
        ('SA0', 'cmdty_main_sina', 'commodity', '纯碱主力', '{}'::jsonb, NULL),
        ('SF0', 'cmdty_main_sina', 'commodity', '硅铁主力', '{}'::jsonb, NULL),
        ('SM0', 'cmdty_main_sina', 'commodity', '锰硅主力', '{}'::jsonb, NULL),
        ('SN0', 'cmdty_main_sina', 'commodity', '沪锡主力', '{}'::jsonb, NULL),
        ('SP0', 'cmdty_main_sina', 'commodity', '纸浆主力', '{}'::jsonb, NULL),
        ('SR0', 'cmdty_main_sina', 'commodity', '白糖主力', '{}'::jsonb, NULL),
        ('SS0', 'cmdty_main_sina', 'commodity', '不锈钢主力', '{}'::jsonb, NULL),
        ('TA0', 'cmdty_main_sina', 'commodity', 'PTA主力', '{}'::jsonb, NULL),
        ('UR0', 'cmdty_main_sina', 'commodity', '尿素主力', '{}'::jsonb, NULL),
        ('V0', 'cmdty_main_sina', 'commodity', 'PVC主力', '{}'::jsonb, NULL),
        ('Y0', 'cmdty_main_sina', 'commodity', '豆油主力', '{}'::jsonb, NULL),
        ('ZN0', 'cmdty_main_sina', 'commodity', '沪锌主力', '{}'::jsonb, NULL),
        ('0-10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-10年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-15Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-15年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-1Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-1年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-30Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-30年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-5年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('0-7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-7年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('1-3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(1-3年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('1Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(1年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('2Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(2年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('3-5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(3-5年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(3年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('5-7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(5-7年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(5年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('7-10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(7-10年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(7年)指数', '{"indicator":"财富"}'::jsonb, NULL),
        ('BTC-USD', 'crypto_yfinance', 'crypto', '比特币兑美元', '{}'::jsonb, NULL),
        ('DX-Y.NYB', 'dxy_em', 'forex', '美元指数(DXY)', '{}'::jsonb, NULL),
        ('GC=F', 'gold_comex_em', 'commodity', 'COMEX黄金(GC)', '{}'::jsonb, NULL),
        -- 38: 16 只推荐 ETF(宽基/红利/海外), 全部走 etf_em 后复权(hfq)主源。
        ('510500', 'etf_em', 'etf', '中证500ETF（南方）',       '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('512100', 'etf_em', 'etf', '中证1000ETF（南方）',      '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('588080', 'etf_em', 'etf', '科创50ETF（易方达）',       '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159845', 'etf_em', 'etf', '中证1000ETF（华夏）',       '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('563300', 'etf_em', 'etf', '中证2000ETF华泰柏瑞',       '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159351', 'etf_em', 'etf', 'A500ETF嘉实',              '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('515180', 'etf_em', 'etf', '红利ETF易方达',             '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('515890', 'etf_em', 'etf', '红利ETF博时',               '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159581', 'etf_em', 'etf', '红利ETF万家',               '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('501031', 'etf_em', 'etf', '沪深300红利低波ETF',         '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513520', 'etf_em', 'etf', '日经ETF（华夏）',            '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159866', 'etf_em', 'etf', '日经ETF工银',               '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159870', 'etf_em', 'etf', '化工ETF鹏华',               '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513880', 'etf_em', 'etf', '日经225ETF华安',            '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513300', 'etf_em', 'etf', '纳斯达克ETF（华夏）',        '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('159509', 'etf_em', 'etf', '纳指科技ETF景顺',            '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        -- 44: 推荐清单 4 类共 17 只 ETF(每指数恰好一只场内 ETF, 取「成立最久 → 规模 → 流动性」最优者)。
        -- 下列 11 只为生产库既有、38 号未收录者; start_date 置 NULL, 由 ingest 回写真实首个行情日。
        ('510300', 'etf_em', 'etf', '沪深300ETF（华泰柏瑞）',    '{"adjust":"hfq"}'::jsonb, NULL),
        ('510050', 'etf_em', 'etf', '上证50ETF（华夏）',         '{"adjust":"hfq"}'::jsonb, NULL),
        ('159915', 'etf_em', 'etf', '创业板ETF（易方达）',        '{"adjust":"hfq"}'::jsonb, NULL),
        ('561580', 'etf_em', 'etf', '央企红利ETF华泰柏瑞',        '{"adjust":"hfq"}'::jsonb, NULL),
        ('513630', 'etf_em', 'etf', '摩根标普港股通低波红利指数（摩根ETF）', '{"adjust":"hfq"}'::jsonb, NULL),
        ('159399', 'etf_em', 'etf', '富时中国A股自由现金流聚焦ETF（现金流ETF国泰）', '{"adjust":"hfq"}'::jsonb, NULL),
        ('511260', 'etf_em', 'etf', '上证10年期国债ETF（国泰）',   '{"adjust":"hfq"}'::jsonb, NULL),
        ('511090', 'etf_em', 'etf', '中债-30年期国债ETF（鹏扬）',   '{"adjust":"hfq"}'::jsonb, NULL),
        ('513500', 'etf_em', 'etf', '标普500ETF（博时）',         '{"adjust":"hfq"}'::jsonb, NULL),
        ('513100', 'etf_em', 'etf', '纳斯达克100 ETF（国泰）',     '{"adjust":"hfq"}'::jsonb, NULL),
        ('159920', 'etf_em', 'etf', '恒生指数ETF（华夏）',         '{"adjust":"hfq"}'::jsonb, NULL),
        -- 47: 生产库既有、任何一版 seed 都没有的 16 个品种(10 个 source 组合)。
        -- 字段逐字对齐生产快照。这 16 行的 start_date 写死生产现值 —— 不像 44 段那样
        -- 置 NULL, 否则全新库里这 16 个键的本列会与生产不一致(其余既有品种的 start_date
        -- 仍是 NULL, 由 ingest 回写真实首个行情日, schema.sql 不跑 ingest 无从写入)。
        ('588000', 'cn_index_em', 'etf', '科创50（华夏）',        '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('932365', 'cn_index_em', 'index', '中证自由现金流',      '{"adjust":"bfq"}'::jsonb, DATE '2025-04-10'),
        ('sz159531', 'cn_index_sina', 'index', '中证2000',        '{}'::jsonb, DATE '2017-01-01'),
        ('511580', 'etf_em', 'etf', '中证国债及政策性金融债0-3年ETF（招商）', '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513000', 'etf_em', 'etf', '日经225 ETF（易方达）',       '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513310', 'etf_em', 'etf', '中韩半导体',                 '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('513530', 'etf_em', 'etf', '中证港股通高股息ETF（华泰柏瑞）', '{"adjust":"hfq"}'::jsonb, DATE '2022-04-25'),
        -- 同代码降级源(东财限流时走新浪); 生产两个 source 并存, 此处照搬。
        ('513310', 'etf_sina', 'etf', '中韩半导体ETF',            '{"adjust":"hfq"}'::jsonb, DATE '2017-01-01'),
        ('印度孟买SENSEX', 'global_index_em', 'index', '印度孟买SENSEX', '{"adjust":"bfq"}'::jsonb, DATE '2017-01-02'),
        ('巴西BOVESPA', 'global_index_em', 'index', '巴西BOVESPA',      '{"adjust":"bfq"}'::jsonb, DATE '2017-01-02'),
        ('德国DAX30', 'global_index_em', 'index', '德国DAX30',          '{"adjust":"bfq"}'::jsonb, DATE '2017-01-02'),
        ('澳大利亚标普200', 'global_index_em', 'index', '澳大利亚标普200', '{"adjust":"bfq"}'::jsonb, DATE '2017-01-03'),
        ('纳斯达克', 'global_index_em', 'index', '纳斯达克100',          '{"adjust":"bfq"}'::jsonb, DATE '2017-01-03'),
        ('英国富时100', 'global_index_em', 'index', '英国富时100',       '{"adjust":"bfq"}'::jsonb, DATE '2017-01-03'),
        ('越南胡志明', 'global_index_em', 'index', '越南胡志明',         '{"adjust":"bfq"}'::jsonb, DATE '2017-01-03')
),
normalized AS (
    SELECT
        seed.*,
        (
            (source = 'global_index_em' AND symbol IN (
                '孟买SENSEX', '富时100', '巴西IBOVESPA', '德国DAX',
                '日经225指数', '澳大利亚ASX200', '胡志明',
                '标普中国A股大盘红利低波50指数'
            ))
            OR
            (source = 'bond_csi_treasury' AND symbol IN (
                '1Y', '2Y', '3Y', '5-7Y', '0-7Y', '0-15Y', '0-30Y'
            ))
            -- 47: 以下 8 行生产库里既无配置行也无任何行情(H30352/H30356/RI0 另有孤儿行情,
            -- 但同样没有配置行)。seed 保留它们以记录「这些代码试探过、不可用」, 但必须停用,
            -- 否则全新库的可选池会凭空多出 8 个永远拉不到数据的品种, 与生产不一致。
            -- 已部署环境由 ddl/47_reconcile_asset_pool.sql 逐行停用。
            OR
            (source = 'cn_index_em' AND symbol IN (
                '000309', '399709', '930000', '930842', 'H30352', 'H30356'
            ))
            OR
            (source = 'hk_index_em' AND symbol = 'HSCONSI')
            OR
            (source = 'cmdty_main_sina' AND symbol = 'RI0')
        ) AS disabled,
        -- 47: 以下 4 行的 extra_params 在生产库里是空 {}。非 ETF 的 bfq 兜底对它们不成立
        -- (dxy_em 走 em_push2his_kline、gold_comex_em 走 futures_foreign_hist, fetch 路径
        -- 都不读 extra_params; cn_index_sina 的中证2000 与 hk_index_em 的 HSMSI 同理为 {})。
        -- 写成显式例外而不是依赖兜底, 保证全新库与生产库逐字段一致。
        (
               (source = 'dxy_em'        AND symbol = 'DX-Y.NYB')
            OR (source = 'gold_comex_em' AND symbol = 'GC=F')
            OR (source = 'cn_index_sina' AND symbol = 'sz159531')
            OR (source = 'hk_index_em'   AND symbol = 'HSMSI')
        ) AS params_final
    FROM asset_seed AS seed
)
INSERT INTO bp_index_config
    (symbol, source, category, name, start_date, extra_params, is_deleted, is_selectable)
SELECT
    symbol,
    source,
    category,
    name,
    start_date,
    CASE
        WHEN disabled THEN base_params
        WHEN params_final THEN '{}'::jsonb
        -- 47: 按 category 而非 source 判定 ETF —— 588000(科创50华夏)在生产库里
        -- 就是 category='etf' + source='cn_index_em' 的组合, 口径同为 hfq;
        -- 513310@etf_sina 也由此落到 hfq。凡是 category='etf' 的品种生产库一律 hfq。
        WHEN category = 'etf' THEN base_params || '{"adjust":"hfq"}'::jsonb
        ELSE base_params || '{"adjust":"bfq"}'::jsonb
    END,
    CASE WHEN disabled THEN 1 ELSE 0 END,
    NOT disabled
FROM normalized
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    start_date    = EXCLUDED.start_date,
    extra_params  = EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable;

-- 40: 非法币种标记(新增环境 seed 后执行; 幂等, 顺序保证日经系先 JPY 后不被 USD 覆盖)。
UPDATE bp_index_config SET currency='HKD' WHERE source IN ('hk_index_em','hk_index_sina');
UPDATE bp_index_config SET currency='JPY'
  WHERE source IN ('global_index_em','global_index_sina') AND name LIKE '%日经%';
UPDATE bp_index_config SET currency='USD'
  WHERE source IN ('global_index_em','global_index_sina') AND currency='CNY';
UPDATE bp_index_config SET currency='USD' WHERE source IN ('crypto_yfinance','dxy_em','gold_comex_em');
-- cmdty_main_sina(沪金/沪铜等国内期货主力) 与境内指数/ETF 保持 CNY 默认值

-- 41: 修正 40 的笼统 USD 标记 — 非美元计价的外国指数按实际币种逐 symbol 精确化,
-- 标普中国A股大盘红利低波50指数(A股) 回 CNY。置于上方笼统 USD 语句之后, 最终状态一致。
UPDATE bp_index_config SET currency='RUB'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '俄罗斯RTS';
UPDATE bp_index_config SET currency='INR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '印度孟买SENSEX';
UPDATE bp_index_config SET currency='INR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '孟买SENSEX';
UPDATE bp_index_config SET currency='BRL'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '巴西BOVESPA';
UPDATE bp_index_config SET currency='BRL'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '巴西IBOVESPA';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '德国DAX30';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '德国DAX';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '法国CAC40';
UPDATE bp_index_config SET currency='EUR'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '荷兰AEX';
UPDATE bp_index_config SET currency='AUD'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '澳大利亚标普200';
UPDATE bp_index_config SET currency='AUD'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '澳大利亚ASX200';
UPDATE bp_index_config SET currency='GBP'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '英国富时100';
UPDATE bp_index_config SET currency='GBP'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '富时100';
UPDATE bp_index_config SET currency='VND'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '越南胡志明';
UPDATE bp_index_config SET currency='VND'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '胡志明';
UPDATE bp_index_config SET currency='KRW'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '韩国KOSPI';
UPDATE bp_index_config SET currency='CNY'
 WHERE source IN ('global_index_em','global_index_sina') AND symbol = '标普中国A股大盘红利低波50指数';
-- 不动: 标普500/纳斯达克/道琼斯=USD, 日经225/日经225指数=JPY (40 已正确)。

-- ---------------------------------------------------------------------
-- 43: 汇率折算审计列 + 汇率标的配置行
-- 汇率(新浪人民币汇率口径, 唯一事实源)在清洗阶段把非 CNY 资产折为人民币计价;
-- 标的 is_selectable=FALSE → 不进 /builder 可选池, 但由 bp_ingest.db.fetch_active_configs
-- 的调度路径显式纳入(空 symbols 时 `is_selectable = TRUE OR source = 'fx_sina'`)。
-- 45: 补齐资产池出现过的**全部**外币币种人民币汇率对(实测新浪均可直取)。
--     VND 例外: 新浪报价精度 4 位小数下 VNDCNY 恒为 0.0000, 不可用 → 不种, 该资产
--     继续抛 MissingFxRate 并由 bp_asset_data_status.last_error 暴露, 绝不静默以原币混入。
-- ---------------------------------------------------------------------
ALTER TABLE bp_quote_clean ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,8);

COMMENT ON COLUMN bp_quote_clean.fx_rate IS
    '折算所用汇率(外币→CNY)。CNY 资产为 1；无汇率日为 NULL。close 列已是折算后的人民币价格。';

INSERT INTO bp_index_config
    (symbol, source, category, name, extra_params, is_deleted, is_selectable, currency)
VALUES
    ('USDCNY', 'fx_sina', 'forex', '美元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('HKDCNY', 'fx_sina', 'forex', '港币兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('JPYCNY', 'fx_sina', 'forex', '日元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('EURCNY', 'fx_sina', 'forex', '欧元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('GBPCNY', 'fx_sina', 'forex', '英镑兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('AUDCNY', 'fx_sina', 'forex', '澳元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('KRWCNY', 'fx_sina', 'forex', '韩元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('INRCNY', 'fx_sina', 'forex', '印度卢比兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('RUBCNY', 'fx_sina', 'forex', '卢布兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('BRLCNY', 'fx_sina', 'forex', '雷亚尔兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY')
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    extra_params  = EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable,
    currency      = EXCLUDED.currency;

-- ---------------------------------------------------------------------
-- 46: 同步组合侧 display_name
-- 44 号纠正了 bp_index_config.name(18 条 ETF 名称/错配), 但 bp_portfolio_asset.display_name
-- 是组合侧展示缓存, 当年照抄了错误名 → 不改就出现「管理端显示正确、组合里显示错误」。
-- 46 号只在组合侧 display_name 与旧错误名**完全一致**时改写(不覆盖用户手工起的别名),
-- 且仅限 44 号改过的那批 symbol。全新环境由 44 段直接写入正确名称, 无需回填。
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- 47: 资产池与生产库对齐(seed 侧)。已部署环境的同款修复见 ddl/47_reconcile_asset_pool.sql。
-- 语义见该文件头注释; schema.sql 侧只需保证「全新库 seed 结果 == 生产现状」。
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- Demo portfolio seed. No account or personal email is hard-coded.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    v_pid BIGINT;
BEGIN
    SELECT portfolio_id
      INTO v_pid
      FROM bp_portfolio
     WHERE is_demo = TRUE
       AND name = '示例组合 (Demo)'
     ORDER BY portfolio_id
     LIMIT 1;

    IF v_pid IS NULL THEN
        INSERT INTO bp_portfolio
            (name, method, ratio, lookback_days, start_date,
             benchmark_symbol, benchmark_source, is_demo, status)
        VALUES
            ('示例组合 (Demo)', 'quadrant_inner_sharpe_outer_rp', 'sharpe', 156,
             (CURRENT_DATE - INTERVAL '3 years')::date,
             '000300', 'cn_index_em', TRUE, 'pending')
        RETURNING portfolio_id INTO v_pid;
    END IF;

    INSERT INTO bp_portfolio_asset
        (portfolio_id, symbol, source, quadrant, display_name, sort_order)
    VALUES
        (v_pid, '000510', 'cn_index_em',      'overheat',    '中证A500', 1),
        (v_pid, 'SC0',    'cmdty_main_sina',  'overheat',    '原油主力', 2),
        (v_pid, '标普500', 'global_index_em', 'stagflation', '标普500',  3),
        (v_pid, '518880', 'etf_em',           'stagflation', '黄金ETF',  4),
        (v_pid, '000825', 'cn_index_em',      'recovery',    '央企红利', 5),
        (v_pid, '10Y',    'bond_csi_treasury','recession',   '10年国债', 6)
    ON CONFLICT (portfolio_id, symbol, source, quadrant) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        sort_order   = EXCLUDED.sort_order;
END;
$$;

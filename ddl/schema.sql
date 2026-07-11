-- =====================================================================
-- Balanced Portfolio - consolidated schema
-- Target: PostgreSQL 18 + TimescaleDB >= 2.23
-- Equivalent to applying legacy migrations 01-32 to an empty database.
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
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_bp_data_source_updated_at ON bp_data_source;
CREATE TRIGGER trg_bp_data_source_updated_at
    BEFORE UPDATE ON bp_data_source
    FOR EACH ROW EXECUTE FUNCTION bp_set_updated_at();

INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume,
     supports_date_range, symbol_hint, vendor)
VALUES
    ('cn_index_em',       'A股/中证指数-东财通用(字段最全, 含成交额/换手率/涨跌幅, 默认推荐)', 'index_zh_a_hist',           'cn_index',     TRUE,  TRUE,  '无市场前缀, 如 000300 / 930914', '东财'),
    ('cn_index_sina',     'A股指数-新浪',                                                    'stock_zh_index_daily',      'cn_index',     TRUE,  FALSE, '带市场前缀, 如 sh000300 / sz399552', '新浪'),
    ('cn_index_tx',       'A股指数-腾讯(支持日期范围)',                                       'stock_zh_index_daily_tx',   'cn_index',     FALSE, TRUE,  '带市场前缀, 如 sh000001', '腾讯'),
    ('cn_index_em_px',    'A股指数-东财(带前缀/csi)',                                         'stock_zh_index_daily_em',   'cn_index',     TRUE,  TRUE,  '带前缀, 如 sh000300 / csi000905', '东财'),
    ('hk_index_em',       '港股指数-东财(close=最新价, 无成交量)',                             'stock_hk_index_daily_em',   'hk_index',     FALSE, FALSE, 'symbol 如 HSI / HSTECF2L, 见 stock_hk_index_spot_em', '东财'),
    ('hk_index_sina',     '港股指数-新浪(含成交量)',                                          'stock_hk_index_daily_sina', 'hk_index',     TRUE,  FALSE, 'symbol 如 CES100', '新浪'),
    ('global_index_em',   '全球指数-东财(中文名 symbol, close=最新价, 无成交量)',              'index_global_hist_em',      'global_index', FALSE, FALSE, '中文名, 如 标普500 / 日经225, 见 index_global_spot_em', '东财'),
    ('global_index_sina', '全球指数-新浪(中文名 symbol, 近1000条)',                            'index_global_hist_sina',    'global_index', TRUE,  FALSE, '中文名, 见 index_global_name_table', '新浪'),
    ('cmdty_main_sina',   '商品期货主力连续合约-新浪(OHLCV)',                                  'futures_main_sina',         'commodity',    TRUE,  TRUE,  '合约代码, 如 M0/CU0/MA0, 见 futures_display_main_sina', '新浪'),
    ('bond_csi_treasury', '中债国债指数(财富/全收益)',                                         'bond_treasury_index_cbond', 'bond',         FALSE, FALSE, '期限标识, 如 10Y / 30Y / 0-3Y', '中债'),
    ('etf_em',            'ETF行情-东财(后复权)',                                             'fund_etf_hist_em',          'etf',          TRUE,  TRUE,  'ETF代码, 如 518880(黄金ETF)', '东财'),
    ('etf_sina',          'ETF行情-新浪(全量, 自动加市场前缀)',                                 'fund_etf_hist_sina',        'etf',          TRUE,  FALSE, 'ETF代码, 如 510050 / 518880(自动加 sh/sz 前缀)', '新浪'),
    ('futures_cffex',     '中金所期货日行情(IF/IH/IC/IM)',                                    'get_futures_daily',         'futures',      TRUE,  TRUE,  '品种代码如 IF/IH/IC/IM', '中金所')
ON CONFLICT (code) DO UPDATE SET
    description         = EXCLUDED.description,
    akshare_func        = EXCLUDED.akshare_func,
    asset_class         = EXCLUDED.asset_class,
    has_volume          = EXCLUDED.has_volume,
    supports_date_range = EXCLUDED.supports_date_range,
    symbol_hint         = EXCLUDED.symbol_hint,
    vendor              = EXCLUDED.vendor;

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
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_bp_index_config_symbol_source UNIQUE (symbol, source),
    CONSTRAINT uq_bp_index_config_row_hash UNIQUE (row_hash),
    CONSTRAINT ck_bp_index_config_is_deleted CHECK (is_deleted IN (0, 1))
);

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
    portfolio_limit INTEGER     NOT NULL DEFAULT 3,
    totp_enabled    BOOLEAN     NOT NULL DEFAULT FALSE,
    totp_secret     TEXT,
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
    params               JSONB        NOT NULL DEFAULT '{}'::jsonb,
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
    portfolio_id BIGINT NOT NULL REFERENCES bp_portfolio(portfolio_id) ON DELETE CASCADE,
    method       TEXT   NOT NULL,
    payload      JSONB  NOT NULL,
    CONSTRAINT pk_bp_backtest_attribution PRIMARY KEY (portfolio_id, method)
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
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_bp_asset_data_status PRIMARY KEY (symbol, source)
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
WITH asset_seed (symbol, source, category, name, base_params) AS (
    VALUES
        ('000300', 'cn_index_em', 'index', '沪深300', '{}'::jsonb),
        ('000905', 'cn_index_em', 'index', '中证500', '{}'::jsonb),
        ('000852', 'cn_index_em', 'index', '中证1000', '{}'::jsonb),
        ('000688', 'cn_index_em', 'index', '科创50', '{}'::jsonb),
        ('000510', 'cn_index_em', 'index', '中证A500', '{}'::jsonb),
        ('930914', 'cn_index_em', 'index', '中证港股通高股息', '{}'::jsonb),
        ('000825', 'cn_index_em', 'index', '央企红利', '{}'::jsonb),
        ('931722', 'cn_index_em', 'index', '国新港股通央企红利', '{}'::jsonb),
        ('HSI', 'hk_index_em', 'index', '恒生指数', '{}'::jsonb),
        ('标普500', 'global_index_em', 'index', '标普500', '{}'::jsonb),
        ('日经225', 'global_index_em', 'index', '日经225', '{}'::jsonb),
        ('CU0', 'cmdty_main_sina', 'commodity', '沪铜主力(有色代表, 替上期有色)', '{}'::jsonb),
        ('MA0', 'cmdty_main_sina', 'commodity', '甲醇主力(能化代表, 替易盛能化)', '{}'::jsonb),
        ('M0', 'cmdty_main_sina', 'commodity', '豆粕主力', '{}'::jsonb),
        ('SC0', 'cmdty_main_sina', 'commodity', '原油主力(INE)', '{}'::jsonb),
        ('10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(10年)指数', '{"indicator":"财富"}'::jsonb),
        ('30Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(30年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-3年)指数', '{"indicator":"财富"}'::jsonb),
        ('518880', 'etf_em', 'etf', '黄金ETF(华安)', '{"adjust":"hfq"}'::jsonb),
        ('000001', 'cn_index_em', 'index', '上证综合指数', '{}'::jsonb),
        ('000010', 'cn_index_em', 'index', '上证180指数', '{}'::jsonb),
        ('000015', 'cn_index_em', 'index', '上证红利指数', '{}'::jsonb),
        ('000016', 'cn_index_em', 'index', '上证50指数', '{}'::jsonb),
        ('000309', 'cn_index_em', 'index', '上证380指数', '{}'::jsonb),
        ('000698', 'cn_index_em', 'index', '上证科创板100指数', '{}'::jsonb),
        ('000814', 'cn_index_em', 'index', '中证国有企业红利指数', '{}'::jsonb),
        ('000846', 'cn_index_em', 'index', '中证ESG100指数', '{}'::jsonb),
        ('000903', 'cn_index_em', 'index', '中证100指数', '{}'::jsonb),
        ('000904', 'cn_index_em', 'index', '中证200指数', '{}'::jsonb),
        ('000906', 'cn_index_em', 'index', '中证800指数', '{}'::jsonb),
        ('000907', 'cn_index_em', 'index', '中证700指数', '{}'::jsonb),
        ('000918', 'cn_index_em', 'index', '沪深300成长指数', '{}'::jsonb),
        ('000919', 'cn_index_em', 'index', '中证医药卫生指数', '{}'::jsonb),
        ('000922', 'cn_index_em', 'index', '中证红利指数', '{}'::jsonb),
        ('000925', 'cn_index_em', 'index', '中证锐联基本面50指数', '{}'::jsonb),
        ('000931', 'cn_index_em', 'index', '中证全指可选消费指数', '{}'::jsonb),
        ('000932', 'cn_index_em', 'index', '中证主要消费指数', '{}'::jsonb),
        ('000933', 'cn_index_em', 'index', '中证全指医药卫生指数', '{}'::jsonb),
        ('000935', 'cn_index_em', 'index', '中证全指信息技术指数', '{}'::jsonb),
        ('000949', 'cn_index_em', 'index', '中证金融地产指数', '{}'::jsonb),
        ('000974', 'cn_index_em', 'index', '中证800金融指数', '{}'::jsonb),
        ('000982', 'cn_index_em', 'index', '中证500等权重指数', '{}'::jsonb),
        ('000984', 'cn_index_em', 'index', '沪深300等权重指数', '{}'::jsonb),
        ('399001', 'cn_index_em', 'index', '深证成份指数', '{}'::jsonb),
        ('399006', 'cn_index_em', 'index', '创业板指数', '{}'::jsonb),
        ('399324', 'cn_index_em', 'index', '深证红利指数', '{}'::jsonb),
        ('399330', 'cn_index_em', 'index', '深证100指数', '{}'::jsonb),
        ('399368', 'cn_index_em', 'index', '深证300指数', '{}'::jsonb),
        ('399378', 'cn_index_em', 'index', '国证ESG300指数', '{}'::jsonb),
        ('399673', 'cn_index_em', 'index', '创业板50指数', '{}'::jsonb),
        ('399709', 'cn_index_em', 'index', '深证基本面60指数', '{}'::jsonb),
        ('399808', 'cn_index_em', 'index', '中证新能源指数', '{}'::jsonb),
        ('399812', 'cn_index_em', 'index', '中证养老产业指数', '{}'::jsonb),
        ('399974', 'cn_index_em', 'index', '中证国有企业改革指数', '{}'::jsonb),
        ('399976', 'cn_index_em', 'index', '中证新能源汽车指数', '{}'::jsonb),
        ('399977', 'cn_index_em', 'index', '中证内地低碳经济主题指数', '{}'::jsonb),
        ('399986', 'cn_index_em', 'index', '中证银行指数', '{}'::jsonb),
        ('399991', 'cn_index_em', 'index', '国证一带一路指数', '{}'::jsonb),
        ('399997', 'cn_index_em', 'index', '中证白酒指数', '{}'::jsonb),
        ('930000', 'cn_index_em', 'index', '中证A100指数', '{}'::jsonb),
        ('930009', 'cn_index_em', 'index', '中证机器人产业指数', '{}'::jsonb),
        ('930050', 'cn_index_em', 'index', '中证A50指数', '{}'::jsonb),
        ('930091', 'cn_index_em', 'index', '中证民营企业红利指数', '{}'::jsonb),
        ('930104', 'cn_index_em', 'index', '中证全指证券公司指数', '{}'::jsonb),
        ('930651', 'cn_index_em', 'index', '中证计算机主题指数', '{}'::jsonb),
        ('930653', 'cn_index_em', 'index', '中证食品饮料指数', '{}'::jsonb),
        ('930697', 'cn_index_em', 'index', '中证家电指数', '{}'::jsonb),
        ('930713', 'cn_index_em', 'index', '中证人工智能主题指数', '{}'::jsonb),
        ('930719', 'cn_index_em', 'index', '中证证券公司指数', '{}'::jsonb),
        ('930758', 'cn_index_em', 'index', '中证生物医药指数', '{}'::jsonb),
        ('930782', 'cn_index_em', 'index', '中证沪港深红利低波动指数', '{}'::jsonb),
        ('930788', 'cn_index_em', 'index', '中证智能汽车主题指数', '{}'::jsonb),
        ('930842', 'cn_index_em', 'index', '中证保险主题指数', '{}'::jsonb),
        ('930875', 'cn_index_em', 'index', '中证A800指数', '{}'::jsonb),
        ('930901', 'cn_index_em', 'index', '中证传媒指数', '{}'::jsonb),
        ('930902', 'cn_index_em', 'index', '中证大数据产业指数', '{}'::jsonb),
        ('930916', 'cn_index_em', 'index', '中证医疗指数', '{}'::jsonb),
        ('930950', 'cn_index_em', 'index', '中证红利潜力指数', '{}'::jsonb),
        ('930955', 'cn_index_em', 'index', '中证红利低波动100指数', '{}'::jsonb),
        ('930997', 'cn_index_em', 'index', '中证新能源汽车产业指数', '{}'::jsonb),
        ('931071', 'cn_index_em', 'index', '中证物联网主题指数', '{}'::jsonb),
        ('931079', 'cn_index_em', 'index', '中证5G通信主题指数', '{}'::jsonb),
        ('931151', 'cn_index_em', 'index', '中证光伏产业指数', '{}'::jsonb),
        ('931152', 'cn_index_em', 'index', '中证上海环交所碳中和指数', '{}'::jsonb),
        ('931160', 'cn_index_em', 'index', '中证芯片产业指数', '{}'::jsonb),
        ('931468', 'cn_index_em', 'index', '中证云计算主题指数', '{}'::jsonb),
        ('931590', 'cn_index_em', 'index', '中证锂电池指数', '{}'::jsonb),
        ('931643', 'cn_index_em', 'index', '中证科创创业50指数', '{}'::jsonb),
        ('931768', 'cn_index_em', 'index', '中证红利低波动50指数', '{}'::jsonb),
        ('931775', 'cn_index_em', 'index', '中证全指房地产指数', '{}'::jsonb),
        ('931865', 'cn_index_em', 'index', '中证半导体产业指数', '{}'::jsonb),
        ('932000', 'cn_index_em', 'index', '中证2000指数', '{}'::jsonb),
        ('932051', 'cn_index_em', 'index', '中证现金流指数', '{}'::jsonb),
        ('932351', 'cn_index_em', 'index', '中证全指自由现金流指数', '{}'::jsonb),
        ('980092', 'cn_index_em', 'index', '国证自由现金流指数', '{}'::jsonb),
        ('H30269', 'cn_index_em', 'index', '中证红利低波动指数', '{}'::jsonb),
        ('H30352', 'cn_index_em', 'index', '中证500价值指数', '{}'::jsonb),
        ('H30356', 'cn_index_em', 'index', '中证800价值指数', '{}'::jsonb),
        ('159653', 'etf_em', 'etf', 'ESG300ETF国联安', '{"adjust":"hfq"}'::jsonb),
        ('159755', 'etf_em', 'etf', '广发国证新能源车电池ETF', '{"adjust":"hfq"}'::jsonb),
        ('159781', 'etf_em', 'etf', '科创创业ETF易方达', '{"adjust":"hfq"}'::jsonb),
        ('159790', 'etf_em', 'etf', '华夏中证内地低碳经济主题ETF', '{"adjust":"hfq"}'::jsonb),
        ('159819', 'etf_em', 'etf', '人工智能ETF易方达', '{"adjust":"hfq"}'::jsonb),
        ('159901', 'etf_em', 'etf', '深证100ETF易方达', '{"adjust":"hfq"}'::jsonb),
        ('159905', 'etf_em', 'etf', '红利ETF工银', '{"adjust":"hfq"}'::jsonb),
        ('159916', 'etf_em', 'etf', '基本面ETF建信', '{"adjust":"hfq"}'::jsonb),
        ('159928', 'etf_em', 'etf', '汇添富中证主要消费ETF', '{"adjust":"hfq"}'::jsonb),
        ('159936', 'etf_em', 'etf', '广发中证全指可选消费ETF', '{"adjust":"hfq"}'::jsonb),
        ('159939', 'etf_em', 'etf', '广发中证全指信息技术ETF', '{"adjust":"hfq"}'::jsonb),
        ('159943', 'etf_em', 'etf', '广发中证全指医药卫生ETF', '{"adjust":"hfq"}'::jsonb),
        ('159949', 'etf_em', 'etf', '创业板50ETF华安', '{"adjust":"hfq"}'::jsonb),
        ('159985', 'etf_em', 'etf', '豆粕ETF(华夏)', '{"adjust":"hfq"}'::jsonb),
        ('159995', 'etf_em', 'etf', '芯片ETF华夏', '{"adjust":"hfq"}'::jsonb),
        ('159996', 'etf_em', 'etf', '易方达中证家电ETF', '{"adjust":"hfq"}'::jsonb),
        ('159997', 'etf_em', 'etf', '广发中证电子ETF', '{"adjust":"hfq"}'::jsonb),
        ('161129', 'etf_em', 'etf', '易方达原油A', '{"adjust":"hfq"}'::jsonb),
        ('161226', 'etf_em', 'etf', '国投瑞银白银期货(LOF)A', '{"adjust":"hfq"}'::jsonb),
        ('161725', 'etf_em', 'etf', '鹏华中证白酒(LOF)', '{"adjust":"hfq"}'::jsonb),
        ('164824', 'etf_em', 'etf', '印度基金LOF工银瑞信', '{"adjust":"hfq"}'::jsonb),
        ('510180', 'etf_em', 'etf', '上证180ETF华安', '{"adjust":"hfq"}'::jsonb),
        ('510210', 'etf_em', 'etf', '上证指数ETF富国', '{"adjust":"hfq"}'::jsonb),
        ('510880', 'etf_em', 'etf', '红利ETF华泰柏瑞', '{"adjust":"hfq"}'::jsonb),
        ('510900', 'etf_em', 'etf', '恒生中国企业ETF易方达', '{"adjust":"hfq"}'::jsonb),
        ('511010', 'etf_em', 'etf', '国债ETF国泰', '{"adjust":"hfq"}'::jsonb),
        ('511020', 'etf_em', 'etf', '国债ETF平安', '{"adjust":"hfq"}'::jsonb),
        ('511030', 'etf_em', 'etf', '公司债ETF平安', '{"adjust":"hfq"}'::jsonb),
        ('511180', 'etf_em', 'etf', '可转债ETF海富通', '{"adjust":"hfq"}'::jsonb),
        ('511220', 'etf_em', 'etf', '城投债ETF海富通', '{"adjust":"hfq"}'::jsonb),
        ('511360', 'etf_em', 'etf', '短融ETF海富通', '{"adjust":"hfq"}'::jsonb),
        ('511380', 'etf_em', 'etf', '可转债ETF博时', '{"adjust":"hfq"}'::jsonb),
        ('511520', 'etf_em', 'etf', '政金债ETF富国', '{"adjust":"hfq"}'::jsonb),
        ('512010', 'etf_em', 'etf', '易方达中证医药ETF', '{"adjust":"hfq"}'::jsonb),
        ('512170', 'etf_em', 'etf', '易方达医疗ETF', '{"adjust":"hfq"}'::jsonb),
        ('512200', 'etf_em', 'etf', '房地产ETF南方', '{"adjust":"hfq"}'::jsonb),
        ('512260', 'etf_em', 'etf', '中证500低波动ETF华安', '{"adjust":"hfq"}'::jsonb),
        ('512400', 'etf_em', 'etf', '有色金属ETF(南方)', '{"adjust":"hfq"}'::jsonb),
        ('512480', 'etf_em', 'etf', '半导体ETF国联安', '{"adjust":"hfq"}'::jsonb),
        ('512640', 'etf_em', 'etf', '金融地产ETF嘉实', '{"adjust":"hfq"}'::jsonb),
        ('512720', 'etf_em', 'etf', '广发中证计算机主题ETF', '{"adjust":"hfq"}'::jsonb),
        ('512750', 'etf_em', 'etf', '基本面50ETF嘉实', '{"adjust":"hfq"}'::jsonb),
        ('512800', 'etf_em', 'etf', '银行ETF华宝', '{"adjust":"hfq"}'::jsonb),
        ('512880', 'etf_em', 'etf', '证券ETF国泰', '{"adjust":"hfq"}'::jsonb),
        ('512890', 'etf_em', 'etf', '红利低波ETF华泰柏瑞', '{"adjust":"hfq"}'::jsonb),
        ('512980', 'etf_em', 'etf', '鹏华中证传媒ETF', '{"adjust":"hfq"}'::jsonb),
        ('513030', 'etf_em', 'etf', '德国DAX30ETF华安', '{"adjust":"hfq"}'::jsonb),
        ('513060', 'etf_em', 'etf', '恒生医疗ETF博时', '{"adjust":"hfq"}'::jsonb),
        ('513080', 'etf_em', 'etf', '法国CAC40ETF华安', '{"adjust":"hfq"}'::jsonb),
        ('513180', 'etf_em', 'etf', '恒生科技ETF华夏', '{"adjust":"hfq"}'::jsonb),
        ('513330', 'etf_em', 'etf', '恒生互联网ETF华夏', '{"adjust":"hfq"}'::jsonb),
        ('515030', 'etf_em', 'etf', '华夏中证新能源汽车ETF', '{"adjust":"hfq"}'::jsonb),
        ('515050', 'etf_em', 'etf', '通信ETF华夏', '{"adjust":"hfq"}'::jsonb),
        ('515080', 'etf_em', 'etf', '中证红利ETF招商', '{"adjust":"hfq"}'::jsonb),
        ('515100', 'etf_em', 'etf', '红利低波100ETF景顺', '{"adjust":"hfq"}'::jsonb),
        ('515150', 'etf_em', 'etf', '一带一路ETF富国', '{"adjust":"hfq"}'::jsonb),
        ('515170', 'etf_em', 'etf', '鹏华中证食品饮料ETF', '{"adjust":"hfq"}'::jsonb),
        ('515230', 'etf_em', 'etf', '嘉实中证软件服务ETF', '{"adjust":"hfq"}'::jsonb),
        ('515250', 'etf_em', 'etf', '智能汽车ETF富国', '{"adjust":"hfq"}'::jsonb),
        ('515290', 'etf_em', 'etf', '易方达中证生物医药ETF', '{"adjust":"hfq"}'::jsonb),
        ('515400', 'etf_em', 'etf', '大数据ETF富国', '{"adjust":"hfq"}'::jsonb),
        ('515450', 'etf_em', 'etf', '红利低波50ETF南方', '{"adjust":"hfq"}'::jsonb),
        ('515590', 'etf_em', 'etf', '500等权ETF前海开源', '{"adjust":"hfq"}'::jsonb),
        ('515700', 'etf_em', 'etf', '平安中证新能源汽车产业ETF', '{"adjust":"hfq"}'::jsonb),
        ('515790', 'etf_em', 'etf', '华泰柏瑞中证光伏产业ETF', '{"adjust":"hfq"}'::jsonb),
        ('515800', 'etf_em', 'etf', '中证800ETF汇添富', '{"adjust":"hfq"}'::jsonb),
        ('515910', 'etf_em', 'etf', '质量ETF中金', '{"adjust":"hfq"}'::jsonb),
        ('516160', 'etf_em', 'etf', '南方中证新能源ETF', '{"adjust":"hfq"}'::jsonb),
        ('516510', 'etf_em', 'etf', '云计算ETF易方达', '{"adjust":"hfq"}'::jsonb),
        ('516560', 'etf_em', 'etf', '养老ETF华宝', '{"adjust":"hfq"}'::jsonb),
        ('560030', 'etf_em', 'etf', '800价值ETF汇添富', '{"adjust":"hfq"}'::jsonb),
        ('562310', 'etf_em', 'etf', '沪深300成长ETF银华', '{"adjust":"hfq"}'::jsonb),
        ('562320', 'etf_em', 'etf', '沪深300价值ETF银华', '{"adjust":"hfq"}'::jsonb),
        ('562330', 'etf_em', 'etf', '中证500价值ETF银华', '{"adjust":"hfq"}'::jsonb),
        ('562500', 'etf_em', 'etf', '机器人ETF华夏', '{"adjust":"hfq"}'::jsonb),
        ('562990', 'etf_em', 'etf', '易方达中证上海环交所碳中和ETF', '{"adjust":"hfq"}'::jsonb),
        ('HSAHP', 'hk_index_em', 'index', '恒生AH股溢价指数', '{}'::jsonb),
        ('HSCEI', 'hk_index_em', 'index', '恒生中国企业指数', '{}'::jsonb),
        ('HSCONSI', 'hk_index_em', 'index', '恒生消费指数', '{}'::jsonb),
        ('HSHCI', 'hk_index_em', 'index', '恒生医疗保健指数', '{}'::jsonb),
        ('HSHDYI', 'hk_index_em', 'index', '恒生高股息率指数', '{}'::jsonb),
        ('HSIII', 'hk_index_em', 'index', '恒生互联网科技业指数', '{}'::jsonb),
        ('HSISC', 'hk_index_em', 'index', '恒生港股通指数', '{}'::jsonb),
        ('HSSCI', 'hk_index_em', 'index', '恒生综合中小型股指数', '{}'::jsonb),
        ('HSTECH', 'hk_index_em', 'index', '恒生科技指数', '{}'::jsonb),
        ('俄罗斯RTS', 'global_index_em', 'index', '俄罗斯RTS', '{}'::jsonb),
        ('孟买SENSEX', 'global_index_em', 'index', '孟买SENSEX', '{}'::jsonb),
        ('富时100', 'global_index_em', 'index', '富时100', '{}'::jsonb),
        ('巴西IBOVESPA', 'global_index_em', 'index', '巴西IBOVESPA', '{}'::jsonb),
        ('德国DAX', 'global_index_em', 'index', '德国DAX', '{}'::jsonb),
        ('标普中国A股大盘红利低波50指数', 'global_index_em', 'index', '标普中国A股大盘红利低波50指数', '{}'::jsonb),
        ('法国CAC40', 'global_index_em', 'index', '法国CAC40', '{}'::jsonb),
        ('澳大利亚ASX200', 'global_index_em', 'index', '澳大利亚ASX200', '{}'::jsonb),
        ('胡志明', 'global_index_em', 'index', '胡志明', '{}'::jsonb),
        ('荷兰AEX', 'global_index_em', 'index', '荷兰AEX', '{}'::jsonb),
        ('道琼斯', 'global_index_em', 'index', '道琼斯', '{}'::jsonb),
        ('韩国KOSPI', 'global_index_em', 'index', '韩国KOSPI', '{}'::jsonb),
        ('A0', 'cmdty_main_sina', 'commodity', '豆一主力', '{}'::jsonb),
        ('AG0', 'cmdty_main_sina', 'commodity', '沪银主力', '{}'::jsonb),
        ('AL0', 'cmdty_main_sina', 'commodity', '沪铝主力', '{}'::jsonb),
        ('AP0', 'cmdty_main_sina', 'commodity', '苹果主力', '{}'::jsonb),
        ('AU0', 'cmdty_main_sina', 'commodity', '沪金主力', '{}'::jsonb),
        ('B0', 'cmdty_main_sina', 'commodity', '豆二主力', '{}'::jsonb),
        ('BC0', 'cmdty_main_sina', 'commodity', '国际铜主力', '{}'::jsonb),
        ('BR0', 'cmdty_main_sina', 'commodity', '丁二烯橡胶主力', '{}'::jsonb),
        ('BU0', 'cmdty_main_sina', 'commodity', '沥青主力', '{}'::jsonb),
        ('C0', 'cmdty_main_sina', 'commodity', '玉米主力', '{}'::jsonb),
        ('CF0', 'cmdty_main_sina', 'commodity', '棉花主力', '{}'::jsonb),
        ('CJ0', 'cmdty_main_sina', 'commodity', '红枣主力', '{}'::jsonb),
        ('CS0', 'cmdty_main_sina', 'commodity', '玉米淀粉主力', '{}'::jsonb),
        ('CY0', 'cmdty_main_sina', 'commodity', '棉纱主力', '{}'::jsonb),
        ('FG0', 'cmdty_main_sina', 'commodity', '玻璃主力', '{}'::jsonb),
        ('FU0', 'cmdty_main_sina', 'commodity', '燃油主力', '{}'::jsonb),
        ('HC0', 'cmdty_main_sina', 'commodity', '热卷主力', '{}'::jsonb),
        ('I0', 'cmdty_main_sina', 'commodity', '铁矿石主力', '{}'::jsonb),
        ('J0', 'cmdty_main_sina', 'commodity', '焦炭主力', '{}'::jsonb),
        ('JD0', 'cmdty_main_sina', 'commodity', '鸡蛋主力', '{}'::jsonb),
        ('JM0', 'cmdty_main_sina', 'commodity', '焦煤主力', '{}'::jsonb),
        ('L0', 'cmdty_main_sina', 'commodity', '塑料主力', '{}'::jsonb),
        ('LU0', 'cmdty_main_sina', 'commodity', '低硫燃油主力', '{}'::jsonb),
        ('NI0', 'cmdty_main_sina', 'commodity', '沪镍主力', '{}'::jsonb),
        ('NR0', 'cmdty_main_sina', 'commodity', '20号胶主力', '{}'::jsonb),
        ('OI0', 'cmdty_main_sina', 'commodity', '菜油主力', '{}'::jsonb),
        ('P0', 'cmdty_main_sina', 'commodity', '棕榈油主力', '{}'::jsonb),
        ('PB0', 'cmdty_main_sina', 'commodity', '沪铅主力', '{}'::jsonb),
        ('PF0', 'cmdty_main_sina', 'commodity', '短纤主力', '{}'::jsonb),
        ('PP0', 'cmdty_main_sina', 'commodity', 'PP主力', '{}'::jsonb),
        ('RB0', 'cmdty_main_sina', 'commodity', '螺纹钢主力', '{}'::jsonb),
        ('RI0', 'cmdty_main_sina', 'commodity', '早籼稻主力', '{}'::jsonb),
        ('RU0', 'cmdty_main_sina', 'commodity', '橡胶主力', '{}'::jsonb),
        ('SA0', 'cmdty_main_sina', 'commodity', '纯碱主力', '{}'::jsonb),
        ('SF0', 'cmdty_main_sina', 'commodity', '硅铁主力', '{}'::jsonb),
        ('SM0', 'cmdty_main_sina', 'commodity', '锰硅主力', '{}'::jsonb),
        ('SN0', 'cmdty_main_sina', 'commodity', '沪锡主力', '{}'::jsonb),
        ('SP0', 'cmdty_main_sina', 'commodity', '纸浆主力', '{}'::jsonb),
        ('SR0', 'cmdty_main_sina', 'commodity', '白糖主力', '{}'::jsonb),
        ('SS0', 'cmdty_main_sina', 'commodity', '不锈钢主力', '{}'::jsonb),
        ('TA0', 'cmdty_main_sina', 'commodity', 'PTA主力', '{}'::jsonb),
        ('UR0', 'cmdty_main_sina', 'commodity', '尿素主力', '{}'::jsonb),
        ('V0', 'cmdty_main_sina', 'commodity', 'PVC主力', '{}'::jsonb),
        ('Y0', 'cmdty_main_sina', 'commodity', '豆油主力', '{}'::jsonb),
        ('ZN0', 'cmdty_main_sina', 'commodity', '沪锌主力', '{}'::jsonb),
        ('0-10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-10年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-15Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-15年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-1Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-1年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-30Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-30年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-5年)指数', '{"indicator":"财富"}'::jsonb),
        ('0-7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(0-7年)指数', '{"indicator":"财富"}'::jsonb),
        ('1-3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(1-3年)指数', '{"indicator":"财富"}'::jsonb),
        ('1Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(1年)指数', '{"indicator":"财富"}'::jsonb),
        ('2Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(2年)指数', '{"indicator":"财富"}'::jsonb),
        ('3-5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(3-5年)指数', '{"indicator":"财富"}'::jsonb),
        ('3Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(3年)指数', '{"indicator":"财富"}'::jsonb),
        ('5-7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(5-7年)指数', '{"indicator":"财富"}'::jsonb),
        ('5Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(5年)指数', '{"indicator":"财富"}'::jsonb),
        ('7-10Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(7-10年)指数', '{"indicator":"财富"}'::jsonb),
        ('7Y', 'bond_csi_treasury', 'bond', '中债-国债总财富(7年)指数', '{"indicator":"财富"}'::jsonb)
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
        ) AS disabled
    FROM asset_seed AS seed
)
INSERT INTO bp_index_config
    (symbol, source, category, name, extra_params, is_deleted, is_selectable)
SELECT
    symbol,
    source,
    category,
    name,
    CASE
        WHEN disabled THEN base_params
        WHEN source = 'etf_em' THEN base_params || '{"adjust":"hfq"}'::jsonb
        ELSE base_params || '{"adjust":"bfq"}'::jsonb
    END,
    CASE WHEN disabled THEN 1 ELSE 0 END,
    NOT disabled
FROM normalized
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    extra_params  = EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable;

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

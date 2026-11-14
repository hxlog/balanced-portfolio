-- =====================================================================
-- 57: P5 加密合约看板 —— 合约池 / 5 分钟快照 / 日汇总 / 分位
--
-- 数据链路:
--   Binance FAPI (经 Cloudflare Worker) → bp_ingest/crypto_futures.py
--     → bp_crypto_contract
--     → bp_crypto_futures_snapshot_5m (TimescaleDB hypertable, chunk 1 day)
--     → bp_crypto_contract_daily
--     → bp_crypto_futures_percentile (API 只读预计算)
--
-- 口径:
--   * 表恒为原生 USD/USDT，不参与 CNY 折算；
--   * 缺失即缺失: 多空比 / taker 比 / OI 缺失存 NULL，不填 0；
--   * 快照 captured_at 对齐 UTC 5 分钟桶，主键幂等。
--
-- 幂等: 全部 CREATE ... IF NOT EXISTS；create_hypertable 使用
-- if_not_exists => TRUE。已部署环境只跑未应用的编号。
-- =====================================================================

-- ---------------------------------------------------------------------
-- 合约池（Top 30 USDT 永续 + 元数据）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_crypto_contract (
    contract_code   TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    base_asset      TEXT NOT NULL,
    quote_asset     TEXT NOT NULL DEFAULT 'USDT',
    listed_at       TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    oi_notional_rank INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_crypto_contract_rank
        CHECK (oi_notional_rank IS NULL OR oi_notional_rank > 0)
);

COMMENT ON TABLE bp_crypto_contract IS
    'Binance USDT 永续合约元数据；oi_notional_rank 为 24h quoteVolume 前 30 排名';
COMMENT ON COLUMN bp_crypto_contract.contract_code IS
    'Binance symbol（如 BTCUSDT），全栈统一主键';
COMMENT ON COLUMN bp_crypto_contract.listed_at IS
    'exchangeInfo.onboardDate（毫秒时间戳）转 UTC；缺失为 NULL';
COMMENT ON COLUMN bp_crypto_contract.oi_notional_rank IS
    '按 24h quoteVolume 倒序的 1..30 排名；掉出 Top 30 置 NULL（保留历史）';

CREATE INDEX IF NOT EXISTS idx_crypto_contract_active_rank
    ON bp_crypto_contract (is_active, oi_notional_rank);

-- ---------------------------------------------------------------------
-- 5 分钟快照（TimescaleDB hypertable）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_crypto_futures_snapshot_5m (
    contract_code       TEXT NOT NULL
        REFERENCES bp_crypto_contract(contract_code) ON DELETE CASCADE,
    captured_at         TIMESTAMPTZ NOT NULL,
    mark_price          DOUBLE PRECISION,
    index_price         DOUBLE PRECISION,
    oi_contracts        DOUBLE PRECISION,
    oi_notional         DOUBLE PRECISION,
    long_short_ratio    DOUBLE PRECISION,
    taker_buy_sell_ratio DOUBLE PRECISION,
    basis_pct           DOUBLE PRECISION,
    PRIMARY KEY (contract_code, captured_at)
);

COMMENT ON TABLE bp_crypto_futures_snapshot_5m IS
    'Binance 5 分钟快照；captured_at 对齐 UTC 5 分钟桶，重复运行幂等 upsert';
COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.oi_notional IS
    '名义未平仓 = oi_contracts × mark_price（USDT 本位永续）';
COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.long_short_ratio IS
    'globalLongShortAccountRatio.longShortRatio；缺失 NULL，不补 0';
COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.taker_buy_sell_ratio IS
    'takerlongshortRatio.buySellRatio；缺失 NULL，不补 0';
COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.basis_pct IS
    '(mark_price - index_price) / index_price × 100';

SELECT create_hypertable(
    'bp_crypto_futures_snapshot_5m',
    by_range('captured_at', INTERVAL '1 day'),
    if_not_exists => TRUE,
    migrate_data => TRUE
);

CREATE INDEX IF NOT EXISTS idx_crypto_snapshot_5m_captured_at
    ON bp_crypto_futures_snapshot_5m (captured_at DESC);

-- ---------------------------------------------------------------------
-- 日汇总（OHLC / 资金费率 / OI）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_crypto_contract_daily (
    contract_code       TEXT NOT NULL
        REFERENCES bp_crypto_contract(contract_code) ON DELETE CASCADE,
    trade_date          DATE NOT NULL,
    open                DOUBLE PRECISION,
    high                DOUBLE PRECISION,
    low                 DOUBLE PRECISION,
    close               DOUBLE PRECISION,
    volume              DOUBLE PRECISION,
    quote_volume        DOUBLE PRECISION,
    funding_rate        DOUBLE PRECISION,
    oi_close            DOUBLE PRECISION,
    oi_notional_close   DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_code, trade_date),
    CONSTRAINT ck_crypto_contract_daily_high_low
        CHECK (high IS NULL OR low IS NULL OR high >= low)
);

COMMENT ON TABLE bp_crypto_contract_daily IS
    '合约日汇总（UTC 交易日）；funding_rate 为当日资金费率（小数，0.0001 = 0.01%）';
COMMENT ON COLUMN bp_crypto_contract_daily.oi_notional_close IS
    '日末名义未平仓 = oi_close × close';

CREATE INDEX IF NOT EXISTS idx_crypto_contract_daily_trade_date
    ON bp_crypto_contract_daily (trade_date DESC);

-- ---------------------------------------------------------------------
-- 分位预计算（API 只读；请求路径永不计算）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bp_crypto_futures_percentile (
    contract_code   TEXT NOT NULL
        REFERENCES bp_crypto_contract(contract_code) ON DELETE CASCADE,
    metric          TEXT NOT NULL,
    window_days     SMALLINT NOT NULL,
    as_of           DATE NOT NULL,
    pct             DOUBLE PRECISION NOT NULL,
    sample_size     INTEGER NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_code, metric, window_days, as_of),
    CONSTRAINT ck_crypto_percentile_window
        CHECK (window_days IN (30, 90, 180)),
    CONSTRAINT ck_crypto_percentile_pct
        CHECK (pct >= 0 AND pct <= 100),
    CONSTRAINT ck_crypto_percentile_sample
        CHECK (sample_size > 0)
);

COMMENT ON TABLE bp_crypto_futures_percentile IS
    '合约微观指标分位（0~100，中点 rank 公式；30/90/180 自然日窗口）';
COMMENT ON COLUMN bp_crypto_futures_percentile.metric IS
    'mark_price / oi_notional / long_short_ratio / taker_buy_sell_ratio / basis_pct';
COMMENT ON COLUMN bp_crypto_futures_percentile.as_of IS
    '该指标最后一个真实样本的 UTC 交易日；避免端点数故障被误标为「新鲜」';

CREATE INDEX IF NOT EXISTS idx_crypto_percentile_metric_asof
    ON bp_crypto_futures_percentile (metric, as_of DESC, window_days);

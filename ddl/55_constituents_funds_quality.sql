-- 55: P1 数据扩展（成分股 / 跟踪基金 / 质量日志 / 收藏）
BEGIN;

CREATE TABLE IF NOT EXISTS bp_stock_master (
    stock_code   TEXT PRIMARY KEY,
    market       TEXT NOT NULL,
    board        TEXT,
    name         TEXT NOT NULL,
    industry_l1  TEXT,
    industry_l2  TEXT,
    is_st        BOOLEAN NOT NULL DEFAULT FALSE,
    is_delisted  BOOLEAN NOT NULL DEFAULT FALSE,
    listed_at    DATE,
    delisted_at  DATE,
    adjust_modes TEXT[] NOT NULL DEFAULT ARRAY['bfq','qfq','hfq']::TEXT[],
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_stock_market CHECK (market IN ('SH','SZ','BJ'))
);

CREATE TABLE IF NOT EXISTS bp_index_constituent (
    index_code     TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    stock_code     TEXT NOT NULL,
    weight         NUMERIC(10,6),
    rank           INTEGER,
    source         TEXT NOT NULL,
    captured_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, effective_date, stock_code),
    CONSTRAINT ck_const_weight CHECK (weight IS NULL OR (weight >= 0 AND weight <= 100))
);
CREATE INDEX IF NOT EXISTS idx_constituent_stock ON bp_index_constituent (stock_code);

CREATE TABLE IF NOT EXISTS bp_fund_master (
    fund_code    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    company_name TEXT,
    risk_grade   TEXT,
    is_etf       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bp_index_tracker_fund (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    fund_code   TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    aum         NUMERIC(20,2),
    source      TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, fund_code, trade_date)
);

CREATE TABLE IF NOT EXISTS bp_data_quality_log (
    log_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    index_code    TEXT,
    trade_date    DATE,
    metric        TEXT,
    primary_src   TEXT,
    check_src     TEXT,
    primary_value NUMERIC(16,6),
    check_value   NUMERIC(16,6),
    rel_diff      NUMERIC(10,6),
    level         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_dq_level CHECK (level IN ('warn','error'))
);
CREATE INDEX IF NOT EXISTS idx_dq_time ON bp_data_quality_log (created_at DESC);

CREATE TABLE IF NOT EXISTS bp_user_favorite_index (
    user_id    BIGINT NOT NULL REFERENCES bp_user(user_id) ON DELETE CASCADE,
    index_code TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, index_code)
);

COMMIT;

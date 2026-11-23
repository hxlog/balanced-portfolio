-- 75: 行情 ETL 运行/源健康/质量问题/追赶 backlog（无限追赶语义）
-- 设计：docs/superpowers/specs/2026-11-23-unified-market-etl-design.md §5
BEGIN;

-- 波次运行记录：每次 run/wave 一行；status=ok 表示该波达标，catching_up 表示未达标但会继续追
CREATE TABLE IF NOT EXISTS bp_etl_run (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset text NOT NULL,
    trade_date date NOT NULL,
    wave integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    target_coverage numeric(6,4),
    achieved_coverage numeric(6,4),
    rows_written integer NOT NULL DEFAULT 0,
    sources_used jsonb NOT NULL DEFAULT '{}'::jsonb,
    errors integer NOT NULL DEFAULT 0,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CONSTRAINT ck_etl_run_status CHECK (status IN ('running','ok','catching_up','error'))
);
CREATE INDEX IF NOT EXISTS idx_etl_run_ds_date ON bp_etl_run (dataset, trade_date DESC, wave DESC);
CREATE INDEX IF NOT EXISTS idx_etl_run_started ON bp_etl_run (started_at DESC);

-- 源×通道健康：每日聚合；供管理页源矩阵与熔断决策
CREATE TABLE IF NOT EXISTS bp_etl_source_health (
    stat_date date NOT NULL,
    dataset text NOT NULL,
    source text NOT NULL,
    channel text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    ok integer NOT NULL DEFAULT 0,
    failed integer NOT NULL DEFAULT 0,
    banned_count integer NOT NULL DEFAULT 0,
    avg_latency_ms numeric(10,2),
    p95_latency_ms numeric(10,2),
    coverage_today numeric(6,4),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stat_date, dataset, source, channel)
);

-- 质量问题（不阻断追赶，但必须可视化/可审计）
CREATE TABLE IF NOT EXISTS bp_etl_quality_issue (
    issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset text NOT NULL,
    symbol text,
    trade_date date,
    kind text NOT NULL,
    severity text NOT NULL DEFAULT 'warn',
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT ck_etl_issue_sev CHECK (severity IN ('info','warn','error'))
);
CREATE INDEX IF NOT EXISTS idx_etl_issue_open ON bp_etl_quality_issue (dataset, created_at DESC) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_etl_issue_symbol ON bp_etl_quality_issue (dataset, symbol, trade_date);

-- 数据集状态：last_success_date 仅当覆盖率达到目标时推进（"追平"的持久事实）
CREATE TABLE IF NOT EXISTS bp_etl_dataset_state (
    dataset text PRIMARY KEY,
    last_success_date date,
    last_run_id bigint REFERENCES bp_etl_run(run_id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 未追赶条目持久队列：无硬停追赶的载体，跨交易日优先重试
CREATE TABLE IF NOT EXISTS bp_etl_backlog (
    dataset text NOT NULL,
    trade_date date NOT NULL,
    scope text NOT NULL DEFAULT 'dataset',
    symbol text NOT NULL DEFAULT '',
    reason text,
    attempts integer NOT NULL DEFAULT 0,
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_etl_backlog_scope CHECK (scope IN ('dataset','symbol')),
    PRIMARY KEY (dataset, trade_date, scope, symbol)
);
CREATE INDEX IF NOT EXISTS idx_etl_backlog_retry ON bp_etl_backlog (next_retry_at);

COMMENT ON TABLE bp_etl_run IS '行情 ETL 波次运行记录（无限追赶：catching_up 表示继续重试，非终止）';
COMMENT ON TABLE bp_etl_source_health IS '行情 ETL 源×通道每日健康度（管理页/熔断依据）';
COMMENT ON TABLE bp_etl_quality_issue IS '行情 ETL 质量问题（OHLC/交叉校验/比率漂移/覆盖率不足）';
COMMENT ON TABLE bp_etl_dataset_state IS '行情 ETL 数据集状态：last_success_date 仅在追平后推进';
COMMENT ON TABLE bp_etl_backlog IS '行情 ETL 未追赶条目队列（跨交易日无限重试）';

COMMIT;

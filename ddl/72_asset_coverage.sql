-- 72: 资产行情覆盖快照（统一资产池 / 数据看护用，避免每次查询扫描大表）
BEGIN;

CREATE TABLE IF NOT EXISTS bp_asset_coverage (
    kind text NOT NULL,
    code text NOT NULL,
    adjust text NOT NULL,
    last_date date,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, code, adjust)
);

COMMENT ON TABLE bp_asset_coverage IS '资产行情覆盖快照：last_date 由 ETL 完成后刷新，API 只读本表';

COMMIT;

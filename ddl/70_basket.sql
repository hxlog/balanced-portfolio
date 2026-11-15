-- 70: 一篮子资产（basket）持久化 —— 保存/复制/编辑，/dashboard 可见
BEGIN;

CREATE TABLE IF NOT EXISTS bp_basket (
    basket_id bigserial PRIMARY KEY,
    owner_user_id integer REFERENCES bp_user(user_id) ON DELETE CASCADE,
    name text NOT NULL,
    description text,
    method text NOT NULL DEFAULT 'risk_parity',
    assets jsonb NOT NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    latest_result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_basket_owner ON bp_basket (owner_user_id, updated_at DESC);

COMMENT ON TABLE bp_basket IS '一篮子资产回测配置（篮子模式可保存、复制、编辑；/dashboard 展示）';
COMMENT ON COLUMN bp_basket.assets IS '资产列表 [{symbol, source}]';
COMMENT ON COLUMN bp_basket.params IS '回测参数 {lookback_days, rebalance_band, risk_free, risk_budget, start, end}';
COMMENT ON COLUMN bp_basket.latest_result IS '最近一次回测摘要（可选，便于 dashboard 展示）';

COMMIT;

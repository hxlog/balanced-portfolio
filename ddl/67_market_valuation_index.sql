-- 67: 市场估值指数 MVI（0=极度低估，100=极度高估）+ 风险分（0=安全，100=危险）
BEGIN;

CREATE TABLE IF NOT EXISTS bp_market_valuation_index (
    as_of date PRIMARY KEY,
    mvi numeric(6, 2) NOT NULL,
    cheap_score numeric(6, 2),
    risk_score numeric(6, 2),
    zone text NOT NULL,
    factors jsonb,
    weights jsonb,
    contributions jsonb,
    risk_factors jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_market_valuation_index IS
    '市场估值指数：周频因子（PE/PB 反向分位、股息/ERP/ROE 分位）线性加权 + IC 最大化权重；每日刷新';
COMMENT ON COLUMN bp_market_valuation_index.mvi IS '0=极度低估 100=极度高估';
COMMENT ON COLUMN bp_market_valuation_index.risk_score IS '0=安全 100=危险（波动率分位 55% + 回撤分位 45%）';

COMMIT;

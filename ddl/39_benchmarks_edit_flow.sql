-- 39: 编辑免重算流程(参数快照) + 组合上限"无限"语义
-- 依赖: 34-38 已应用

-- 1) 组合上限: NULL = 无限 (存量行均有显式值, 不受影响)
ALTER TABLE bp_user ALTER COLUMN portfolio_limit DROP NOT NULL;

-- 2) 复用未使用的 params 列作为"最后一次回测参数快照"
ALTER TABLE bp_portfolio RENAME COLUMN params TO last_run_params;

-- 3) 回填: status=done 的组合, 当前参数即最后一次回测参数 (历史上 PUT 必重算)
UPDATE bp_portfolio p
SET last_run_params = jsonb_build_object(
    'method', p.method,
    'ratio', p.ratio,
    'lookback_days', p.lookback_days,
    'start_date', to_jsonb(p.start_date),
    'benchmark_key', p.benchmark_key,
    'max_weight', round(p.max_weight::numeric, 4),
    'rebalance_band', round(p.rebalance_band::numeric, 4),
    'risk_free_rate', round(p.risk_free_rate::numeric, 4),
    'fee_rate', round(p.fee_rate::numeric, 4),
    'slippage_rate', round(p.slippage_rate::numeric, 4),
    'stamp_duty_rate', round(p.stamp_duty_rate::numeric, 4),
    'assets', (
      SELECT coalesce(jsonb_agg(jsonb_build_array(a.symbol, a.source, a.quadrant)
                                ORDER BY a.symbol, a.source, a.quadrant), '[]'::jsonb)
      FROM bp_portfolio_asset a WHERE a.portfolio_id = p.portfolio_id)
)
WHERE p.status = 'done';

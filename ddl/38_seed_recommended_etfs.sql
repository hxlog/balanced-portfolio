-- 38: 新增 16 只推荐 ETF(宽基/红利/海外) — 全部走 etf_em 后复权(hfq)主源,
-- 由 bp_ingest.fetch_with_fallback 在东财被 IP 封禁时降级腾讯 hfq(收益率对齐)。
-- 名称对应真实产品; category='etf'; 幂等 ON CONFLICT (symbol, source) DO UPDATE。
INSERT INTO bp_index_config
    (symbol, source, category, name, start_date, is_deleted, is_selectable, extra_params)
VALUES
    ('510500', 'etf_em', 'etf', '中证500ETF（南方）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('512100', 'etf_em', 'etf', '中证1000ETF（南方）',      '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('588080', 'etf_em', 'etf', '科创50ETF（易方达）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159845', 'etf_em', 'etf', '中证1000ETF（华夏）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('563300', 'etf_em', 'etf', '中证A500ETF',               '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159351', 'etf_em', 'etf', '创业板ETF（易方达）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('515180', 'etf_em', 'etf', '红利ETF易方达',             '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('515890', 'etf_em', 'etf', '红利低波ETF（华泰柏瑞）',    '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159581', 'etf_em', 'etf', '深红利ETF',                 '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('501031', 'etf_em', 'etf', '沪深300红利低波ETF',         '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('513520', 'etf_em', 'etf', '日经ETF（华夏）',            '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159866', 'etf_em', 'etf', '日经225ETF（易方达）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159870', 'etf_em', 'etf', '标普500ETF（易方达）',       '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('513880', 'etf_em', 'etf', '港股科技ETF',               '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('513300', 'etf_em', 'etf', '纳斯达克ETF（华夏）',        '2017-01-01', 0, TRUE, '{"adjust":"hfq"}'),
    ('159509', 'etf_em', 'etf', '德国ETF',                   '2017-01-01', 0, TRUE, '{"adjust":"hfq"}')
ON CONFLICT (symbol, source) DO UPDATE SET
    category     = EXCLUDED.category,
    name         = EXCLUDED.name,
    start_date   = EXCLUDED.start_date,
    is_deleted   = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable,
    extra_params = COALESCE(bp_index_config.extra_params, '{}'::jsonb) || EXCLUDED.extra_params,
    updated_at   = now();
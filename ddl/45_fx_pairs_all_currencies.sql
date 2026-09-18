-- =====================================================================
-- 43b: 补齐资产池全部外币币种的人民币汇率标的
--
-- 背景: 43 号只种了 USD/HKD/JPY 三对, 清洗期折算对 EUR/GBP/AUD/KRW/INR/RUB/BRL
-- 直接抛 MissingFxRate → 这几个市场的指数无法进入清洗表。实测新浪外汇日 K 端点
-- 对这些币种**均有直接报价**(无需美元三角合成), 故全部补齐为直接对。
--
-- 唯一例外: VND(越南胡志明)。新浪虽有报价但精度只有 4 位小数, VNDCNY ≈ 0.00027
-- 在 4 位小数下恒为 0.0000, 不可用 → 保持缺失, 该资产继续抛 MissingFxRate 并留下
-- last_error 暴露给运维, 绝不静默以原币混入 CNY 面板。
--
-- 幂等; 已部署环境只执行本文件。
-- =====================================================================

INSERT INTO bp_index_config
    (symbol, source, category, name, extra_params, is_deleted, is_selectable, currency)
VALUES
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

-- =====================================================================
-- 43: 汇率接入与 CNY 折算
--
-- 背景: 非 CNY 计价资产(港股指数 HKD、日经225 JPY、标普500/纳斯达克/道琼斯 USD)
-- 此前直接以原币价格进入 bp_quote_clean, 与 CNY 资产混在同一风险平价面板里比较
-- 收益/协方差 → 口径错误。本迁移让清洗阶段把非 CNY 资产折算为人民币计价。
--
-- 口径决策(与用户确认, 见 bp_api/quant/cleaning.py 模块头):
--   * 汇率**只取新浪**(bp_data_source.fx_sina)。实测新浪「人民币汇率」与中行牌价
--     是两套口径(USD 日变动相关 0.149, ±2 日移位检验排除日期错位) → 不可聚合、不可互换,
--     故 AGGREGATE_CHAINS 不注册该源, 汇率只有单一事实源。
--   * 折算发生在清洗阶段(唯一事实源 bp_quote_clean), 先折算再插值, OHLC 同时乘汇率。
--   * 无汇率日不处理(不 ffill/不外推): 该日不产出清洗行。
--   * 交叉汇率不做 USD 三角合成; 仅支持有直接新浪报价的币种 USD/HKD/JPY, 其余币种跳过。
--
-- 幂等; 已部署环境只执行本文件(勿重跑历史迁移)。
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. bp_quote_clean 增折算审计列
-- ---------------------------------------------------------------------
ALTER TABLE bp_quote_clean ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18,8);

COMMENT ON COLUMN bp_quote_clean.fx_rate IS
    '折算所用汇率(外币→CNY)。CNY 资产为 1；无汇率日为 NULL。close 列已是折算后的人民币价格。';

-- ---------------------------------------------------------------------
-- 2. 新增汇率数据源(新浪「人民币汇率」日 K, 直连 jsonp 端点)
--    is_addable=FALSE → 不可从 /admin/assets 添加;
--    is_selectable 由 bp_index_config 的配置行控制, 汇率标的均为 FALSE → 不进 /builder 可选池。
-- ---------------------------------------------------------------------
INSERT INTO bp_data_source
    (code, description, akshare_func, asset_class, has_volume,
     supports_date_range, symbol_hint, vendor, logical_source, is_backup, is_addable)
VALUES
    ('fx_sina', '人民币汇率-新浪(日 K, 直连 NewForexService.getDayKLine; 清洗期折算唯一汇率口径)',
     'NewForexService.getDayKLine', 'fx', FALSE, FALSE,
     '币种+CNY, 如 USDCNY / HKDCNY / JPYCNY', '新浪财经', 'fx_sina', FALSE, FALSE)
ON CONFLICT (code) DO UPDATE SET
    description         = EXCLUDED.description,
    akshare_func        = EXCLUDED.akshare_func,
    asset_class         = EXCLUDED.asset_class,
    has_volume          = EXCLUDED.has_volume,
    supports_date_range = EXCLUDED.supports_date_range,
    symbol_hint         = EXCLUDED.symbol_hint,
    vendor              = EXCLUDED.vendor,
    logical_source      = EXCLUDED.logical_source,
    is_backup           = EXCLUDED.is_backup,
    is_addable          = EXCLUDED.is_addable;

-- ---------------------------------------------------------------------
-- 3. 汇率标的配置行: is_selectable=FALSE(不进可选池) 但 is_deleted=0
--    (bp_ingest.db.fetch_active_configs 在调度路径显式纳入 source='fx_sina')
-- ---------------------------------------------------------------------
INSERT INTO bp_index_config
    (symbol, source, category, name, extra_params, is_deleted, is_selectable, currency)
VALUES
    ('USDCNY', 'fx_sina', 'forex', '美元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('HKDCNY', 'fx_sina', 'forex', '港币兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY'),
    ('JPYCNY', 'fx_sina', 'forex', '日元兑人民币(新浪)', '{}'::jsonb, 0, FALSE, 'CNY')
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    extra_params  = EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable,
    currency      = EXCLUDED.currency;

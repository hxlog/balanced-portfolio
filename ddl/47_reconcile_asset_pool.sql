-- =====================================================================
-- 47: 资产池与生产库对齐(已部署环境)
--
-- 背景: schema.sql 的 seed 与生产库 bp_index_config 存在实测漂移, 两处都要修
-- (PRD: 「schema.sql 最终要和生成环境一样」——全新安装必须产出与生产一致的可选资产池)。
--   漂移 A: 生产有 16 个品种, 任何一版 seed 都没有 → 全新库少 16 个可选键;
--   漂移 B: seed 有 9 行生产根本不存在(且从未落过数据) → 全新库多 9 个「幽灵资产」;
--   漂移 C: 恒生综合中小型股指数在 seed 里写成错代码 HSSCI, 真实东财代码是 HSMSI;
--   漂移 D: 4 行的 extra_params 被 seed 的兜底规则写成 {"adjust":"bfq"}, 生产为空 {}
--           (DX-Y.NYB / GC=F / sz159531 / HSMSI)。其中前两者由本文件第 3 段纠正,
--           后两者在生产库里本就是同一行、新 seed 直接写对, 无需本迁移介入。
-- 实测(可选池 = is_selectable AND NOT is_deleted, 以 symbol@source 为键):
--   修前 全新库 271 键 vs 生产 278 键(9 多 / 16 少), 另有 2 处 extra_params 差异;
--   修后 278 == 278, 共有键的 currency/category/name/extra_params 全部零差异。
--   (start_date 未对齐: 全新库仍有 239 个共有键为 NULL, 生产为 ingest 回写的真实
--    首个行情日 —— schema.sql 不跑 ingest, 该列不可能与生产相等, 也不应硬编码。
--    本迁移对新增的 16 行保留既有 start_date, 只保证这 16 个新增键的本列与生产一致。)
--
-- 幂等: 全部语句都带 (symbol, source) 谓词; 在生产库上四段全部改 0 行
--       (那些 key 或值已一致 —— 生产实测 bp_index_config 288 行 / 0 行软删 / 278 个可选键,
--        9 个幽灵键与 HSSCI 均不存在, DX-Y.NYB 与 GC=F 的 extra_params 已是 {})。
-- 边界: 只动配置行; 不 INSERT/UPDATE/DELETE 任何行情数据, 也不动 bp_asset_data_status。
--       生产库里 H30352/H30356/RI0 的孤儿行情与孤儿状态行是历史遗留, 本迁移不清理
--       (23 号迁移的 F 段曾清过孤儿状态行, 但那会造成行情「查得到数据、状态表说没有」
--        的不一致, 且孤儿数据在删除动作前无法安全清除 —— 留待人工决策)。
-- schema.sql 侧的同款修复(seed 段)与本文件一一对应, 见该文件 47 段注释。
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1) 补齐生产既有的 16 个品种。字段逐字取自生产库快照(symbol/source/category/
--    name/extra_params/is_deleted/is_selectable/currency), 顺序按 source, symbol。
--    start_date 用 COALESCE 保留既有值: 由 ingest 回写的真实首个行情日优先,
--    仅当当前为空时才落到本迁移给出的字面值(与 22 号迁移「保留 start_date」口径一致)。
--    生产库上这些日期已与快照一致(16 行实测逐行相等, 含 HSMSI 的 2017-01-01), 该列
--    在已部署环境不会被改写; 在全新环境(bp_index_config 无此 key)则写入快照值。
--    币种按生产实际写死(INR/BRL/EUR/AUD/USD/GBP/VND/HKD), 不依赖 40/41 段的
--    「global_index_em 一律 USD」等笼统规则, 保证任何环境都落到同一结果。
--    注意 513310 在 etf_em 与 etf_sina 下各有一行(同代码降级源), 生产两个 source 并存。
-- ---------------------------------------------------------------------
INSERT INTO bp_index_config
    (symbol, source, category, name, start_date, extra_params,
     is_deleted, is_selectable, currency)
VALUES
    ('588000', 'cn_index_em', 'etf', '科创50（华夏）', DATE '2017-01-01', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('932365', 'cn_index_em', 'index', '中证自由现金流', DATE '2025-04-10', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('sz159531', 'cn_index_sina', 'index', '中证2000', DATE '2017-01-01', '{}'::jsonb, 0, TRUE, 'CNY'),
    ('511580', 'etf_em', 'etf', '中证国债及政策性金融债0-3年ETF（招商）', DATE '2017-01-01', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('513000', 'etf_em', 'etf', '日经225 ETF（易方达）', DATE '2017-01-01', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('513310', 'etf_em', 'etf', '中韩半导体', DATE '2017-01-01', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('513530', 'etf_em', 'etf', '中证港股通高股息ETF（华泰柏瑞）', DATE '2022-04-25', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('513310', 'etf_sina', 'etf', '中韩半导体ETF', DATE '2017-01-01', '{"adjust":"hfq"}'::jsonb, 0, TRUE, 'CNY'),
    ('印度孟买SENSEX', 'global_index_em', 'index', '印度孟买SENSEX', DATE '2017-01-02', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'INR'),
    ('巴西BOVESPA', 'global_index_em', 'index', '巴西BOVESPA', DATE '2017-01-02', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'BRL'),
    ('德国DAX30', 'global_index_em', 'index', '德国DAX30', DATE '2017-01-02', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'EUR'),
    ('澳大利亚标普200', 'global_index_em', 'index', '澳大利亚标普200', DATE '2017-01-03', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'AUD'),
    ('纳斯达克', 'global_index_em', 'index', '纳斯达克100', DATE '2017-01-03', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'USD'),
    ('英国富时100', 'global_index_em', 'index', '英国富时100', DATE '2017-01-03', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'GBP'),
    ('越南胡志明', 'global_index_em', 'index', '越南胡志明', DATE '2017-01-03', '{"adjust":"bfq"}'::jsonb, 0, TRUE, 'VND'),
    -- 恒生综合中小型股指数的真实东财代码是 HSMSI(见下方第 2 段的 HSSCI)。
    ('HSMSI', 'hk_index_em', 'index', '恒生综合中小型股指数', DATE '2017-01-01', '{}'::jsonb, 0, TRUE, 'HKD')
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    extra_params  = EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable,
    currency      = EXCLUDED.currency,
    -- 保留已落库的 start_date(ingest 回写的真实首个行情日); 仅空值才回填字面值。
    start_date    = COALESCE(bp_index_config.start_date, EXCLUDED.start_date);

-- ---------------------------------------------------------------------
-- 2) seed 有、生产没有的 9 行 → 停用(is_deleted=1 + is_selectable=FALSE)。
--    判定依据(逐行核对生产库, 只读):
--      · 生产 bp_index_config 里这 9 个 key 完全不存在, 也不存在任何近义/大小写变体;
--      · 均未被任何 bp_portfolio_asset 引用(按 symbol 全库查过);
--      · bp_asset_data_status 显示 raw_rows=0(即从未落过数据)的占 6 个;
--        H30352/H30356/RI0 另有孤儿行情与状态行(见文件头「边界」), 但同样没有配置行。
--    为什么是「停用」而不是「删掉」或「保留可选」:
--      · 保留可选 → 全新库 /builder 会多出 9 个永远拉不到数据、管理端永远显示
--        「从未落过数据」的品种, 与生产可选池不一致;
--      · 删掉 → 行内记录「这些代码试探过、不可用」的信息一并丢失, 且未来想重新
--        验证时没有落点。停用后它们既不进 /builder(list_assets 按 is_selectable 过滤),
--        也不被 6h 调度拉取(fetch_active_configs 按 is_deleted 过滤)。
--    HSSCI 是错代码, 真代码 HSMSI 已由第 1 段补上(同名同义, 不是两套资产)。
-- ---------------------------------------------------------------------
-- 上证380指数: 东财无此代码, 生产试探后从未取到数据。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = '000309' AND (is_deleted = 0 OR is_selectable);
-- 深证基本面60指数: 生产曾把 source 切到 cn_index_sina 重试仍失败, 现无任何 key。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = '399709' AND (is_deleted = 0 OR is_selectable);
-- 中证A100指数。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = '930000' AND (is_deleted = 0 OR is_selectable);
-- 中证保险主题指数。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = '930842' AND (is_deleted = 0 OR is_selectable);
-- 中证500价值指数(生产残留 860 行行情, 最后一日 2026-07-09)。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = 'H30352' AND (is_deleted = 0 OR is_selectable);
-- 中证800价值指数(生产残留 756 行行情, 最后一日 2026-07-09)。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cn_index_em' AND symbol = 'H30356' AND (is_deleted = 0 OR is_selectable);
-- 恒生消费指数: 东财无此代码, 生产试探后从未取到数据。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'hk_index_em' AND symbol = 'HSCONSI' AND (is_deleted = 0 OR is_selectable);
-- 恒生综合中小型股指数(错代码; 真代码 HSMSI 见第 1 段)。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'hk_index_em' AND symbol = 'HSSCI' AND (is_deleted = 0 OR is_selectable);
-- 早籼稻主力: 该合约已退市, 生产库里 2022-06-30 后再无行情。
UPDATE bp_index_config SET is_deleted = 1, is_selectable = FALSE, updated_at = now()
 WHERE source = 'cmdty_main_sina' AND symbol = 'RI0' AND (is_deleted = 0 OR is_selectable);

-- ---------------------------------------------------------------------
-- 3) 清掉 seed 兜底规则误加的 adjust 键。
--    schema.sql 的 seed 对「非 ETF」一律补 {"adjust":"bfq"}, 但这两个品种的 fetch 路径
--    根本不读 extra_params(dxy_em 走 em_push2his_kline; GC=F 走 futures_foreign_hist),
--    生产库为 {}。该键不影响行情口径(没有消费方), 但会让「全新库 == 生产」断言失败。
--    同类漂移另有 sz159531@cn_index_sina 与 HSMSI@hk_index_em: 这两行的 seed 已在
--    schema.sql 侧直接写成 {}, 而它们在生产库并非「已存在的旧行被兜底改写」而是本来就
--    是新行, 故此处不需要纠偏语句(写了也是 0 行)。
--    注意: 仅清这两行; 其余非 ETF 品种(国内指数/国债/商品主力/全球指数)生产的
--    adjust 确实存在且为 bfq, 不能一起清。
-- ---------------------------------------------------------------------
UPDATE bp_index_config SET extra_params = '{}'::jsonb, updated_at = now()
 WHERE ((source = 'dxy_em'        AND symbol = 'DX-Y.NYB')
     OR (source = 'gold_comex_em' AND symbol = 'GC=F'))
   AND extra_params <> '{}'::jsonb;

COMMIT;

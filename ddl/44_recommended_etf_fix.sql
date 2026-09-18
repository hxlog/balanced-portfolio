-- =====================================================================
-- 44: 推荐 ETF 清单重建 —— 错误名称纠正 + 补齐 4 类 17 只场内 ETF
-- =====================================================================
-- 背景
--   38_seed_recommended_etfs.sql 当年按「指数名 → 代码」的假设批量写入,
--   部分 symbol 与真实产品不符(如 159870 实为化工ETF鹏华, 却挂着「标普500ETF（易方达）」)。
--   已用东财 ak.fund_etf_spot_em() / 新浪 ak.fund_etf_category_sina() 实盘列表交叉核对,
--   并用 bp_quote_clean 日收益率相关性二次验证(见下方逐条注释)。
--
-- 本迁移做两件事, 均为幂等:
--   1) 纠正 18 条确实错配/错名的 bp_index_config.name(symbol 与 source 不变, 资产 key 不受影响)
--   2) 确保推荐清单 4 类 17 只场内 ETF 全部在册(每指数恰好一只)。
--      其中 11 只在生产库已存在但从未进入任何 DDL; 全新环境由 schema.sql 的 44 段补齐。
--
-- 注意: 只改 name, 不改 key。key 是 {symbol}@{source}, 全栈通用; 改名不会让组合引用失效。
--       组合自身的 display_name 是组合侧展示缓存, 本迁移不改写(避免把正确的语义改错)。
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1) 名称纠正(symbol + source 定位, 不触碰 extra_params / is_selectable / currency)
-- ---------------------------------------------------------------------
-- 命名口径: 统一取东财实盘简称(平台 ETF 主源即 etf_em, 与 vendor 一致)。
-- 判定为「资产错配」(即 symbol 的真实标的 ≠ 原名称所述)的, 附相关性证据。
UPDATE bp_index_config SET name = 'A500ETF嘉实',       updated_at = now()
 WHERE symbol = '159351' AND source = 'etf_em';   -- 错配: 原「创业板ETF（易方达）」; 与沪深300 相关 0.970, 与创业板指 0.846
UPDATE bp_index_config SET name = '纳指科技ETF景顺',    updated_at = now()
 WHERE symbol = '159509' AND source = 'etf_em';   -- 错配: 原「德国ETF」; 与纳指ETF 相关 0.887, 与德国DAX 仅 0.556
UPDATE bp_index_config SET name = '红利ETF万家',       updated_at = now()
 WHERE symbol = '159581' AND source = 'etf_em';   -- 错名: 原「深红利ETF」; 实跟踪中证红利(与 515180 相关 0.983)
UPDATE bp_index_config SET name = '日经ETF工银',       updated_at = now()
 WHERE symbol = '159866' AND source = 'etf_em';   -- 错名: 原「日经225ETF（易方达）」, 管理人为工银瑞信
UPDATE bp_index_config SET name = '化工ETF鹏华',       updated_at = now()
 WHERE symbol = '159870' AND source = 'etf_em';   -- 错配: 原「标普500ETF（易方达）」; 与标普500 相关 0.197, 与有色金属 0.775
UPDATE bp_index_config SET name = '深证成指ETF大成',    updated_at = now()
 WHERE symbol = '159943' AND source = 'etf_em';   -- 错配: 原「广发中证全指医药卫生ETF」; 与深证100 相关 0.918, 与医药 0.663
UPDATE bp_index_config SET name = '家电ETF国泰',       updated_at = now()
 WHERE symbol = '159996' AND source = 'etf_em';   -- 错名: 原「易方达中证家电ETF」, 管理人为国泰
UPDATE bp_index_config SET name = '电子ETF天弘',       updated_at = now()
 WHERE symbol = '159997' AND source = 'etf_em';   -- 错名: 原「广发中证电子ETF」, 管理人为天弘
UPDATE bp_index_config SET name = '医疗ETF华宝',       updated_at = now()
 WHERE symbol = '512170' AND source = 'etf_em';   -- 错名: 原「易方达医疗ETF」, 管理人为华宝
UPDATE bp_index_config SET name = '计算机ETF国泰',      updated_at = now()
 WHERE symbol = '512720' AND source = 'etf_em';   -- 错名: 原「广发中证计算机主题ETF」, 管理人为国泰
UPDATE bp_index_config SET name = '传媒ETF广发',       updated_at = now()
 WHERE symbol = '512980' AND source = 'etf_em';   -- 错名: 原「鹏华中证传媒ETF」, 管理人为广发
UPDATE bp_index_config SET name = '食品饮料ETF华夏',    updated_at = now()
 WHERE symbol = '515170' AND source = 'etf_em';   -- 错名: 原「鹏华中证食品饮料ETF」, 管理人为华夏
UPDATE bp_index_config SET name = '软件ETF国泰',       updated_at = now()
 WHERE symbol = '515230' AND source = 'etf_em';   -- 错名: 原「嘉实中证软件服务ETF」, 管理人为国泰
UPDATE bp_index_config SET name = '银行ETF天弘',       updated_at = now()
 WHERE symbol = '515290' AND source = 'etf_em';   -- 错配: 原「易方达中证生物医药ETF」; 与银行ETF 相关 0.988, 与医药 0.254
UPDATE bp_index_config SET name = '红利ETF博时',       updated_at = now()
 WHERE symbol = '515890' AND source = 'etf_em';   -- 错名: 原「红利低波ETF（华泰柏瑞）」; 实跟踪中证红利(与 515180 相关 0.977)
UPDATE bp_index_config SET name = '中证2000ETF华泰柏瑞', updated_at = now()
 WHERE symbol = '563300' AND source = 'etf_em';   -- 错配: 原「中证A500ETF」; 与中证1000 相关 0.932, 与中证A500 仅 0.687
UPDATE bp_index_config SET name = '日经225ETF华安',    updated_at = now()
 WHERE symbol = '513880' AND source = 'etf_em';   -- 错配: 原「港股科技ETF」; 与日经225 相关 0.887, 与恒生科技 仅 0.329
UPDATE bp_index_config SET name = '央企红利ETF华泰柏瑞', updated_at = now()
 WHERE symbol = '561580' AND source = 'etf_em';   -- 错名: 原「中证央企业红利ETF」(「央企业」为笔误); 实跟踪中证中央企业红利指数


-- ---------------------------------------------------------------------
-- 2) 推荐清单 4 类 17 只场内 ETF 在册
--    全部场内 ETF(无 LOF / 场外), etf_em 后复权(hfq)主源, 与 38 号迁移同口径。
--    选品: 每指数恰好一只, 取「成立最久(可用行情行数最多) → 规模 → 流动性(成交额)」最优者。
--    start_date 置 NULL: 由 bp_ingest mark_sync_success 的 COALESCE 回写真实首个行情日
--    (38 号写死的 2017-01-01 会阻止回写, 故此处不沿用)。
--    ON CONFLICT 不更新 name / start_date: 生产库已有的更准确中文名与真实起始日保持不变。
-- ---------------------------------------------------------------------
INSERT INTO bp_index_config
    (symbol, source, category, name, start_date, extra_params, is_deleted, is_selectable)
VALUES
    -- 国内宽基
    ('588080', 'etf_em', 'etf', '科创50ETF（易方达）',                       NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('159915', 'etf_em', 'etf', '创业板ETF（易方达）',                       NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('510300', 'etf_em', 'etf', '沪深300ETF（华泰柏瑞）',                     NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('510050', 'etf_em', 'etf', '上证50ETF（华夏）',                         NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    -- 红利类
    ('561580', 'etf_em', 'etf', '央企红利ETF华泰柏瑞',                        NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('513630', 'etf_em', 'etf', '摩根标普港股通低波红利指数（摩根ETF）',          NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('515450', 'etf_em', 'etf', '红利低波50ETF南方',                         NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('515180', 'etf_em', 'etf', '红利ETF易方达',                             NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('159399', 'etf_em', 'etf', '富时中国A股自由现金流聚焦ETF（现金流ETF国泰）',   NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    -- 固收类
    ('511260', 'etf_em', 'etf', '上证10年期国债ETF（国泰）',                   NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('511520', 'etf_em', 'etf', '政金债ETF富国',                             NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('511360', 'etf_em', 'etf', '短融ETF海富通',                             NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('511090', 'etf_em', 'etf', '中债-30年期国债ETF（鹏扬）',                  NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    -- 海外投资
    ('513500', 'etf_em', 'etf', '标普500ETF（博时）',                         NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('513100', 'etf_em', 'etf', '纳斯达克100 ETF（国泰）',                     NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('513520', 'etf_em', 'etf', '日经ETF（华夏）',                            NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE),
    ('159920', 'etf_em', 'etf', '恒生指数ETF（华夏）',                         NULL, '{"adjust":"hfq"}'::jsonb, 0, TRUE)
ON CONFLICT (symbol, source) DO UPDATE SET
    category      = EXCLUDED.category,
    extra_params  = COALESCE(bp_index_config.extra_params, '{}'::jsonb) || EXCLUDED.extra_params,
    is_deleted    = EXCLUDED.is_deleted,
    is_selectable = EXCLUDED.is_selectable;

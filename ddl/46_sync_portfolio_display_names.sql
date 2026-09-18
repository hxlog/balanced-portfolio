-- =====================================================================
-- 46: 同步组合侧 display_name —— 44 号改名后, 组合里仍留着旧(错误)展示名
--
-- 背景: 44 号纠正了 bp_index_config.name, 但 bp_portfolio_asset.display_name 是
-- 组合侧的展示缓存, 当年按错误 name 抄了一份, 改 44 号不会自动跟随 → 同一个标的
-- 在 /admin/assets 显示正确名称、在 /builder 与 /dashboard 仍显示错误名称。
--
-- 本迁移只同步「44 号改过名的那批 symbol」, 且仅当组合侧 display_name 与库中旧名
-- **完全一致**时才改写(避免覆盖用户手工起的别名)。
--
-- 幂等; 已部署环境只执行本文件。
-- =====================================================================

BEGIN;

-- 逐条按「组合侧 display_name = 旧错误名」精确匹配后改写为新名。
-- 使用 (symbol, source) 定位, 不动 portfolio_id / quadrant / sort_order。
UPDATE bp_portfolio_asset a SET display_name = c.name
  FROM bp_index_config c
 WHERE c.symbol = a.symbol AND c.source = a.source
   AND c.source = 'etf_em'
   AND a.display_name IS DISTINCT FROM c.name
   AND a.display_name IN (
       '创业板ETF（易方达）',            -- 159351 实为 A500ETF嘉实
       '德国ETF',                        -- 159509 实为 纳指科技ETF景顺
       '深红利ETF',                      -- 159581 实为 红利ETF万家
       '日经225ETF（易方达）',            -- 159866 实为 日经ETF工银
       '标普500ETF（易方达）',            -- 159870 实为 化工ETF鹏华
       '广发中证全指医药卫生ETF',         -- 159943 实为 深证成指ETF大成
       '易方达中证家电ETF',               -- 159996 实为 家电ETF国泰
       '广发中证电子ETF',                 -- 159997 实为 电子ETF天弘
       '易方达医疗ETF',                   -- 512170 实为 医疗ETF华宝
       '广发中证计算机主题ETF',           -- 512720 实为 计算机ETF国泰
       '鹏华中证传媒ETF',                 -- 512980 实为 传媒ETF广发
       '鹏华中证食品饮料ETF',             -- 515170 实为 食品饮料ETF华夏
       '嘉实中证软件服务ETF',             -- 515230 实为 软件ETF国泰
       '易方达中证生物医药ETF',           -- 515290 实为 银行ETF天弘
       '红利低波ETF（华泰柏瑞）',         -- 515890 实为 红利ETF博时
       '中证A500ETF',                    -- 563300 实为 中证2000ETF华泰柏瑞
       '港股科技ETF',                    -- 513880 实为 日经225ETF华安
       '中证央企业红利ETF（华泰柏瑞）'     -- 561580 笔误, 实为 央企红利ETF华泰柏瑞
   );

COMMIT;

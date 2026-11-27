-- 78: 示例篮子（basket demo）—— is_demo / display_order + 列表索引（幂等）
--
-- 背景（2026-11-27 全站整改 P2）：
--   一篮子资产（ddl/70）上线后只有「我的篮子」；/dashboard 需要一个所有人（含匿名）
--   可读、登录用户可复制、仅管理员可编辑的示例篮子。
--
-- 语义与四象限 demo 组合（ddl/36 的 bp_portfolio.is_demo / display_order）保持一致：
--   is_demo      示例篮子标记；匿名列表只返回 is_demo = TRUE 的行；
--   display_order 示例的全局展示顺序（管理员调整，NULLS LAST）。
--
-- 幂等：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可重复执行。
BEGIN;

ALTER TABLE bp_basket
    ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;

ALTER TABLE bp_basket
    ADD COLUMN IF NOT EXISTS display_order integer;

-- 示例列表：按全局顺序取示例（匿名/登录用户共用）
CREATE INDEX IF NOT EXISTS idx_basket_demo_order
    ON bp_basket (display_order, basket_id)
    WHERE is_demo = TRUE;

COMMENT ON COLUMN bp_basket.is_demo IS '示例篮子（匿名可读、登录可复制、仅管理员可编辑/重算）';
COMMENT ON COLUMN bp_basket.display_order IS '示例篮子全局展示顺序（升序，NULLS LAST；管理员维护）';

COMMIT;

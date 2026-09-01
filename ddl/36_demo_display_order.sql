-- 36: 示例组合(demo)全局展示顺序。
-- 新增 bp_portfolio.display_order 列, 供管理员调整「全局示例顺序」;
-- 匿名访客打开 /dashboard 默认展示 display_order 最小的 demo(而非最早创建)。
ALTER TABLE bp_portfolio ADD COLUMN IF NOT EXISTS display_order integer;

-- 62: 指数行业分类（用于 /valuation 行业筛选与行业估值热力图）
ALTER TABLE bp_index_master
    ADD COLUMN IF NOT EXISTS industry text;

COMMENT ON COLUMN bp_index_master.industry IS '申万一级行业分类（按指数名称关键词映射，宽基为 NULL）';

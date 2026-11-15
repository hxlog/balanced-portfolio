-- 63: 分位窗口扩展为 1/3/5/10 年 + 全历史（配合重构后的多窗口分位）
BEGIN;

ALTER TABLE bp_index_percentile DROP CONSTRAINT IF EXISTS ck_pct_window;

ALTER TABLE bp_index_percentile
    ADD CONSTRAINT ck_pct_window
    CHECK (window_key IN ('1y', '3y', '5y', '10y', 'all'));

COMMIT;

-- 把今日批量新增的估值指数行情配置降级为非可选：
-- 服务器只维持原有资产的增量；521 只估值指数的行情由本机批量拉取后写库。
UPDATE bp_index_config
SET is_selectable = FALSE, updated_at = now()
WHERE is_deleted = 0
  AND category = 'index'
  AND index_code IS NOT NULL
  AND created_at >= TIMESTAMPTZ '2026-11-14 14:50:00+00';

SELECT count(*) AS index_configs,
       count(*) FILTER (WHERE is_selectable) AS selectable_index_configs
FROM bp_index_config WHERE is_deleted = 0 AND category = 'index';

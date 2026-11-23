-- 76: qfq（前复权）逻辑停用
-- 决策：只保留 bfq/hfq（D5）；历史 qfq 行情行保留只读，不物理删除。
BEGIN;

-- 1) 抓取口径：从 adjust_modes 中移除 qfq（幂等）
UPDATE bp_index_config
SET adjust_modes = array_remove(adjust_modes, 'qfq'),
    updated_at = now()
WHERE is_deleted = 0
  AND 'qfq' = ANY(adjust_modes);

-- 2) 主口径若为 qfq（不应存在），回退为 bfq，避免清洗取错口径
UPDATE bp_index_config
SET adjust = 'bfq',
    updated_at = now()
WHERE is_deleted = 0
  AND adjust = 'qfq';

COMMENT ON COLUMN bp_index_config.adjust_modes IS '抓取口径（bfq/hfq；qfq 已于 76 号迁移停用）';

COMMIT;

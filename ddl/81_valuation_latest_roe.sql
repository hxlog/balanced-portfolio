-- 81: 指数估值最新快照补 ROE(TTM) 列（ROE × PE 估值矩阵的数据源）
--
-- 背景（2026-11-27 第二轮反馈 A5）：
--   首页「估值矩阵 · ROE × PE」长期是空态：bp_index_valuation_daily 有 roe_ttm，
--   但 ddl/80 的 bp_index_valuation_latest 没带该列，/api/v1/valuation/indices 快照
--   不返回 roe_ttm，前端散射点恒为空。本迁移只补列；数据由 refresh_valuation_latest
--   在估值任务收尾时随快照刷新写入（重跑一次估值任务即回填），缺失写 NULL 不造数。
--
-- 口径：与 bp_index_valuation_daily.roe_ttm 一致（百分数点），来自最新 is_primary 估值行。
-- 已知限制：中证官网 fallback（csindex_value）的 119 只指数无 ROE/PB 记录，ROE 为 NULL
--   属数据源限制，不在前端用其它字段推导。
BEGIN;

ALTER TABLE bp_index_valuation_latest
    ADD COLUMN IF NOT EXISTS roe_ttm NUMERIC(10,4);

COMMENT ON COLUMN bp_index_valuation_latest.roe_ttm IS
    'ROE(TTM)，百分数点；来自最新主口径估值行，缺失为 NULL（ROE×PE 估值矩阵用）';

COMMIT;

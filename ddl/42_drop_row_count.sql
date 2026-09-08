-- 42: 删除 bp_asset_data_status.row_count 冗余列
--
-- 背景: DDL 40 为「COUNT 移出热路径」方案新增了 row_count(=bp_index_quote_daily 行数),
-- 但该表早已有语义相同的既存列 raw_rows/clean_rows(NOT NULL DEFAULT 0), 其维护者正是
-- refresh_asset_status 里的两条 COUNT(*)。row_count 与 raw_rows 完全重复, 无任何读取方
-- (API/前端/ingest 均不引用), 属冗余列。
--
-- 修正后的方案(不再维护 row_count):
--   refresh_asset_status 默认 with_count=False 只跑 MAX(trade_date) 且不触碰 raw_rows/clean_rows;
--   管理端「刷新状态」/ ingest 推进 last_raw_date 的路径用 with_count=True 重算 COUNT 写回 raw_rows/clean_rows。
--
-- 本迁移只 DROP 冗余列; raw_rows/clean_rows 数据完好, DDL 40 的回填值随之丢弃(与 raw_rows 同源, 无信息损失)。
-- 幂等: DROP COLUMN IF EXISTS, 可重复执行。
-- 依赖: DDL 40 已应用(row_count 列存在)。

BEGIN;
ALTER TABLE bp_asset_data_status DROP COLUMN IF EXISTS row_count;
COMMIT;

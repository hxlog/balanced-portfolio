-- 35: 用户「资产编辑者」权限 — 可进 /admin/assets 新增/更新/测试/拉取增量,
-- 但不能软删除、停用/启用、全量 sync-all、重算所有就绪组合。
-- 幂等: ADD COLUMN IF NOT EXISTS。
ALTER TABLE bp_user ADD COLUMN IF NOT EXISTS can_manage_assets boolean NOT NULL DEFAULT false;

-- 回填: 超级管理员(role='admin')默认授予资产编辑权。
UPDATE bp_user SET can_manage_assets = true WHERE role = 'admin';
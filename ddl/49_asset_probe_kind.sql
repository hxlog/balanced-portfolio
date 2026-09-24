-- =====================================================================
-- 49: bp_asset_data_status.last_probe_kind —— 区分「接口可达但本次拉不到」与「真实错误」
--
-- 背景: 保存资产前的「必须先测试读取成功」门禁(asset_probe_ok)只认 last_error IS NULL。
-- 但反爬/限频/IP 封锁是**暂时性**的: 用户明明知道该品种用某个接口是通的(如东财 ETF
-- 在别处刚拉过), 只是此刻被 429/连接重置挡住, 于是保存被永久卡住, 交互无法推进。
--
-- 口径: probe 时把失败按**错误类别**归档到本列 ——
--   'ok'          读取成功
--   'unreachable' 连接级失败(ConnectionError/Timeout/SSL/429/YFRateLimitError/整链断连):
--                 接口本身没问题, 稍后重试即可 → **允许保存**, 落库后由后台 ingest 补数据
--   'invalid'     未知数据源、代码不存在等真实错误 → 仍然拦截保存
-- NULL 表示从未 probe 过(旧行), 视同「未探测」, 与原有语义一致。
--
-- 判据落地在 bp_ingest/sources.py:classify_probe_error(单一事实源), probe 端点写入本列。
-- 幂等: ADD COLUMN IF NOT EXISTS + 约束先 DROP 再 ADD。
-- =====================================================================

ALTER TABLE bp_asset_data_status
  ADD COLUMN IF NOT EXISTS last_probe_kind TEXT;

ALTER TABLE bp_asset_data_status
  DROP CONSTRAINT IF EXISTS ck_bp_asset_data_status_probe_kind;

ALTER TABLE bp_asset_data_status
  ADD CONSTRAINT ck_bp_asset_data_status_probe_kind
  CHECK (last_probe_kind IS NULL OR last_probe_kind IN ('ok', 'unreachable', 'invalid'));

COMMENT ON COLUMN bp_asset_data_status.last_probe_kind IS
  '上次测试读取的结论类别: ok=成功; unreachable=接口可达但本次被反爬/限频/超时挡住(允许保存, 后台补拉); invalid=未知源或代码不存在(拦截保存); NULL=从未测试';

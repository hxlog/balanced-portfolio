-- 37: 数据源「逻辑源分组」— 让 UI 对 ETF/国内指数不再暴露东财/新浪/腾讯等物理源。
-- 物理 source 保持不变(回测 JSON 键、bp_portfolio_asset 等全栈 key 不受影响),
-- 聚合取数在 bp_ingest.sources.fetch_with_fallback 完成; 本迁移只加展示分组元数据。
ALTER TABLE bp_data_source ADD COLUMN IF NOT EXISTS logical_source text;
ALTER TABLE bp_data_source ADD COLUMN IF NOT EXISTS is_backup boolean NOT NULL DEFAULT false;

-- 国内指数: 新浪/腾讯/东财代码(宽基)通用, 聚合为 cn_index, 主源 cn_index_em。
UPDATE bp_data_source SET logical_source='cn_index', is_backup = (code <> 'cn_index_em')
 WHERE code IN ('cn_index_em','cn_index_em_px','cn_index_sina','cn_index_tx','index_tx');

-- 港股指数: em 与 sina 命名入参不同(HSI vs CES100), 不聚合; 逻辑源=主源自身。
UPDATE bp_data_source SET logical_source='hk_index', is_backup = (code <> 'hk_index_em')
 WHERE code IN ('hk_index_em','hk_index_sina');

-- 全球指数: 中文名 vs 英文 symbol 差异, 不聚合。
UPDATE bp_data_source SET logical_source='global_index', is_backup = (code <> 'global_index_em')
 WHERE code IN ('global_index_em','global_index_sina');

-- ETF: 后复权聚合(东财主 + 腾讯 hfq 兜底); 新浪 ETF 仅原始价不用于回测口径, 标记为备源。
UPDATE bp_data_source SET logical_source='etf', is_backup = (code <> 'etf_em')
 WHERE code IN ('etf_em','etf_tx','etf_sina');

-- 其余(commodity/bond/futures/forex/alternative)逻辑源=自身, 非备源。
UPDATE bp_data_source SET logical_source = code, is_backup = false WHERE logical_source IS NULL;
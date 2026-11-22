-- 74: 补齐 SGDCNY 汇率对（Accounts 表 USD/SGD 需要；fx_sina 支持任意 {币种}CNY）
-- 注意：bp_index_config.config_id 是 GENERATED ALWAYS AS IDENTITY，禁止显式赋值。
BEGIN;

INSERT INTO bp_index_config (
    symbol, source, category, name, currency, adjust,
    adjust_modes, is_selectable, is_deleted
)
SELECT
    'SGDCNY', 'fx_sina', 'forex', '新加坡元兑人民币(新浪)', 'CNY', 'bfq',
    ARRAY['bfq'], FALSE, 0
WHERE NOT EXISTS (
    SELECT 1 FROM bp_index_config WHERE symbol = 'SGDCNY' AND source = 'fx_sina'
);

COMMIT;

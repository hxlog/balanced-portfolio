-- 74: 补齐 SGDCNY 汇率对（Accounts 表 USD/SGD 需要；fx_sina 支持任意 {币种}CNY）
BEGIN;

INSERT INTO bp_index_config (
    config_id, symbol, source, category, name, currency, adjust,
    adjust_modes, is_selectable, is_deleted
)
SELECT
    nextval('bp_index_config_config_id_seq'),
    'SGDCNY', 'fx_sina', 'forex', '新加坡元兑人民币(新浪)', 'CNY', 'bfq',
    ARRAY['bfq'], FALSE, 0
WHERE NOT EXISTS (
    SELECT 1 FROM bp_index_config WHERE symbol = 'SGDCNY' AND source = 'fx_sina'
);

COMMIT;

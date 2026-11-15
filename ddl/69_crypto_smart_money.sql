-- 69: 加密合约大户多空 + 资金费率历史（Smart Money 因子与 30 日分位）
BEGIN;

ALTER TABLE bp_crypto_futures_snapshot_5m
    ADD COLUMN IF NOT EXISTS top_account_ratio numeric(12, 4),
    ADD COLUMN IF NOT EXISTS top_position_ratio numeric(12, 4);

COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.top_account_ratio IS '大户多空账户数比（topLongShortAccountRatio）';
COMMENT ON COLUMN bp_crypto_futures_snapshot_5m.top_position_ratio IS '大户多空持仓比（topLongShortPositionRatio）';

CREATE TABLE IF NOT EXISTS bp_crypto_funding_history (
    contract_code text NOT NULL,
    funding_time timestamptz NOT NULL,
    funding_rate numeric(14, 8),
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_code, funding_time)
);

CREATE TABLE IF NOT EXISTS bp_crypto_top_ratio_history (
    contract_code text NOT NULL,
    ts timestamptz NOT NULL,
    top_account_ratio numeric(12, 4),
    top_position_ratio numeric(12, 4),
    captured_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_code, ts)
);

COMMIT;

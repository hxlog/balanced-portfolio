-- 59: 加密合约数据源口径（Binance 直连被封时的 Bybit+OKX 备用口径）
--
-- 背景：Binance 的 WAF 封禁 Cloudflare Workers 出口（实测 403），生产无法经 Worker 访问 Binance；
-- 同一 Worker 访问 Bybit/OKX 正常。不同数据源的多空比/OI 口径不可混算分位，
-- 因此显式记录 provider，分位只对同一 provider 的历史计算。
BEGIN;

ALTER TABLE bp_crypto_contract
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'binance';

ALTER TABLE bp_crypto_futures_snapshot_5m
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'binance';

ALTER TABLE bp_crypto_futures_percentile
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'binance';

ALTER TABLE bp_crypto_contract DROP CONSTRAINT IF EXISTS ck_crypto_contract_provider;
ALTER TABLE bp_crypto_contract ADD CONSTRAINT ck_crypto_contract_provider
    CHECK (provider IN ('binance', 'bybit_okx'));

ALTER TABLE bp_crypto_futures_snapshot_5m DROP CONSTRAINT IF EXISTS ck_crypto_snapshot_provider;
ALTER TABLE bp_crypto_futures_snapshot_5m ADD CONSTRAINT ck_crypto_snapshot_provider
    CHECK (provider IN ('binance', 'bybit_okx'));

COMMIT;

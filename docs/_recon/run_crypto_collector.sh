#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== cron ==="
cat /etc/cron.d/bp-crypto-futures 2>/dev/null || echo missing
echo "=== 手动跑一次采集 ==="
set -a; . ./.env; set +a
timeout 240 .venv/bin/python -m bp_ingest.crypto_futures 2>&1 | tail -4 || true
echo "=== 最新快照多空/大户 ==="
su - postgres -c "psql -d postgres -c \"select s.contract_code, round(s.long_short_ratio::numeric,2) ls, round(s.top_account_ratio::numeric,2) top_acc, round(s.top_position_ratio::numeric,2) top_pos, round((s.oi_notional/1e8)::numeric,1) oi_yi from bp_crypto_futures_snapshot_5m s join bp_crypto_contract c using(contract_code) where c.is_active order by s.captured_at desc limit 8\""

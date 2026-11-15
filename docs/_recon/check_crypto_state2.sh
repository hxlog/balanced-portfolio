#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== crypto 数据 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), min(captured_at), max(captured_at) from bp_crypto_futures_snapshot_5m\"" 
su - postgres -c "psql -d postgres -tAc \"select count(*), count(distinct contract) from bp_crypto_futures_percentile\"" 2>/dev/null || echo "no percentile table"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(trade_date) from bp_crypto_corr_daily\"" 2>/dev/null || echo "no corr"
echo "=== crypto API ==="
for p in "/api/crypto/futures/summary" "/api/crypto/futures/contracts" "/api/crypto/correlation"; do
  curl -s -o /dev/null -w "  $p -> %{http_code}\n" --max-time 15 "http://127.0.0.1:8000$p"
done
echo "=== 前端文件 ==="
ls web/app/crypto-futures 2>/dev/null; ls web/app/crypto 2>/dev/null

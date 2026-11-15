#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 全站 200 检查 ==="
for p in / /valuation /valuation/930641 /crypto /crypto-futures /cffex /dashboard /builder /methodology /otc-pricing /admin/assets; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "http://127.0.0.1:3000$p")
  echo "$p -> $code"
done
echo "=== API 端点 ==="
for p in /api/health /api/valuation/indices?limit=1 /api/valuation/summary /api/crypto/futures/summary /api/cffex/spot /api/portfolios/demo /api/assets; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "http://127.0.0.1:8000$p")
  echo "$p -> $code"
done
echo "=== 数据新鲜度 ==="
su - postgres -c "psql -d postgres -tAc \"select max(trade_date) from bp_index_valuation_daily where is_primary\""
su - postgres -c "psql -d postgres -tAc \"select max(captured_at) from bp_crypto_futures_snapshot_5m\""
su - postgres -c "psql -d postgres -tAc \"select max(trade_date) from bp_cffex_contract_daily\""
date
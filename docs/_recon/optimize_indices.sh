#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm 'perf: 指标列表两日收盘合并为一次 LATERAL + 90 天 chunk 裁剪' || true
pm2 restart bp-api >/dev/null
sleep 4
echo '--- analyze ---'
su - postgres -c "psql -d postgres -c 'ANALYZE bp_quote_clean; ANALYZE bp_index_valuation_daily; ANALYZE bp_index_percentile; ANALYZE bp_index_master'" | tail -2
echo '--- timing ---'
for i in 1 2; do curl -s -o /dev/null -w "indices run$i: %{http_code} %{time_total}s\n" 'http://127.0.0.1:8000/api/valuation/indices?limit=600'; done
#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 服务 ==="
pm2 list --no-color | grep -E "bp-api|bp-web" | head -3
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== 服务器代码版本 ==="
grep -n "PERCENTILE_WINDOWS = " bp_api/repositories_valuation.py | head -2
grep -n "PERCENTILE_WINDOW_ORDER = " bp_ingest/valuation_ingest.py | head -2
grep -n "_WINDOW_YEARS = " bp_api/quant/valuation.py | head -2
echo "=== 分位窗口现状 ==="
su - postgres -c "psql -d postgres -c \"select window_key, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
echo "=== 简介/行业 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where intro is not null and btrim(intro) <> ''), count(*) filter (where industry is not null), count(*) from bp_index_master\""
echo "=== 数据新鲜度 ==="
su - postgres -c "psql -d postgres -tAc \"select max(trade_date) from bp_index_valuation_daily where is_primary\""
date

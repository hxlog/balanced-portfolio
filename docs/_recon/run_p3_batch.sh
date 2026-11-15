#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== P3 批量验证开始 $(date +%H:%M:%S) ==="
timeout 600 .venv/bin/python scripts/p3_stock_batch_verify.py 2>&1 | grep -aE "configs ready|ingest:|raw:|clean rows|clean:|Error" | tail -30
sleep 3
echo "=== 汇总 ==="
su - postgres -c "psql -d postgres -tAc \"select adjust, count(distinct symbol), count(*) from bp_index_quote_daily where category = 'stock' group by 1 order by 1\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol), count(*) from bp_quote_clean where symbol in (select symbol from bp_index_config where category = 'stock' and is_deleted = 0)\""
free -h | head -2

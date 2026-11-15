#!/usr/bin/env bash
set -uo pipefail
echo "=== 先停 bp-ingest，避免启动即全量拉 648 个标的 ==="
pm2 stop bp-ingest >/dev/null 2>&1 || true
echo "=== 降级新配置 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /tmp/demote_new_indexes.sql"
echo "=== 重启 bp-ingest（仅原有 selectable 资产参与增量） ==="
pm2 start bp-ingest >/dev/null 2>&1 || pm2 restart bp-ingest >/dev/null
sleep 8
pm2 list --no-color | grep -E "bp-ingest"
echo "=== 数据现状 ==="
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = chr(98)||chr(102)||chr(113)\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = chr(98)||chr(102)||chr(113)\""
free -h | head -2
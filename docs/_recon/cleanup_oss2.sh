#!/usr/bin/env bash
set -uo pipefail
pkill -9 -f cleanup_oss || true
pkill -9 -f "psql -d postgres -f /tmp/cleanup_oss_rows.sql" || true
sleep 1
rm -f /etc/cron.d/bp-csindex-oss
su - postgres -c "psql -d postgres -f /tmp/cleanup_oss2.sql"
echo "--- 覆盖率 ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
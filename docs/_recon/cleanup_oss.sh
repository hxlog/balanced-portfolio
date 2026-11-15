#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -f /tmp/cleanup_oss_rows.sql"
echo "--- 停用无效的 OSS cron ---"
rm -f /etc/cron.d/bp-csindex-oss
ls /etc/cron.d/
echo "--- 覆盖率 ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
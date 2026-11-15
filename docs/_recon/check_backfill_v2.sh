#!/usr/bin/env bash
echo "--- backfill v2 ---"
grep -a "progress\|missing\|done" /tmp/server_backfill2.log | tail -4
echo "--- clean ---"
pgrep -fc server_clean_indexes || echo 0
tail -2 /tmp/server_clean.log
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2
date
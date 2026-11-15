#!/usr/bin/env bash
echo "--- retry log ---"
tail -4 /var/log/bp-index-quotes-retry.log 2>/dev/null || echo "not yet"
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
echo "--- agents ---"
ps -eo cmd | grep -icE "[q]cloud|[Y]DLive|[b]arad" || echo 0
date
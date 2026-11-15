#!/usr/bin/env bash
echo "--- procs ---"
pgrep -af "server_quote_backfill|server_clean_indexes" | head -4 || echo none
echo "--- backfill tail ---"
tail -c 600 /tmp/server_backfill.log | tr -d "\r" | tail -3
echo "--- clean tail ---"
tail -3 /tmp/server_clean.log
echo "--- raw coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = chr(98)||chr(102)||chr(113)\""
echo "--- index-code coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
date
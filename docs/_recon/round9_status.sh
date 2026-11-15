#!/usr/bin/env bash
echo "--- flag ---"
cat /tmp/backfill_complete.flag 2>/dev/null || echo "not complete yet"
echo "--- procs ---"
pgrep -fc run_quote_batch || echo 0
echo "--- chain log ---"
tail -6 /tmp/chain_clean.log 2>/dev/null || echo "no chain log"
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date
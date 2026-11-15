#!/usr/bin/env bash
sleep 120
echo "--- procs ---"
pgrep -fc run_quote_batch || echo 0
echo "--- batch tails ---"
for i in 0 1 2 3; do echo -n "batch$i: "; tail -1 /tmp/vbatch_$i.log 2>/dev/null | tr -d "\r" | cut -c1-100; done
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date
#!/usr/bin/env bash
sleep 150
echo "procs: $(pgrep -fc run_quote_batch12 || echo 0)"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo "--- chain log ---"
tail -4 /tmp/chain_clean.log
date
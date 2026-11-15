#!/usr/bin/env bash
for i in $(seq 1 60); do
  if [ -f /tmp/backfill_complete.flag ]; then echo "flag present at attempt $i"; break; fi
  sleep 15
done
echo "--- chain log ---"
tail -8 /tmp/chain_clean.log 2>/dev/null
echo "--- final coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date
#!/usr/bin/env bash
for i in $(seq 1 90); do
  if ! pgrep -f "bp_ingest run" > /dev/null; then echo "backfill finished at attempt $i"; break; fi
  sleep 10
done
echo "--- log tail ---"
tail -3 /tmp/valuation_backfill.log
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date
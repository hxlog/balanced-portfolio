#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "waiting for batches... $(date +%H:%M:%S)"
for i in $(seq 1 180); do
  if ! pgrep -f run_quote_batch > /dev/null; then echo "batches done $(date +%H:%M:%S)"; break; fi
  sleep 10
done
echo "--- coverage before clean ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo "--- cleaning ---"
.venv/bin/python /tmp/cleanup_after_quote_backfill.py > /tmp/clean_after_backfill.log 2>&1
echo "clean exit=$?"
tail -3 /tmp/clean_after_backfill.log
echo "--- coverage after clean ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo DONE > /tmp/backfill_complete.flag
date
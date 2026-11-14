#!/usr/bin/env bash
for i in $(seq 1 20); do
  n=$(ps aux | grep -c "[v]aluation_run")
  if [ "$n" -eq 0 ]; then echo "finished at attempt $i"; break; fi
  sleep 6
done
echo "--- log2 ---"
tail -3 /tmp/valuation_ingest2.log
echo "--- counts ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_master) + 0, (select count(*) from bp_index_valuation_daily) + 0, (select count(*) from bp_index_percentile) + 0\""
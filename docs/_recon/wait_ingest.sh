#!/usr/bin/env bash
for i in $(seq 1 60); do
  if ! ps aux | grep -q "[v]aluation_run"; then echo "process finished at attempt $i"; break; fi
  sleep 5
done
echo "--- log ---"
tail -6 /tmp/valuation_ingest.log
echo "--- counts ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_master) || chr(47) || (select count(*) from bp_index_valuation_daily) || chr(47) || (select count(*) from bp_index_valuation_series) || chr(47) || (select count(*) from bp_index_percentile)\""
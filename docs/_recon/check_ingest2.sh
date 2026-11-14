#!/usr/bin/env bash
echo "procs: $(ps aux | grep -c "[v]aluation_run")"
echo "--- log ---"
tail -3 /tmp/valuation_ingest2.log
echo "--- counts (master/daily/series/percentile) ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_master) + 0, (select count(*) from bp_index_valuation_daily) + 0, (select count(*) from bp_index_valuation_series) + 0, (select count(*) from bp_index_percentile) + 0\""
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct index_code) from bp_index_valuation_daily where is_primary\""
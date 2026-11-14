#!/usr/bin/env bash
echo "procs: $(ps aux | grep -c "[v]aluation_run")"
echo "--- log4 ---"
tail -2 /tmp/valuation_ingest4.log 2>/dev/null || echo none
echo "--- counts ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_constituent) + 0, (select count(*) from bp_fund_master) + 0, (select count(*) from bp_index_tracker_fund) + 0\""
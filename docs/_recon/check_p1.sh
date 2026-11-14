#!/usr/bin/env bash
echo "--- procs ---"; ps aux | grep -c "[v]aluation_run"
echo "--- log3 ---"; tail -2 /tmp/valuation_ingest3.log
echo "--- counts (constituent/fund/tracker/stock) ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_constituent) + 0, (select count(*) from bp_fund_master) + 0, (select count(*) from bp_index_tracker_fund) + 0, (select count(*) from bp_stock_master) + 0\""
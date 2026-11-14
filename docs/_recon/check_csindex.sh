#!/usr/bin/env bash
echo "--- csindex2 procs ---"
ps aux | grep -c "[r]un_csindex"
tail -2 /tmp/csindex2.log 2>/dev/null || echo "no log"
echo "--- series counts ---"
su - postgres -c "psql -d postgres -tAc \"select calc_src, count(*), count(distinct index_code) from bp_index_valuation_series group by 1\""
echo "--- quality log ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), round(avg(rel_diff)::numeric,1) from bp_data_quality_log\""
#!/usr/bin/env bash
echo "--- procs ---"
pgrep -af "psql|cleanup_oss" | head -3 || echo none
echo "--- 覆盖率 ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
echo "--- csindex rows ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_quote_daily where source = chr(99)||chr(115)||chr(105)||chr(110)||chr(100)||chr(101)||chr(120)||chr(95)||chr(112)||chr(101)||chr(114)||chr(102)\""
echo "--- cron ---"
ls /etc/cron.d/
date
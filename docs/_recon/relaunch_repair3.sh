#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f repair_stale_quotes || true
sleep 1
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/repair_stale_quotes.py > /tmp/repair_quotes4.log 2>&1 < /dev/null &
echo relaunched
sleep 50
grep -aE "repair targets|fixed|write fail|repair done" /tmp/repair_quotes4.log | tail -6
su - postgres -c "psql -d postgres -tAc \"
with q as (select symbol, max(trade_date) d from bp_index_quote_daily where adjust='bfq' group by 1),
cal as (select max(cal_date) d from bp_trading_calendar where market='CN' and is_trading and cal_date <= current_date)
select count(*) filter (where q.d >= (select d from cal)) at_latest,
       count(*) filter (where q.d < (select d from cal)) lagging,
       count(*) filter (where q.symbol is null) missing
from bp_index_master m left join q on q.symbol = m.index_code
where m.is_active and m.is_tracked\""

#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 修复进度 ==="
pgrep -fc repair_stale_quotes || echo done
grep -ac "fixed" /tmp/repair_quotes5.log || true
grep -a "repair done" /tmp/repair_quotes5.log || true
echo "=== 覆盖率 ==="
su - postgres -c "psql -d postgres -c \"
with q as (select symbol, max(trade_date) d from bp_index_quote_daily where adjust='bfq' group by 1),
cal as (select max(cal_date) d from bp_trading_calendar where market='CN' and is_trading and cal_date <= current_date)
select count(*) filter (where q.d >= (select d from cal)) at_latest,
       count(*) filter (where q.d < (select d from cal)) lagging,
       count(*) filter (where q.symbol is null) missing
from bp_index_master m left join q on q.symbol = m.index_code
where m.is_active and m.is_tracked\""
su - postgres -c "psql -d postgres -c \"select last_date, count(*) from (select q.symbol, max(q.trade_date) last_date from bp_index_quote_daily q join bp_index_master m on m.index_code=q.symbol and m.is_active and m.is_tracked group by 1) t group by 1 order by 1 desc limit 4\""

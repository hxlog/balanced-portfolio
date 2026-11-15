#!/usr/bin/env bash
su - postgres -c "psql -d postgres -tAc \"
with q as (select symbol, max(trade_date) d from bp_index_quote_daily where adjust='bfq' group by 1),
cal as (select max(cal_date) d from bp_trading_calendar where market='CN' and is_trading and cal_date <= current_date)
select case
         when symbol like '000%' then '000-sh'
         when symbol like '399%' then '399-sz'
         when symbol like '93%' then '93-csi'
         when symbol like 'H%' then 'H-csi'
         when symbol like '95%' then '95-csi'
         when symbol like '97%' then '97-csi'
         when symbol like '98%' then '98-csi'
         else 'other' end as grp,
       count(*)
from bp_index_master m left join q on q.symbol=m.index_code
where m.is_active and m.is_tracked and (q.symbol is null or q.d < (select d from cal))
group by 1 order by 2 desc\""

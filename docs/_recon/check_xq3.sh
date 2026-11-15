#!/usr/bin/env bash
echo "--- 日志尾 ---"
tail -8 /tmp/xueqiu_backfill3.log
echo "--- 行数/进程 ---"
wc -l /tmp/xueqiu_backfill3.log
pgrep -fc xueqiu_quote_backfill || echo done
echo "--- global 是否入库 ---"
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -tAc \"select symbol, source, count(*) from bp_index_quote_daily where symbol in (chr(26631)||chr(26222)||chr(53)||chr(48)||chr(48)||chr(25351)||chr(25968)) group by 1,2\"" 2>/dev/null || true
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
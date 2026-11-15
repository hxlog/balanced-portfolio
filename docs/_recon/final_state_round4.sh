#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 修复进程 ==="
pgrep -fc repair_stale_quotes || echo done
tr -d "\r" < /tmp/repair_quotes6.log | tr "\r" "\n" | grep -acE "^fixed " || true
echo "=== 健康快照 ==="
su - postgres -c "psql -d postgres -c \"select status, count(*) from bp_index_quote_health group by 1 order by 2 desc\""
su - postgres -c "psql -d postgres -c \"select last_date, count(*) from (select q.symbol, max(q.trade_date) last_date from bp_index_quote_daily q join bp_index_master m on m.index_code=q.symbol and m.is_active and m.is_tracked group by 1) t group by 1 order by 1 desc limit 4\""
echo "=== 页面 ==="
for p in /valuation /valuation/000300 /crypto-futures; do curl -s -o /dev/null -w "  $p -> %{http_code}\n" --max-time 40 "http://127.0.0.1:3000$p"; done

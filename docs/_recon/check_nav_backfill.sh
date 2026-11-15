#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 净值回填进度 ==="
pgrep -fc backfill_fund_nav || echo done
tail -4 /tmp/fund_nav_backfill.log | tr -d "\r"
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*), max(trade_date) from bp_fund_nav_daily\""

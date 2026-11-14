#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/scheduler.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 移除与 cron 重复的加密调度任务" || true
pm2 restart bp-ingest >/dev/null
sleep 8
echo "--- 数据核对 ---"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_constituent), (select count(*) from bp_fund_master), (select count(*) from bp_index_tracker_fund), (select count(*) from bp_stock_master)\""
su - postgres -c "psql -d postgres -tAc \"select adjust, count(*), min(trade_date), max(trade_date) from bp_index_quote_daily where source like @stock_% group by adjust\"" 2>/dev/null || true
echo "--- 今日调度任务日志 ---"
grep -a -E "估值抓取完成|全市场估值快照完成|中证官网口径同步|Scheduler started" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -6
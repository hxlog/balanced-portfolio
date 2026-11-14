#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/scheduler.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 首轮增量改为后台线程，调度器立即启动" || true
pm2 restart bp-ingest >/dev/null
sleep 12
echo "--- fresh logs ---"
tail -12 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- scheduler started count ---"
grep -ac "Scheduler started" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null || echo 0
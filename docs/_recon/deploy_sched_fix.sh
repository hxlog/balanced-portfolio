#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/scheduler.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 调度器先启动再跑首轮，避免阻塞 5 分钟任务" || true
pm2 restart bp-ingest >/dev/null
sleep 10
echo "--- 启动日志 ---"
pm2 logs bp-ingest --lines 60 --nostream 2>/dev/null | grep -iE "Scheduler started|调度器启动|Adding job" | tail -6
echo "--- crypto job 是否注册 ---"
pm2 logs bp-ingest --lines 60 --nostream 2>/dev/null | grep -iE "crypto-futures" | tail -3 || echo "not yet"
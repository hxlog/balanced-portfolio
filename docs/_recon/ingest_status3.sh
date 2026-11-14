#!/usr/bin/env bash
echo "--- pm2 ---"
pm2 list --no-color | grep bp-ingest
echo "--- out tail ---"
tail -12 /root/.pm2/logs/bp-ingest-out.log 2>/dev/null
echo "--- err tail ---"
tail -12 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- 启动标记 ---"
grep -a "Scheduler started" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2
grep -a "crypto-futures" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2
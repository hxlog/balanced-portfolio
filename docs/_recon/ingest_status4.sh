#!/usr/bin/env bash
echo "--- 最近启动标记 ---"
grep -a "Scheduler started" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2
echo "--- 当前进程启动后的日志 ---"
tail -6 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- crypto job 相关 ---"
grep -a -iE "crypto-futures|加密合约" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -3 || echo none
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
date
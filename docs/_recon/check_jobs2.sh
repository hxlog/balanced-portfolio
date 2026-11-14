#!/usr/bin/env bash
echo "--- 重启后的调度任务列表 ---"
grep -a "Added job" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -12
echo "--- autocommit 报错上下文 ---"
grep -a -B 8 "can.t change .autocommit" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | head -20
echo "--- 当前时间与最近日志 ---"
date
tail -6 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
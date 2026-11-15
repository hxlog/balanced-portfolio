#!/usr/bin/env bash
echo "=== 强杀 YDLive ==="
pkill -9 -f YDLive 2>/dev/null || true
sleep 3
ps -eo pid,ppid,cmd | grep -iE "[q]cloud|[Y]DLive|[Y]DService|[b]arad|[t]at_agent" || echo "  已无腾讯 agent 进程"
echo "=== 检查是否有看门狗/父进程 ==="
ps -eo pid,ppid,cmd | grep -iE "watchdog|monitor|cloud-init" | head -5 || true
echo "=== 再观察 5 秒 ==="
sleep 5
ps -eo pid,cmd | grep -iE "[q]cloud|[Y]DLive" || echo "  稳定：无进程"
echo "=== 文件系统占用 ==="
ls -la /usr/local/qcloud /etc/cron.d/yunjing
df -h / | tail -1
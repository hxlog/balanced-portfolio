#!/usr/bin/env bash
set -uo pipefail
echo "=== 1) 停进程 ==="
pkill -9 -f "/usr/local/qcloud" 2>/dev/null || true
pkill -9 -f "YDLive" 2>/dev/null || true
pkill -9 -f "YDService" 2>/dev/null || true
pkill -9 barad_agent 2>/dev/null || true
pkill -9 -f "tat_agent" 2>/dev/null || true
sleep 2
ps -eo pid,cmd | grep -iE "[q]cloud|[Y]DLive|[Y]DService|[b]arad" || echo "  无残留进程"

echo "=== 2) 删除目录与 cron ==="
rm -rf /usr/local/qcloud /qcloud_init 2>/dev/null || true
rm -f /etc/cron.d/yunjing /etc/cron.d/sgagenttask 2>/dev/null || true

echo "=== 3) 中性化 per-boot 引导脚本 ==="
printf "#!/bin/bash\nexit 0\n" > /var/lib/cloud/scripts/per-boot/cloudRun.sh
chmod +x /var/lib/cloud/scripts/per-boot/cloudRun.sh
chattr +i /var/lib/cloud/scripts/per-boot/cloudRun.sh 2>/dev/null || echo "  chattr 不支持（忽略）"

echo "=== 4) 用不可写文件占位，阻止重建 ==="
touch /usr/local/qcloud
chattr +i /usr/local/qcloud 2>/dev/null || echo "  chattr 不支持（忽略）"
touch /etc/cron.d/yunjing
chattr +i /etc/cron.d/yunjing 2>/dev/null || echo "  chattr 不支持（忽略）"
ls -la /usr/local/qcloud /etc/cron.d/yunjing
lsattr /usr/local/qcloud /etc/cron.d/yunjing 2>/dev/null || true

echo "=== 5) 复核 ==="
sleep 3
ps -eo pid,cmd | grep -iE "[q]cloud|[Y]DService|[b]arad|[t]at_agent" || echo "  无腾讯 agent 进程"
ls -la /etc/cron.d/ | head -8
echo "=== 6) 业务自检 ==="
systemctl is-active nginx postgresql redis-server bp-relay | tr "\n" " "; echo
curl -s -o /dev/null -w "api:%{http_code} web:" --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation
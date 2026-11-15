#!/usr/bin/env bash
set -uo pipefail
echo "=== 1) 杀掉安装器与其父 sleep ==="
pkill -9 -f "self_cloud_install" 2>/dev/null || true
for p in $(ps -eo pid,cmd | grep -E "sh -c sleep [0-9]+" | awk "{print \$1}"); do kill -9 "$p" 2>/dev/null || true; done
sleep 2
echo "=== 2) 删除安装包 ==="
rm -f /tmp/self_cloud_install_linux64* /tmp/ydeye_install.log 2>/dev/null || true
echo "=== 3) 屏蔽下载域名（防止自动重装） ==="
for host in l.yd.qcloud.com lp.yd.qcloud.com sp.yd.qcloud.com l.yd.tencentyun.com; do
  grep -q " $host$" /etc/hosts || echo "0.0.0.0 $host" >> /etc/hosts
done
tail -6 /etc/hosts
echo "=== 4) 终止残留 agent ==="
pkill -9 -f "qcloud/YunJing" 2>/dev/null || true
pkill -9 -f "YDLive" 2>/dev/null || true
pkill -9 -f "YDService" 2>/dev/null || true
pkill -9 barad_agent 2>/dev/null || true
pkill -9 -f "tat_agent" 2>/dev/null || true
pkill -9 -f "/tmp/self_cloud" 2>/dev/null || true
echo "=== 5) 观察 20 秒 ==="
for i in 1 2 3 4; do
  sleep 5
  n=$(ps -eo cmd | grep -icE "[q]cloud|[Y]DLive|[Y]DService|[b]arad|self_cloud" || true)
  echo "  t=${i}x5s 进程数=$n"
done
ps -eo pid,cmd | grep -iE "[q]cloud|[Y]DLive|self_cloud|[b]arad" || echo "  已彻底清空"
echo "=== 6) 业务自检 ==="
systemctl is-active nginx postgresql redis-server bp-relay | tr "\n" " "; echo
curl -s -o /dev/null -w "api:%{http_code} web:" --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation
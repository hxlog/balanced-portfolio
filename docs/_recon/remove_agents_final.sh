#!/usr/bin/env bash
set -uo pipefail
echo "=== 1) 强杀残留 ==="
for p in $(pgrep -f "qcloud/YunJing" 2>/dev/null) $(pgrep -f "YDLive" 2>/dev/null) $(pgrep -f "barad_agent" 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
sleep 2
ps -eo pid,cmd | grep -iE "[q]cloud|[b]arad|[Y]DService|[Y]DLive" || echo "  无残留进程"

echo "=== 2) 移除 tat_agent unit ==="
systemctl stop tat_agent.service 2>/dev/null || true
systemctl disable tat_agent.service 2>/dev/null || true
rm -f /etc/systemd/system/tat_agent.service
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

echo "=== 3) 复核服务 ==="
systemctl list-unit-files --no-pager 2>/dev/null | grep -iE "tat_agent|barad|yunjing|stargate" || echo "  无相关 unit"
systemctl list-units --all --no-pager 2>/dev/null | grep -iE "tat_agent|barad_agent|stargate" || echo "  无相关运行 unit"

echo "=== 4) 最终进程表 ==="
ps -eo pid,cmd | grep -iE "[q]cloud|[b]arad|[s]gagent|[t]at_agent" || echo "  干净"

echo "=== 5) relay 与业务 ==="
systemctl is-active bp-relay nginx postgresql redis-server | tr "\n" " "; echo
curl -s -o /dev/null -w "api:%{http_code} " http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" http://127.0.0.1:3000/valuation
#!/usr/bin/env bash
set -uo pipefail
STAMP=$(date +%Y%m%d_%H%M%S)
BK=/opt/backup/qcloud_agents_$STAMP
mkdir -p "$BK"

echo "=== 1) 备份现状 ==="
cp -a /etc/cron.d/sgagenttask /etc/cron.d/yunjing "$BK/" 2>/dev/null || true
crontab -l > "$BK/root_crontab.txt" 2>/dev/null || true
cp /etc/rc.local "$BK/rc.local" 2>/dev/null || true
tar -czf "$BK/qcloud_dir.tar.gz" -C /usr/local qcloud 2>/dev/null || true
du -sh "$BK"

echo "=== 2) 停用 service 与定时任务 ==="
systemctl disable --now tat_agent.service 2>/dev/null || true
rm -f /etc/cron.d/sgagenttask /etc/cron.d/yunjing
crontab -l 2>/dev/null | grep -v "stargate" | crontab - || true
echo "  cron.d 剩余:"; ls /etc/cron.d/ | tr "\n" " "; echo
echo "  root crontab 剩余:"; crontab -l 2>/dev/null || echo "(empty)"

echo "=== 3) 停进程 ==="
pkill -f "qcloud/stargate" 2>/dev/null || true
pkill -f "qcloud/tat_agent" 2>/dev/null || true
pkill -f "qcloud/YunJing" 2>/dev/null || true
pkill -f "barad_agent" 2>/dev/null || true
sleep 2
ps -eo pid,cmd | grep -iE "[q]cloud|[b]arad" | head -8 || echo "  已无 qcloud/barad 进程"

echo "=== 4) 移除目录 ==="
mv /usr/local/qcloud "$BK/qcloud_moved" 2>/dev/null || true
ls -d /usr/local/qcloud 2>/dev/null && echo "  still exists" || echo "  /usr/local/qcloud 已移除（备份在 $BK）"

echo "=== 5) 清理 rc.local 中的 qcloud 行 ==="
sed -i "/qcloud/d" /etc/rc.local 2>/dev/null || true
cat /etc/rc.local 2>/dev/null | head -8

echo "=== 6) 复核 ==="
ps -eo pid,cmd | grep -iE "[q]cloud|[b]arad|[s]gagent|[Y]DService" || echo "  无残留进程"
systemctl list-unit-files --no-pager 2>/dev/null | grep -iE "tat_agent" || echo "  tat_agent 已移除"
echo "=== 7) 业务自检 ==="
systemctl is-active nginx postgresql redis-server | tr "\n" " "; echo
curl -s -o /dev/null -w "api:%{http_code} " http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" http://127.0.0.1:3000/valuation
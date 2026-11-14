#!/usr/bin/env bash
echo "=== 腾讯云相关服务 ==="
systemctl list-units --type=service --all --no-pager 2>/dev/null | grep -iE "yd|barad|tat|stargate|sgagent|qcloud|tencent|tcss|tce" | head -20
echo "=== 相关进程 ==="
ps aux | grep -iE "[Y]DService|[b]arad_agent|[t]at_agent|[s]targate|[s]gagent|[y]deyes|[q]cloud" | head -15
echo "=== /usr/local/qcloud 目录 ==="
ls -la /usr/local/qcloud 2>/dev/null | head -10
echo "=== crontab ==="
crontab -l 2>/dev/null | head -10
echo "=== 架构 ==="
uname -m; cat /etc/os-release | head -2
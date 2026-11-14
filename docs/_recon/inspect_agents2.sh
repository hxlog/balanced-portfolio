#!/usr/bin/env bash
echo "=== 所有 qcloud/腾讯相关 unit ==="
systemctl list-units --all --no-pager 2>/dev/null | grep -iE "tat|yd|barad|stargate|sgagent|qcloud|tcss" || echo none
echo "=== /etc/systemd/system 下的相关文件 ==="
ls -la /etc/systemd/system/ 2>/dev/null | grep -iE "tat|yd|barad|stargate|qcloud" || echo none
echo "=== 进程详情 ==="
ps -eo pid,ppid,cmd | grep -iE "[q]cloud|[b]arad|[t]at_agent|[s]gagent|[Y]DService|[Y]DLive" | head -12
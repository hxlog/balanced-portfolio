#!/usr/bin/env bash
echo "--- qcloud dir ---"
ls -d /usr/local/qcloud 2>/dev/null && ls /usr/local/qcloud | head -8 || echo "no qcloud dir"
echo "--- procs ---"
ps -eo pid,cmd | grep -iE "[q]cloud|[b]arad|[Y]DService|[t]at_agent|[s]gagent" | head -8 || echo "no processes"
echo "--- units ---"
systemctl list-unit-files --no-pager 2>/dev/null | grep -iE "tat_agent|barad|yunjing" || echo "no units"
echo "--- cron.d/yunjing ---"
cat /etc/cron.d/yunjing 2>/dev/null || echo "missing"
echo "--- 安装来源探测 ---"
grep -rl "YDCrontab" /etc/ /usr/lib/systemd/ 2>/dev/null | head -5 || true
#!/usr/bin/env bash
echo "=== 进程父进程 ==="
ps -o pid,ppid,user,cmd -p 1102,1475,1507,1508,1510,1504560 2>/dev/null || true
echo "=== ppid 链 ==="
for p in 1475 1507 1510 1504560; do echo -n "$p parent: "; awk '{print $4}' /proc/$p/stat 2>/dev/null; done
echo "=== init.d ==="
ls /etc/init.d/ 2>/dev/null | head -20
echo "=== rc.local ==="
cat /etc/rc.local 2>/dev/null | head -20 || echo none
echo "=== systemd 中 qcloud 路径引用 ==="
grep -rl "qcloud" /etc/systemd/system/ 2>/dev/null | head -10 || echo none
echo "=== cron.d ==="
ls /etc/cron.d/ 2>/dev/null; cat /etc/cron.d/* 2>/dev/null | grep -iE "qcloud|stargate|barad|yunjing" | head -5 || true
echo "=== 服务名候选 ==="
systemctl list-unit-files --no-pager 2>/dev/null | grep -iE "tat_agent|barad|yunjing|stargate|sgagent" || echo none
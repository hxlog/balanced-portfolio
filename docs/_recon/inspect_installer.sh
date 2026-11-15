#!/usr/bin/env bash
echo "=== 安装器进程链 ==="
ps -o pid,ppid,cmd -p 5036 2>/dev/null || true
echo "=== 父进程 1368 ==="
ps -o pid,ppid,cmd -p 1368 2>/dev/null || true
cat /proc/1368/cmdline 2>/dev/null | tr "\0" " "; echo
echo "=== /tmp 下安装器 ==="
ls -la /tmp/self_cloud_install* 2>/dev/null || echo none
echo "=== 可能的守护：最近启动的 systemd 服务 ==="
systemctl list-units --type=service --state=running --no-pager 2>/dev/null | grep -iE "cloud|tencent|qcloud|monitor" || echo none
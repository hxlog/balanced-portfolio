#!/usr/bin/env bash
echo "--- 进程父链 ---"
ps -o pid,ppid,cmd -p 1181,1190 2>/dev/null || true
echo "--- dpkg 腾讯包 ---"
dpkg -l 2>/dev/null | grep -iE "tencent|qcloud|yunjing|barad" | head -5 || echo none
echo "--- cloud-init 脚本 ---"
ls /var/lib/cloud/scripts/per-boot/ 2>/dev/null || echo "no per-boot"
grep -rl "qcloud\|YunJing" /var/lib/cloud/ 2>/dev/null | head -5 || echo "none in cloud"
echo "--- 最近被创建时间 ---"
stat -c "%n %y" /usr/local/qcloud 2>/dev/null
stat -c "%n %y" /etc/cron.d/yunjing 2>/dev/null
echo "--- 启动脚本引用 ---"
grep -rl "Yunjing\|YunJing" /etc/rc.local /etc/systemd/system/ /lib/systemd/system/ 2>/dev/null | head -5 || echo none
echo "--- systemd tmpfiles ---"
grep -r "qcloud" /etc/tmpfiles.d/ /usr/lib/tmpfiles.d/ 2>/dev/null | head -3 || echo none
#!/usr/bin/env bash
echo "--- cloudRun.sh ---"
head -40 /var/lib/cloud/scripts/per-boot/cloudRun.sh 2>/dev/null
echo "--- runcmd ---"
head -30 /var/lib/cloud/instances/ins-n9davdom/scripts/runcmd 2>/dev/null
echo "--- vendor-data 中与 qcloud 相关 ---"
grep -iE "qcloud|yunjing|barad|tat_agent" /var/lib/cloud/instances/ins-n9davdom/vendor-data.txt 2>/dev/null | head -10 || echo none
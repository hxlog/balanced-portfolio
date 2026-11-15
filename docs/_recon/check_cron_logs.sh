#!/usr/bin/env bash
echo "--- crontab entries ---"
ls /etc/cron.d/ | head -8
echo "--- retry log ---"
ls -la /var/log/bp-index-quotes*.log 2>/dev/null || echo "no logs yet"
tail -4 /var/log/bp-index-quotes-retry.log 2>/dev/null || echo "retry not run yet"
date
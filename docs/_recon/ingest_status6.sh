#!/usr/bin/env bash
echo "--- pm2 ---"
pm2 list --no-color | grep bp-ingest
echo "--- uptime/state ---"
pm2 describe bp-ingest --no-color 2>/dev/null | grep -iE "status|uptime|restarts|script|exec cwd" | head -8
echo "--- process cpu ---"
ps -o pid,etime,pcpu,rss,cmd -C python3 2>/dev/null | head -6
echo "--- log mtime ---"
ls -la /root/.pm2/logs/bp-ingest-*.log
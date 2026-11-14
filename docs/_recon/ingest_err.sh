#!/usr/bin/env bash
echo "--- error log tail ---"
tail -40 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -25
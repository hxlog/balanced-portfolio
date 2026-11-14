#!/usr/bin/env bash
echo "--- bp-ingest stderr tail ---"
tail -30 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- bp-ingest stdout tail ---"
tail -25 /root/.pm2/logs/bp-ingest-out.log 2>/dev/null
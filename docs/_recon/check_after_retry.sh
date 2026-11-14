#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- file has retries ---"
grep -c "retries: int = 2" bp_ingest/crypto_futures.py || echo 0
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron log tail ---"
tail -4 /var/log/bp-crypto-futures.log 2>/dev/null
echo "--- git ---"
git log --oneline -2
date
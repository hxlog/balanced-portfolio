#!/usr/bin/env bash
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- scheduler log ---"
pm2 logs bp-ingest --lines 600 --nostream 2>/dev/null | grep -iE "加密合约采集完成|加密合约采集异常" | tail -3
echo "--- job list ---"
pm2 logs bp-ingest --lines 600 --nostream 2>/dev/null | grep -iE "job .crypto-futures|Added job" | tail -3
echo "--- relay ---"
systemctl is-active bp-relay
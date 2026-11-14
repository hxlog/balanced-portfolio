#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- scheduler jobs added ---"
pm2 logs bp-ingest --lines 300 --nostream 2>/dev/null | grep -iE "crypto-futures|Added job .*crypto" | tail -5
echo "--- relay service ---"
systemctl is-active bp-relay
echo "--- snapshots in db ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- recent collector logs ---"
pm2 logs bp-ingest --lines 200 --nostream 2>/dev/null | grep -iE "加密合约采集" | tail -3
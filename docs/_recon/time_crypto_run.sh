#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "start $(date +%H:%M:%S)"
start=$(date +%s)
BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 timeout 420 .venv/bin/python -m bp_ingest.crypto_futures > /tmp/crypto_run_out.log 2>&1
rc=$?
end=$(date +%s)
echo "exit=$rc duration=$((end-start))s end $(date +%H:%M:%S)"
tail -6 /tmp/crypto_run_out.log
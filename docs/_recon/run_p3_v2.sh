#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
timeout 600 .venv/bin/python scripts/p3_stock_batch_verify2.py 2>&1 | grep -aE "removed|ingest:|clean rows|raw:|clean:|Error" | tail -25

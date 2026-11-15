#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== daily 增量 ==="
.venv/bin/python scripts/incremental_stock_quotes.py --mode daily 2>&1 | tail -3
echo "=== 覆盖率报告 ==="
.venv/bin/python scripts/asset_coverage_report.py --json /tmp/coverage.json 2>&1 | tail -45
echo "=== cron 已装 ==="
crontab -l | grep -cE "incremental_(stock|fund)"

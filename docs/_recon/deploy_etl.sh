#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
mkdir -p logs
echo "=== 测试 daily 增量 ==="
.venv/bin/python scripts/incremental_stock_quotes.py --mode daily 2>&1 | tail -3
echo "=== 安装 cron ==="
CRON=$(crontab -l 2>/dev/null || true)
for line in \
"35 23 * * 1-5 cd /opt/balanced-portfolio && .venv/bin/python scripts/incremental_stock_quotes.py --mode daily >> logs/etl-stock-daily.log 2>&1" \
"30 2 * * 0 cd /opt/balanced-portfolio && .venv/bin/python scripts/incremental_stock_quotes.py --mode weekly --days 40 --threads 6 >> logs/etl-stock-weekly.log 2>&1" \
"50 21 * * 1-5 cd /opt/balanced-portfolio && .venv/bin/python scripts/incremental_fund_nav.py --threads 6 --days 30 >> logs/etl-fund-daily.log 2>&1"
do
  if ! grep -qF "$line" <<< "$CRON"; then CRON="$CRON"$'\n'"$line"; fi
done
echo "$CRON" | sed '/^$/d' | crontab -
crontab -l | grep -E "incremental_(stock|fund)" || true
echo "=== 覆盖率报告 ==="
.venv/bin/python scripts/asset_coverage_report.py --json /tmp/coverage.json 2>&1 | tail -40

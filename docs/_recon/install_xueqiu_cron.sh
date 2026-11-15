#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f xueqiu_quote_backfill || true
sleep 1
# 继续补齐剩余（若上一轮未跑完）
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/xueqiu_quote_backfill.py > /tmp/xueqiu_backfill2.log 2>&1 < /dev/null &
cat > /etc/cron.d/bp-xueqiu-quotes <<'EOF'
# 每工作日 16:35 用雪球增量更新指数行情（东财/中证官网限流期间的主力通道）
35 16 * * 1-5 root cd /opt/balanced-portfolio && BP_XQ_ALL=1 BP_XQ_COUNT=-30 BP_XQ_DELAY=0.6 BP_XQ_BUDGET=1800 nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/xueqiu_quote_backfill.py >> /var/log/bp-xueqiu-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-xueqiu-quotes
cat /etc/cron.d/bp-xueqiu-quotes
sleep 30
tail -2 /tmp/xueqiu_backfill2.log
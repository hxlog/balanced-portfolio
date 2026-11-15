#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 64 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/64_index_quote_extremes.sql" 2>&1 | tail -3
su - postgres -c "psql -d postgres -tAc \"select count(*), count(high_all), count(close_52w_ago) from bp_index_quote_extremes\""
echo "=== 重启 api 并测速 ==="
pm2 restart bp-api >/dev/null
sleep 5
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | while read -r k; do redis-cli -h 127.0.0.1 -p 6379 DEL "$k" >/dev/null; done
for q in "indices?limit=1000&window=5y&metric=pe_ttm" "indices?limit=1000&window=1y&metric=pb" "indices?limit=1000&window=3y&industry=%E9%93%B6%E8%A1%8C"; do
  curl -s -o /dev/null -w "  cold $q -> %{http_code} %{time_total}s\n" --max-time 60 "http://127.0.0.1:8000/api/valuation/$q"
  curl -s -o /dev/null -w "  warm $q -> %{http_code} %{time_total}s\n" --max-time 60 "http://127.0.0.1:8000/api/valuation/$q"
done
echo "=== 安装每日极值刷新 cron ==="
cat > /etc/cron.d/bp-index-extremes <<'EOF'
# 每工作日 16:45 刷新指数行情极值（区间最高 / 52 周前收盘）
45 16 * * 1-5 root cd /opt/balanced-portfolio && su - postgres -c "psql -d postgres -f /opt/balanced-portfolio/ddl/64_index_quote_extremes.sql" >> /var/log/bp-index-extremes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-index-extremes
cat /etc/cron.d/bp-index-extremes

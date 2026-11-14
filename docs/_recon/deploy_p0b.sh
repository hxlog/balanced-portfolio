#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "[0] 恢复被停的进程"
pm2 start bp-ingest bp-worker >/dev/null 2>&1 || true
pm2 list --no-color | grep -E "bp-(ingest|worker)" || true

echo "[1] 提高 max_locks_per_transaction 至 4096"
CONF=/etc/postgresql/18/main/postgresql.conf
grep -q "^max_locks_per_transaction" "$CONF" && sed -i "s/^max_locks_per_transaction.*/max_locks_per_transaction = 4096/" "$CONF" || echo "max_locks_per_transaction = 4096" >> "$CONF"
grep "^max_locks_per_transaction" "$CONF"

echo "[2] 重启 PostgreSQL"
pg_ctlcluster 18 main restart --force 2>&1 | tail -2 || systemctl restart postgresql@18-main
sleep 4
su - postgres -c "psql -d postgres -tAc 'show max_locks_per_transaction'"

echo "[3] 执行 53 号迁移"
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/53_quote_adjust_pk.sql" 2>&1 | tail -5

echo "[4] 校验主键"
su - postgres -c "psql -d postgres -tAc \"select pg_get_constraintdef(oid) from pg_constraint where conname = 'pk_bp_index_quote_daily'\""
su - postgres -c "psql -d postgres -tAc \"select pg_get_constraintdef(oid) from pg_constraint where conname = 'pk_bp_quote_clean'\""

echo "[5] 重启全部进程"
pm2 restart bp-api bp-web bp-ingest bp-worker bp-beat >/dev/null 2>&1 || pm2 restart all >/dev/null
sleep 4
pm2 list --no-color | grep -E "bp-" || true

echo "[6] 健康检查"
printf "  api valuation: "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/valuation/overview || true
printf "  web valuation: "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/valuation || true
printf "  web home:      "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/ || true
free -h | head -2
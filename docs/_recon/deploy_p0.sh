#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio

echo "[1/6] 备份"
TS=$(date +%Y%m%d_%H%M%S)
TMP="/tmp/pre53_$TS.dump"
su - postgres -c "pg_dump -d postgres -Fc -f $TMP"
mv "$TMP" "/opt/backups/pre53_$TS.dump"
echo "  backup: /opt/backups/pre53_$TS.dump"

echo "[2/6] 停止写入进程"
pm2 stop bp-ingest bp-worker >/dev/null
echo "  stopped"

echo "[3/6] 执行 53 号迁移（主键与 row_hash 重建）"
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/53_quote_adjust_pk.sql" >/dev/null
echo "  migration ok"

echo "[4/6] 校验主键"
su - postgres -c "psql -d postgres -tAc \"select pg_get_constraintdef(oid) from pg_constraint where conname=\x27pk_bp_index_quote_daily\x27\""

echo "[5/6] 重启全部进程"
pm2 restart bp-api bp-web bp-ingest bp-worker bp-beat >/dev/null
pm2 list --no-color | grep -E "bp-(api|web|ingest|worker|beat)"

echo "[6/6] 健康检查"
sleep 4
printf "  api/valuation/overview: "
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/valuation/overview || true
printf "  web/valuation: "
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/valuation || true
echo "部署完成"

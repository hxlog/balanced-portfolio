#!/usr/bin/env bash
# 生产重活导致 OOM 事故后的**串行**恢复脚本（2026-11-24 事故复盘产物）。
# 用法（服务器 root，重启后执行）：
#   bash scripts/recover_after_reboot.sh
# 原则：一次只跑一个重活；每步前检查 MemAvailable；重活全局锁（bp_etl.guard heavy_lock）兜底。
set -uo pipefail
cd /opt/balanced-portfolio
set -a; . ./.env; set +a
MEM_MIN="${BP_ETL_MIN_MEM_MB:-700}"
log() { echo "[$(date '+%F %T')] $*"; }
avail() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
wait_mem() {
  while [ "$(avail)" -lt "$MEM_MIN" ]; do
    log "MemAvailable=$(avail)MB < $MEM_MIN，等待 30s"
    sleep 30
  done
  log "MemAvailable=$(avail)MB OK"
}

log "== 1) 清理遗留重活 =="
pkill -f '[b]p_etl rebuild' 2>/dev/null && log "killed stale rebuild" || true
pkill -f '[b]p_etl run --dataset' 2>/dev/null && log "killed stale run" || true
sleep 2

log "== 2) PostgreSQL =="
if ! systemctl is-active --quiet postgresql; then
  systemctl restart postgresql || true
fi
for _ in $(seq 1 30); do pg_isready -q && break; sleep 2; done
pg_isready || { log "POSTGRES NOT READY"; exit 1; }

log "== 3) PM2 基础进程 =="
pm2 restart deploy/ecosystem.config.cjs --update-env 2>/dev/null || pm2 start deploy/ecosystem.config.cjs
sleep 5
curl -sf "http://127.0.0.1:8000/api/health" >/dev/null && log "API OK" || log "WARN API 未就绪"

log "== 4) 串行补数（一次一个）=="
wait_mem; .venv/bin/python -m bp_etl run --dataset a_stock --adjust bfq --force --json | tail -5
wait_mem; .venv/bin/python -m bp_etl rebuild --dataset a_stock --mode delta --json | tail -5
wait_mem; .venv/bin/python -m bp_etl run --dataset hk_stock --force --json | tail -5
wait_mem; .venv/bin/python -m bp_etl run --dataset etf --force --json | tail -5
wait_mem; .venv/bin/python -m bp_etl run --dataset fund_nav --force --json | tail -5

log "== 5) 启动 bp-etl 常驻无限追赶 =="
pm2 start bp-etl --update-env 2>/dev/null || pm2 restart bp-etl --update-env
sleep 3
pm2 status bp-etl | head -8

log "== 6) 验收 =="
ACCEPT_DATE="${BP_ACCEPT_DATE:-$(date +%F)}"
log "验收交易日: $ACCEPT_DATE"
.venv/bin/python scripts/etl_e2e_acceptance.py --date "$ACCEPT_DATE" --json /tmp/etl-e2e.json | tail -8 || true
log "恢复脚本完成（e2e 若未全绿，bp-etl 会继续无限追赶）"
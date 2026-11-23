#!/usr/bin/env bash
# 旧行情 cron 灰度下线 / 回滚脚本（v3 五条 root crontab + 旧指数链 ad-hoc cron.d 行情条目）。
#
# 用法（服务器 root）：
#   bash scripts/etl_legacy_cron_toggle.sh dry-run   # 只打印将要改动的行，不做任何修改
#   bash scripts/etl_legacy_cron_toggle.sh disable   # 备份并注释/禁用旧行情任务
#   bash scripts/etl_legacy_cron_toggle.sh restore   # 从最近一次备份恢复
#
# 不触碰：加密合约 5 分钟、MVI、估值、基金风险、迁移等非行情 cron。
set -euo pipefail

MODE="${1:-dry-run}"
BACKUP_DIR="/opt/backup"
STAMP="$(date +%Y%m%d-%H%M%S)"

# root crontab 中要下线的行情任务匹配串（v3 日更 + 覆盖刷新）
CRON_PATTERNS=(
  "incremental_stock_quotes.py"
  "hk_stock_quotes.py"
  "etf_quotes.py"
  "incremental_fund_nav.py"
  "refresh_asset_coverage.py"
)

# /etc/cron.d 下要禁用的文件。
# P1 阶段：只处理 bp-fund-nav（其 nav 抓取已被 bp_etl 接管；该文件另行改写为仅保留风险重算）。
# P2 迁入旧指数链后，再把 bp-index-quotes / -retry / bp-xueqiu-quotes / bp-csindex-quotes /
# bp-index-extremes 加入此列表（脚本逻辑已支持）。
CRON_D_FILES=(
  # "bp-index-quotes"
  # "bp-index-quotes-retry"
  # "bp-xueqiu-quotes"
  # "bp-csindex-quotes"
  # "bp-index-extremes"
)

latest_backup() {
  ls -1t "$BACKUP_DIR"/etl-cron-backup-*.tar.gz 2>/dev/null | head -1 || true
}

if [[ "$MODE" == "dry-run" ]]; then
  echo "== dry-run：以下 root crontab 行会被注释 =="
  for pat in "${CRON_PATTERNS[@]}"; do
    crontab -l 2>/dev/null | grep -nF "$pat" | sed 's/^/  /' || true
  done
  echo "== dry-run：以下 /etc/cron.d 文件会被禁用 =="
  for f in "${CRON_D_FILES[@]}"; do
    [[ -f "/etc/cron.d/$f" ]] && echo "  /etc/cron.d/$f"
  done
  exit 0
fi

if [[ "$MODE" == "disable" ]]; then
  mkdir -p "$BACKUP_DIR"
  ARCHIVE="$BACKUP_DIR/etl-cron-backup-$STAMP.tar.gz"
  TMP="$(mktemp -d)"
  crontab -l > "$TMP/root.crontab" 2>/dev/null || true
  for f in "${CRON_D_FILES[@]}"; do
    [[ -f "/etc/cron.d/$f" ]] && cp "/etc/cron.d/$f" "$TMP/$f"
  done
  tar -czf "$ARCHIVE" -C "$TMP" . && rm -rf "$TMP"
  echo "备份完成: $ARCHIVE"

  # 注释 root crontab 中的行情任务行
  NEW_CRON="$(mktemp)"
  crontab -l 2>/dev/null | while IFS= read -r line; do
    hit=0
    for pat in "${CRON_PATTERNS[@]}"; do
      [[ "$line" == *"$pat"* ]] && hit=1
    done
    if [[ "$hit" == "1" ]]; then
      echo "# [bp-etl disabled $STAMP] $line"
    else
      echo "$line"
    fi
  done > "$NEW_CRON"
  crontab "$NEW_CRON"
  rm -f "$NEW_CRON"
  echo "root crontab 行情任务已注释"

  # 禁用旧行情 cron.d（改名 .disabled，可恢复）
  for f in "${CRON_D_FILES[@]}"; do
    if [[ -f "/etc/cron.d/$f" ]]; then
      mv "/etc/cron.d/$f" "/etc/cron.d/$f.disabled-$STAMP"
      echo "已禁用 /etc/cron.d/$f"
    fi
  done
  echo "完成。回滚: bash scripts/etl_legacy_cron_toggle.sh restore"
  exit 0
fi

if [[ "$MODE" == "restore" ]]; then
  ARCHIVE="$(latest_backup)"
  if [[ -z "$ARCHIVE" ]]; then
    echo "未找到备份（$BACKUP_DIR/etl-cron-backup-*.tar.gz）" >&2
    exit 1
  fi
  TMP="$(mktemp -d)"
  tar -xzf "$ARCHIVE" -C "$TMP"
  if [[ -f "$TMP/root.crontab" ]]; then
    crontab "$TMP/root.crontab"
    echo "root crontab 已恢复: $ARCHIVE"
  fi
  for f in "${CRON_D_FILES[@]}"; do
    if [[ -f "$TMP/$f" ]]; then
      mv -f "$TMP/$f" "/etc/cron.d/$f"
      echo "已恢复 /etc/cron.d/$f"
    fi
  done
  for stale in /etc/cron.d/*.disabled-*; do
    [[ -e "$stale" ]] && mv -f "$stale" "${stale%%.disabled-*}" && echo "清理禁用文件: $stale"
  done
  rm -rf "$TMP"
  echo "回滚完成"
  exit 0
fi

echo "未知模式: $MODE（可用 dry-run|disable|restore）" >&2
exit 2
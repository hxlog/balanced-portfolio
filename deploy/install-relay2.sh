#!/usr/bin/env bash
# 安装/更新第二 relay（bp-relay2）：仅本机 127.0.0.1:10810，不对外开放。
#
# 用法（服务器 root）：
#   bash deploy/install-relay2.sh                 # 使用已存在的 /etc/bp-relay2/config.json
#   bash deploy/install-relay2.sh --from FILE     # 从给定 JSON 安装（含 VLESS 节点参数，勿入 git）
#
# 说明：复用现有 /usr/local/bin/bp-relay（Xray）二进制；仓库只提供配置示例（占位符打码），
# 真实节点参数由运维写入 /etc/bp-relay2/config.json（600 权限），不进版本库。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_DIR="/etc/bp-relay2"
CONF="$CONF_DIR/config.json"
UNIT_SRC="$ROOT/deploy/bp-relay2.service"
UNIT_DST="/etc/systemd/system/bp-relay2.service"

if [[ "${1:-}" == "--from" ]]; then
  SRC="${2:?--from 需要配置文件路径}"
  install -d -m 700 "$CONF_DIR"
  install -m 600 "$SRC" "$CONF"
fi

if [[ ! -f "$CONF" ]]; then
  echo "缺少 $CONF：先把真实节点配置写入该文件（参考 deploy/bp-relay2.config.example.json）" >&2
  exit 1
fi

if [[ ! -x /usr/local/bin/bp-relay ]]; then
  echo "缺少 /usr/local/bin/bp-relay（应已由 bp-relay 服务安装）" >&2
  exit 1
fi

install -m 644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable bp-relay2 >/dev/null 2>&1 || true
systemctl restart bp-relay2
sleep 2
systemctl --no-pager --lines=0 status bp-relay2 | head -3

echo "== 探测 EM push2his（经 10810） =="
code="$(curl -sS -o /dev/null -w '%{http_code}' -x http://127.0.0.1:10810 \
  'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600036&fields1=f1&fields2=f51&klt=101&fqt=2&beg=20261101&end=20500101' \
  --max-time 20 || true)"
echo "EM HTTP: ${code:-fail}"
echo "完成。生产 .env 可设 BP_ETL_RELAY2=http://127.0.0.1:10810"

#!/usr/bin/env bash
# 部署 P5 Binance 代理 Worker 到 Cloudflare。
#
# 用法:
#   export CLOUDFLARE_API_TOKEN=...        # 必需（Workers Scripts:Edit）
#   export CLOUDFLARE_ACCOUNT_ID=...       # 可选（多账号时建议）
#   ./scripts/deploy_worker.sh [--dry-run]
#
# 缺少 token 时给出友好提示并退出，不做任何网络请求。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT_DIR/workers/binance-proxy"

DRY_RUN=0
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=1
    fi
done

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" && "$DRY_RUN" -eq 0 ]]; then
    cat >&2 <<'EOF'
[deploy_worker] 缺少 CLOUDFLARE_API_TOKEN，已中止（未发起部署）。

修复方式：
  1. Cloudflare Dashboard → My Profile → API Tokens → Create Token
     权限: Account · Workers Scripts · Edit
           Account · Account Settings · Read
  2. export CLOUDFLARE_API_TOKEN="..."
     export CLOUDFLARE_ACCOUNT_ID="..."   # 可选，多账号时建议
  3. 重新执行 ./scripts/deploy_worker.sh

仅想验证打包（不发请求/不需要 token）：
  ./scripts/deploy_worker.sh --dry-run
EOF
    exit 2
fi

if ! command -v node >/dev/null 2>&1; then
    echo "[deploy_worker] 未找到 node，请安装 Node.js 20+（CI 使用 Node 24）。" >&2
    exit 2
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "[deploy_worker] 未找到 npm，请安装 Node.js 20+（含 npm）。" >&2
    exit 2
fi
if [[ ! -d "$WORKER_DIR" ]]; then
    echo "[deploy_worker] Worker 目录不存在: $WORKER_DIR" >&2
    exit 2
fi

cd "$WORKER_DIR"

if [[ ! -d node_modules ]]; then
    echo "[deploy_worker] 首次部署，安装依赖..."
    if [[ -f package-lock.json ]]; then
        npm ci
    else
        npm install
    fi
fi

echo "[deploy_worker] 离线单测..."
npm test

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[deploy_worker] 打包校验（不发布）..."
    npx wrangler deploy --dry-run "$@"
    echo "[deploy_worker] 打包通过。"
else
    echo "[deploy_worker] 部署到 Cloudflare..."
    npx wrangler deploy "$@"
    echo "[deploy_worker] 完成。请把 Worker URL 配置到生产环境 BP_BINANCE_PROXY_URL。"
fi

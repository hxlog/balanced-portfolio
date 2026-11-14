# binance-proxy（Cloudflare Worker）

P5 加密合约看板的中转层。生产服务器无法直连 Binance（timeout），由本 Worker
转发 5 个**无需签名**的 Binance USDT 永续公开端点。Worker 不保存、不转发任何
API Key/Secret。

## 转发白名单

| `?path=` | 说明 | 必填参数 |
|---|---|---|
| `/fapi/v1/exchangeInfo` | 合约元数据（筛选 USDT 永续） | — |
| `/fapi/v1/ticker/24hr` | 24h 行情（按 `quoteVolume` 排名） | — |
| `/fapi/v1/premiumIndex` | 标记价 / 指数价 / 资金费率 | — |
| `/fapi/v1/openInterest` | 当前未平仓合约量 | `symbol` |
| `/futures/data/globalLongShortAccountRatio` | 全市场多空账户比 | `symbol` |
| `/futures/data/takerlongshortRatio` | 主动买卖量比 | `symbol` |
| `/futures/data/openInterestHist` | OI 历史（5m/…） | `symbol` |

`exchangeInfo` / `ticker/24hr` 是 `bp_ingest/crypto_futures.py::fetch_contracts()`
筛选 Top 30 的必需输入；生产服务器无法直连 Binance，因此一并经本 Worker 转发。

请求示例：

```bash
curl "https://binance-proxy.<account>.workers.dev/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT"
curl "https://binance-proxy.<account>.workers.dev/?path=/futures/data/openInterestHist&symbol=BTCUSDT&period=5m&limit=1"
```

除 `path` 外的 query 原样透传；非白名单路径返回 `403 path_not_allowed`，
缺少 `symbol` 返回 `400 missing_symbol`。

## 行为

- **缓存**：成功响应写入 `caches.default`，`Cache-Control: public, max-age=300`
  （5 分钟）。上游 4xx/5xx 与网络异常不缓存。
- **限频**：按 `CF-Connecting-IP` 每 60 秒 120 次；超限 `429 rate_limited` +
  `Retry-After`。实现为 Worker isolate 内的固定窗口，横向扩容时是“每实例”
  配额；若需要严格全局配额，请在 Cloudflare 控制台配置 Rate Limiting 规则
  或改用 Durable Object。
- **CORS**：仅 `https://xushilu.com`（可用 `[vars] ALLOWED_ORIGIN` 覆盖）。
  预检 `OPTIONS` 返回 204，不消耗限频额度。
- 只接受 `GET`；其他方法返回 `405 method_not_allowed`。

## 本地开发

```bash
cd workers/binance-proxy
npm install
npm test          # Node 24 原生 type-stripping，离线单测（不访问 Binance）
npm run typecheck  # tsc --noEmit（需先 npm install）
npx wrangler dev   # 本地 Worker（会真实访问 Binance）
```

本地不配 Worker 时，后端可直接直连 Binance（见 `bp_ingest/crypto_futures.py`）。

## 部署

### 方式 A：wrangler 交互登录

```bash
cd workers/binance-proxy
npm install
npx wrangler login
npx wrangler deploy
```

### 方式 B：API Token（CI / 无浏览器服务器，推荐）

1. Cloudflare Dashboard → My Profile → API Tokens → Create Token。
2. 权限至少包含：
   - **Account · Workers Scripts · Edit**
   - **Account · Account Settings · Read**
3. 导出环境变量（不要写入 git / `.env` 提交）：

```bash
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ACCOUNT_ID="..."   # 可选；多账号时建议设置
```

4. 部署：

```bash
./scripts/deploy_worker.sh
# 或：cd workers/binance-proxy && npx wrangler deploy
```

`scripts/deploy_worker.sh` 在缺少 `CLOUDFLARE_API_TOKEN` 时会直接给出修复提示并
退出；使用 `--dry-run` 可在无 token 时做一次打包校验。

### 运行期 secrets

当前**不需要**任何运行期 secret：5 个端点都是公开只读接口，Worker 不持有
Binance API Key。`ALLOWED_ORIGIN` 是普通 `[vars]`，不是 secret。

如果后续要给代理增加调用方鉴权，使用：

```bash
npx wrangler secret put PROXY_TOKEN
```

并在 `src/index.ts` 中校验 `Authorization`，不要把 token 写进 `wrangler.toml`。

## 配置后端

部署完成后，在生产环境 `.env` 设置：

```bash
BP_BINANCE_PROXY_URL=https://binance-proxy.<account>.workers.dev
```

`bp_ingest/crypto_futures.py` 会自动把请求改写成
`{BP_BINANCE_PROXY_URL}/?path=...`；未配置时直连 `https://fapi.binance.com`。

## 返回码

| 状态 | error.code | 含义 |
|---|---|---|
| 400 | `missing_path` / `missing_symbol` | 参数缺失 |
| 403 | `path_not_allowed` | 白名单外路径 |
| 405 | `method_not_allowed` | 非 GET/OPTIONS |
| 429 | `rate_limited` | 超过 120 req/min |
| 502 | `upstream_unreachable` | 连接 Binance 失败 |

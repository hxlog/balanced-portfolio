# Balanced Portfolio

[![CI](https://github.com/hxlog/balanced-portfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/hxlog/balanced-portfolio/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Balanced Portfolio 是基于桥水基金风险平价理论的投资组合管理与回测系统，功能包括中金所股指期货描述性统计和场外期权自动敲入敲出产品(autocallables)结构化产品定价功能**，供广大投资者参考和交流学习。

项目官网/Demo：https://xushilu.com

Demo的测试账户和密码都是`test1`

介绍与说明（长文）：[我全栈开发的第一个产品：Balanced Portfolio 多资产风险平价全天候策略回测系统](https://prologue.dev/blog/my-first-full-stack-development-project-balanced-portfolio-a-global-multi-asset-risk-parity-backtesting-system)

## 主要功能

- **风险平价组合**：按GDP增长/宏观通胀二分法划分四象限，将四种不同经济场景里分配对应经济场景占优的投资品种，优化算法包括`最大化夏普/Sortino`，`象限内最大优化指标、象限间等风险贡献`，`全资产风险平价`、`按优化指标分配风险预算`共四种方法，输出优化后的投资品权重、组合单位净值、历史调仓、风险指标、相关性和绩效归因。
- **中金所股指期货数据看板**：跟踪 IF、IH、IC、IM 及对应指数，展示同一交易日口径的收盘快照、历史年化升贴水及分位值统计。
- **加密货币相关性看板**：比特币对数日收益率与黄金（COMEX/沪金）、标普500、纳斯达克100 的滚动相关系数（Pearson/Spearman/Kendall/Hoeffding），以及 BTC 与远期美元指数 (DXY) 的走势。
- **场外期权自动敲入敲出(autocallables)结构化产品定价**：覆盖雪球、凤凰、气囊和障碍产品，支持Monte Carlo、BSM求解、积分法定价，模型求解输出公允价值、PV值、PoL、Delta/Gamma/Vega/Theta/Rho 与存续路径状态。
- **机构级别的数据可视化**：打造一个开箱即用、可交互的、可视化的投资组合分析与回测工具，以及丰富的数据可视化图表。

## 功能展示

### 风险平价回测系统

![风险平价回测结果](/docs/balanced_portfolio_dashboard_example.avif)

### 股指期货数据看板

![股指期货数据看板](/docs/balanced_portfolio_futures.jpeg)

### 场外衍生品定价

![场外衍生品定价](/docs/balanced_portfolio_otc_derivatives_pricing.avif)

## 技术栈

系统分四层：

```text
akshare → bp_ingest（落库 / 清洗）→ PostgreSQL 18 + TimescaleDB → bp_api（FastAPI 量化引擎）→ web（Next.js）
```

| 组件 | 技术 | 说明 |
| --- | --- | --- |
| 数据源 | akshare, 东方财富, Yahoo Finance | A 股 / 港股 / 商品 / 海外指数 / 加密货币 / 美元指数 |
| 数据库 | PostgreSQL 18 + TimescaleDB ≥ 2.23 | 存储日行情 hypertable、压缩、增量更新、投资组合簿记 |
| 后端 | FastAPI + psycopg3  | 模型结果预计算和接口请求 |
| 计算 | numpy + scipy | 风险平价与风险预算模型用循环坐标下降法（Spinu CCD），最大比率用连续最小二乘法（SLSQP）求解 |
| 任务队列 | Celery + Redis | 异步回测 / 全量拉取 / 定时调度检查增量，若无 Redis时降级为BackgroundTasks |
| 鉴权 | PyJWT + bcrypt + pyotp | JWT + TOTP 两步验证 + httpOnly Cookie |
| 前端 | Next.js 16 App Router + React 19 | Tailwind v4 + shadcn/Radix + ECharts |

行情通过 [AKShare](https://github.com/akfamily/akshare) 和[Yahoo Finance](https://github.com/ranaroussi/yfinance)获取日行情并写入 PostgreSQL/TimescaleDB，底层来源包括交易所及东财、新浪、Yahoo Finance等公开接口，具体来源由资产配置决定。

原始行情不会直接进入回测：系统先按 A 股交易日历进行对齐，线性填补内部缺口，剔除A股休市情况下的海外周末行情。

回测只会使用每个交易日当日及之前的滚动窗口数据，未来收益不会改变历史净值。

组合回测、OTC 定价和全量行情任务采用`Redis + Celery`异步执行。本地开发可设置 `BP_TASK_MODE=inline`，由 FastAPI `BackgroundTasks` 执行，不需要启动 Redis 和 worker。

## 系统架构

Balanced Portfolio 由行情接入、数据库、量化与业务 API、Web 前端四层组成：

```text
AKShare
   │
   ▼
bp_ingest ──► PostgreSQL 18 + TimescaleDB
                    │
                    ▼
            Redis + Celery worker
                    │
                    ▼
              bp_api / quant
                    │
                    ▼
               Next.js web
```

生产环境在 API 与耗时计算之间增加 Redis、Celery worker 和定时任务；开发环境可用 FastAPI 后台任务代替。

## 数据接入

`bp_ingest` 工具通过适配器调用 AKShare，增量写入指数、ETF、商品、加密货币和 CFFEX 股指期货行情。`bp_index_quote_daily` 表保存原始 OHLCV，是组合回测行情的单一事实源。

常规更新流程：

1. 按资产配置和回看天数（.env里配置）拉取增量行情。
2. 对近期数据做覆盖写入，以接收上游修订。
3. 刷新清洗行情和资产数据状态。
4. 找出数据已推进的组合并提交重算任务。


## 清洗行情

组合回测只读取 `bp_quote_clean`表，不直接读取原始行情。清洗流程以 A 股交易日历为基准：

1. 把各资产价格重建到统一交易日索引。
2. 对有前后有效价格锚点的内部缺口根据上一个值进行填充。
3. 保留资产上市前的前导空白，由回测的有效起始日处理。
4. 若资产在回测区间尾部停止更新且无法插值填充，构建面板时直接报错。
5. 基于清洗后的价格重新计算收益率，保证协方差、净值、回撤和归因使用同一口径。

这套处理便于跨市场资产对齐，但插值价格不等于可成交价格。涉及实盘执行时，应采用与目标市场一致的交易日历、汇率、复权和停牌处理规则。

## 风险平价与回测

平台支持四种组合优化方法：

- `quadrant_inner_sharpe_outer_rp`：象限内最大夏普或 Sortino，象限间等风险贡献。
- `all_risk_parity`：全部资产等风险贡献。
- `all_max_sharpe`：全部资产最大夏普或 Sortino。
- `sharpe_sq_risk_budget`：按单资产比率平方分配风险预算。

等风险贡献和风险预算使用循环坐标下降求解，最大比率问题使用连续最小二乘法（SLSQP）。无风险利率、回看窗口和再平衡偏离带保存在组合上，环境变量只提供新建组合或缺省场景的默认值。

回测按交易日推进。每一天重新取不晚于当天的滚动窗口，计算当日目标权重；任一资产的实际权重偏离目标超过组合设定阈值时，整个组合再平衡。新资产在积累到最小回看窗口后才加入，不会拖延其他资产的回测起点。

## CFFEX 看板

CFFEX 模块覆盖 IF、IH、IC、IM 及沪深 300、上证 50、中证 500、中证 1000：

- 现货指数收盘价复用资产管理日 K 表（`bp_quote_clean` / `bp_index_quote_daily`），不另建实时源。
- 日 K 源盘中会把最新价写入当日 close；入库与看板均在上海时区 **15:10** 后才认「今日」正式收盘（`BP_CLOSE_CONFIRM_HHMM` 可调）。盘中写入的今日行会被丢弃；若已误写入，收盘后强制重拉覆盖，且看板在 `updated_at` 未过确认时刻前会回退到上一完整交易日。
- ingest 定期拉取合约日行情并计算升贴水，现货修正后会重算近窗 premium。
- 快照只选择期货品种和挂钩指数在同一交易日齐全、且收盘已确认的数据，避免混日与盘中脏价。
- API 提供收盘快照、历史走势和统计分位，Redis 可缓存查询结果（盘前/盘后分桶）。



## OTC 定价

`bp_api/quant/otc` 是基于 NumPy/SciPy 的定价实现，覆盖雪球、凤凰、气囊和障碍结构：

- 全品种支持批量 GBM 蒙特卡洛。
- 障碍和气囊结构支持相应解析方法。
- Greeks 使用共同随机数的 bump-and-reprice。
- 交易日、观察日调整和 ACT/365、ACT/360、BUS/252 日计数由日历模块处理。
- 定价结果、存续状态和路径图可由异步任务计算并持久化。

模块的产品分层、术语和参数命名参考 Apache-2.0 许可的 [pricelib](https://gitee.com/lltech/pricelib)，运行时定价代码不依赖 pricelib。

## 异步任务

创建、修改、复制或重算组合时，API 先写入 `bp_task`，再派发计算：

```text
请求 ─► 数据库任务记录 ─► Celery/Redis ─► worker ─► 结果表
                         │
                         └─ 失败或 inline 模式 ─► FastAPI BackgroundTasks
```

生产环境建议保持 Redis、`bp-worker` 和 `bp-beat` 运行。`bp-beat` 定期检查可推进到最新行情日的组合；`bp-ingest` 也有轻量巡检作为补充。本地开发可设置 `BP_TASK_MODE=inline` 后，不需要单独运行队列。

## API、鉴权与前端

FastAPI 提供组合、行情、CFFEX、OTC、任务、管理和鉴权接口。JWT 用于身份校验，管理员必须绑定 TOTP；Redis 可用于登录限流和结果缓存。

Next.js 使用 App Router。浏览器登录时，`web/app/api/session` Route Handler 负责写入 httpOnly `bp_session` Cookie。因此生产反向代理必须区分两类路径：

```text
/api/session*  ─► Next.js :3000
/api/*         ─► FastAPI :8000
/*             ─► Next.js :3000
```

若把所有 `/api/` 都转给 FastAPI，登录会返回 404。具体配置见 [部署说明](deployment.md)。

## 主要持久化对象

- 原始行情与清洗行情。
- 资产、数据源、交易日历及数据状态。
- 用户、权限、TOTP 和会话相关状态。
- 组合定义、象限资产和组合级参数。
- 净值、调仓、指标、相关性、末日持仓和绩效归因。
- CFFEX 合约行情与升贴水序列。
- OTC 交易、定价结果和历史。
- 异步任务状态、进度和错误信息。

数据库定义以 `ddl/schema.sql` 为全新安装基线。


## 环境要求

- Python 3.11–3.14
- Node.js 20+
- PostgreSQL 18
- TimescaleDB 2.23+（建议使用当前稳定版）
- `psql` 命令行工具

## Quick Start

1. 克隆仓库并创建配置：

   ```bash
   git clone https://github.com/hxlog/balanced-portfolio.git
   cd balanced-portfolio
   cp .env.example .env
   ```

   编辑 `.env`，至少填写数据库连接、JWT 密钥和首次管理员凭据。开发环境可使用 inline 任务模式：

   ```env
   PGPASSWORD=<database-password>
   BP_JWT_SECRET=<random-long-secret>
   <!-- JWT推荐生成高强度密钥 -->
   BP_ADMIN_EMAIL=admin@example.com
   <!-- 管理员账户的又想和密码 -->
   BP_ADMIN_INITIAL_PASSWORD=<initial-admin-password>
   <!-- inline是开发模式，生产环境可使用redis（填写celery） -->
   BP_TASK_MODE=inline
   ```

   可用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成 JWT 密钥，管理员创建成功后可从运行环境移除 `BP_ADMIN_INITIAL_PASSWORD`，或直接在数据库里的`bp_admin_user`修改。

2. 安装 Python 依赖：

   ```bash
   python -m venv .venv
   # Linux/macOS
   source .venv/bin/activate
   # Windows PowerShell
   # .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. 初始化数据库。全新环境只执行合并后的 schema，不要再逐个执行旧编号脚本：

   ```bash
   createdb -h localhost -U postgres balanced_portfolio
   psql -h localhost -U postgres -d balanced_portfolio -f ddl/schema.sql
   ```

4. 拉取并清洗行情：

   ```bash
   python -m bp_ingest run
   ```

5. 启动后端：

   ```bash
   uvicorn bp_api.main:app --host 127.0.0.1 --port 8000 --reload
   ```

6. 在另一个终端启动前端：

   ```bash
   cd web
   npm install
   npm run dev
   ```

打开 <http://localhost:3000>。后端健康检查地址为 <http://localhost:8000/api/health>，OpenAPI 页面为 <http://localhost:8000/docs>。若 API 不在本机 `8000` 端口，启动前端前设置 `BP_API_BASE`。

## 常用命令

```bash
# 行情调度测试
python -m bp_ingest ping

# 行情调度启动
python -m bp_ingest run

# 行情调度只提取沪深300和恒生指数，不自动清洗数据
python -m bp_ingest run --symbols 000300 HSI --no-clean

# 部分数据走yahoo finance需要代理，国内云服务器无法访问，需要在开发环境连代理补数据
python -m bp_ingest run --symbols BTC-USD

# 清洗行情数据，将交易日标准化成A股交易日，再计算涨跌幅
python -m bp_ingest clean

# 行情调度任务，建议配合pm2使用
python -m bp_ingest schedule

# 中金所股指期货行情跑增量
python -m bp_ingest cffex-backfill

# 中金所股指期货行情跑全量（会删除历史期货行情数据！！！）
python -m bp_ingest cffex-backfill --full 

# 中金所股指期货数据重新计算基差和贴水
python -m bp_ingest cffex-backfill --recompute-premium

# 后端服务启动，建议配合pm2
uvicorn bp_api.main:app --host 127.0.0.1 --port 8000 --reload

# redis celery查询
celery -A bp_api.workers.celery_app worker -c 2

# 前端next.js的开发与build命令
cd web
npm run dev
npm run build
```

## 测试

```bash
# CI测试
python -m pytest bp_api/tests -q
cd web && npm run build
```

后端测试覆盖优化权重、ERC、绩效指标、CFFEX 数据口径、OTC 定价和无未来函数约束。提交前请同时确认前端生产构建通过。

## 部署说明

本文说明如何手工部署 Balanced Portfolio。项目当前不提供 Docker 编排；生产模板采用 Linux、PM2 和 Nginx。

### 1. 准备环境

建议使用一台应用服务器和一套 PostgreSQL/TimescaleDB 数据库。最低软件要求：

- Python 3.11–3.14
- Node.js 20+
- PostgreSQL 18
- TimescaleDB 2.23+
- Redis
- PM2、Nginx、`psql`、Git

数据库应只允许应用服务器或内网访问，不要向公网开放 `5432`。应用服务器只需公开 `80` 和 `443`。

### 2. 获取代码

```bash
sudo mkdir -p /opt/balanced-portfolio
sudo chown "$USER:$USER" /opt/balanced-portfolio
git clone https://github.com/hxlog/balanced-portfolio.git /opt/balanced-portfolio
cd /opt/balanced-portfolio
```

创建 Python 虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd web
npm ci --legacy-peer-deps
cd ..
```

### 3. 配置环境变量

```bash
cp .env.example .env
chmod 600 .env
```

至少检查以下配置：

```env
PGHOST=<database-host>
PGPORT=5432
PGDATABASE=<database-name>
PGUSER=<database-user>
PGPASSWORD=<strong-database-password>

BP_CORS_ORIGINS=https://<your-domain>
BP_JWT_SECRET=<random-long-secret>
BP_ADMIN_EMAIL=<admin@example.com>
BP_ADMIN_INITIAL_PASSWORD=<initial-admin-password>
BP_API_BASE=http://127.0.0.1:8000
BP_SITE_URL=https://<your-domain>
# /crypto 看板: 后端重算后 ping Next.js 失效 SSR 缓存(可选; 不设则靠 cacheLife TTL 兜底)
BP_WEB_BASE=https://<your-domain>
BP_INTERNAL_REVALIDATE_TOKEN=<random-32+-chars>
BP_CRYPTO_CLOSE_CONFIRM_HHMM=1600

REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
BP_TASK_MODE=celery
```

生产环境必须显式设置随机的 `BP_JWT_SECRET`，不要依赖数据库密码派生。`BP_ADMIN_INITIAL_PASSWORD` 只在首次创建管理员时使用，创建成功并修改密码后可从运行环境移除。

### 4. 初始化数据库

全新数据库只执行合并后的 schema：

```bash
set -a
source .env
set +a

# 数据库尚未创建时，先使用具备 CREATEDB 权限的账号执行：
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"

psql \
  -h "$PGHOST" \
  -p "$PGPORT" \
  -U "$PGUSER" \
  -d "$PGDATABASE" \
  -f ddl/schema.sql
```

数据库已经存在时跳过 `createdb`；应用账号没有建库权限时，由数据库管理员预先创建数据库和扩展。

验证连接并完成首轮行情：

```bash
source .venv/bin/activate
python -m bp_ingest ping
python -m bp_ingest run
```

首轮拉取耗时取决于资产数量、起始日期和上游限流。遇到单一资产失败时，先核对资产代码和 AKShare 接口，不要直接跳过清洗错误。

### 5. 构建并启动服务

项目提供 PM2 配置，包含：

- `bp-api`：FastAPI，监听 `127.0.0.1:8000`
- `bp-web`：Next.js，监听 `127.0.0.1:3000`
- `bp-ingest`：行情定时更新
- `bp-worker`：Celery worker
- `bp-beat`：Celery 定时巡检

```bash
cd /opt/balanced-portfolio
export APP_ROOT=/opt/balanced-portfolio
set -a
source .env
set +a

cd web
npm run build
cd ..

pm2 start deploy/ecosystem.config.cjs
pm2 save
pm2 startup
```

`pm2 startup` 会输出一条需要 `sudo` 执行的命令，按终端提示完成即可。

### 6. 配置 Nginx 与 HTTPS

复制模板并替换域名：

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/balanced-portfolio
sudo editor /etc/nginx/sites-available/balanced-portfolio
sudo ln -s /etc/nginx/sites-available/balanced-portfolio \
  /etc/nginx/sites-enabled/balanced-portfolio
sudo nginx -t
sudo systemctl reload nginx
```

模板中最重要的是 Session 路由顺序：

```nginx
location /api/session {
    proxy_pass http://bp_web;
}

location /api/ {
    proxy_pass http://bp_api;
}
```

`/api/session` 必须写在通用 `/api/` 之前，并转给 Next.js。它负责写入 httpOnly Cookie；FastAPI 没有这个路由。

确认 HTTP 可访问后，用 Certbot 或现有证书系统启用 HTTPS：

```bash
sudo certbot --nginx -d <your-domain>
sudo certbot renew --dry-run
```

### 7. 更新同步

服务器端发版脚本会拉取代码、更新 Python 和前端依赖、构建前端、重载 PM2、执行健康检查并在配置有效时重载 Nginx：

```bash
cd /opt/balanced-portfolio
bash deploy/deploy.sh
```

发版前应在开发或 CI 环境执行：

```bash
python -m pytest bp_api/tests -q
cd web && npm run build
```

如果版本包含新的编号数据库迁移，先阅读迁移内容并安排备份和维护窗口，再对已有数据库单独执行。`deploy.sh` 不会自动执行数据库迁移。

### 8. 发布后检查

```bash
pm2 status
curl -fsS http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:3000/api/session
sudo nginx -t
redis-cli ping
```

未登录时 Session 地址应返回鉴权相关状态，不能是 `404`。同时检查：

- `bp-api`、`bp-web`、`bp-ingest`、`bp-worker`、`bp-beat` 均为 `online`。
- 首页和 API 可通过 HTTPS 访问。
- 新建组合能从 `queued/running` 进入 `done`。
- 行情最新日期和组合 `data_as_of_date` 符合预期。
- 日志中没有持续的数据库连接、上游限流或任务重试错误。


## 许可证

本项目按 [Apache License 2.0](LICENSE) 发布。第三方组件仍适用各自许可证。

## 更新日志（since v1.0.0）

### 新功能

- **加密货币相关性看板**（`/crypto`）：BTC 与黄金（COMEX/沪金）、标普500、纳斯达克100 的对数日收益率滚动相关性 + BTC vs 美元指数 (DXY) 远期走势。4 种方法（Pearson/Spearman/Kendall/Hoeffding）×4 窗口（3/6/9/12 月）。预计算落库（`bp_crypto_corr_daily` 64 series-per-row JSONB + `bp_crypto_meta`），NYSE 16:00 ET 双时区「数据截至」带时分（ET + 北京时间，DST 自洽），`bp_ingest.run` 钩子 + 每日定时任务重算，API 只读、请求路径永不计算，Next.js→Redis→DB 三层缓存。
- **yfinance 数据源**：crypto/forex/commodity 日线（BTC-USD、美元指数 DXY、COMEX 黄金期货），与 AKShare 行情共用 `bp_ingest` 增量/清洗/调度链路。

### 2026-07 优化与修复

- **加密看板数据源切换**：DXY（美元指数）与 COMEX 黄金从 yfinance 切到**东方财富**（`dxy_em` 直连 push2his secid=100.UDI；`gold_comex_em` = akshare `futures_foreign_hist("GC")`），生产服务器不再受 Yahoo 429 限流影响；BTC-USD 保留 yfinance（由 atomicity hold-back 兜底）。迁移 `ddl/33_crypto_source_em.sql`，`bp_ingest/sources.py` 新增 2 个 EM 适配器。
- **加密看板原子性 + hold-back**：`effective_td` 恢复 CFFEX 式「6 资产同日齐全 + NYSE 16:00 ET 收盘确认」门槛（修复此前放宽导致用 ffill 假价冒充最新收盘的 bug）；任一资产缺口则看板 hold 在前一完整日 + 琥珀「数据待齐」徽章（`is_synced`），不再冒进。预计算输出截断至 `effective_td` + 删残留行；`symbols_by_date` 只统计真实非 NaN 收盘日，杜绝 interp 假日被误判齐全。
- **1h crypto 增量调度**：新增 `crypto_job`（每 1h 拉 6 资产 → 钩子重算），镜像 CFFEX `cffex_job`；保留每日 05:30 北京兜底。仅 `effective_td`/`is_synced` 推进才 bump version + ping SSR revalidate（no-op 不刷 cacheTag）。
- **yfinance 陈旧可见化**：`bp_ingest/ingest.py::_sync_one` 加 STALE 探测（源未推进或滞后超 `BP_STALE_TOL_DAYS`=3 → 打 WARNING + 计入汇总），让 prod IP 被 Yahoo 429 时不再静默吞掉。
- **首页加密看板 section**：`/` 新增全宽扁平 crypto 看板卡（6 资产快照 + 4 个 3M Pearson 相关值 + BTC 滚动相关性 SVG sparkline + 数据截至/数据待齐徽章 + CTA），PPR 动态洞 + `cacheTag "crypto"` 与 `/crypto` 同步刷新；扁平/现代风（无 shadow、细边框、monospace 价格）。

## 数据与投资免责声明

AKShare 聚合公开数据接口，数据源可能调整、延迟、限流、修订或停止服务。项目不保证行情、交易日历、复权、基差、波动率、定价结果和回测结果完整、准确或持续可用，使用者应自行核验数据授权、质量和适用性。

本项目仅用于软件开发、教学和研究，不构成投资建议、交易信号、估值意见、要约或任何收益承诺。回测和模型价格不代表未来表现或可成交价格，实盘决策及损失由使用者自行承担。

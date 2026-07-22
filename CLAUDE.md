# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Balanced Portfolio 是基于桥水风险平价理论的投资组合管理与回测系统，外加中金所股指期货看板和场外期权(autocallables)定价。四层架构：

```
AKShare → bp_ingest → PostgreSQL 18 + TimescaleDB → bp_api/quant → Next.js web
```

生产环境在 API 与耗时计算之间插入 Redis + Celery；本地开发用 `BP_TASK_MODE=inline` 走 FastAPI `BackgroundTasks`，无需 Redis/worker。详细架构见 `docs/architecture.md`。

## Common commands

```bash
# 后端
uvicorn bp_api.main:app --host 127.0.0.1 --port 8000 --reload

# 前端 (Next.js 16 + Turbopack, port 3000)
cd web && npm install --legacy-peer-deps   # --legacy-peer-deps 必须
cd web && npm run dev
cd web && npm run build                    # CI 也跑这个
cd web && npm run typecheck                # tsc --noEmit

# 测试 (后端, 合成 GBM 行情夹具, 见 bp_api/tests/conftest.py)
python -m pytest bp_api/tests -q
python -m pytest bp_api/tests/test_backtest.py -q          # 单文件
python -m pytest bp_api/tests -k no_future -q              # 单测/关键字

# 行情 ingest
python -m bp_ingest ping
python -m bp_ingest run                                   # 增量更新全部标的
python -m bp_ingest run --symbols 000300 HSI --no-clean
python -m bp_ingest clean                                 # 重建 bp_quote_clean
python -m bp_ingest schedule                              # 每 6h 定时调度
python -m bp_ingest cffex-backfill                        # CFFEX 增量
python -m bp_ingest cffex-backfill --full                 # 全量(删历史重拉!)
python -m bp_ingest cffex-backfill --recompute-premium

# Celery (生产; 本地 inline 模式不需要)
celery -A bp_api.workers.celery_app.celery_app worker -c 2
celery -A bp_api.workers.celery_app.celery_app beat

# 数据库 (全新环境只执行合并 schema, 勿再跑旧编号脚本)
psql -h localhost -U postgres -d balanced_portfolio -f ddl/schema.sql
```

提交前必跑：`python -m pytest bp_api/tests -q` 且 `cd web && npm run build`（CI 同口径，见 `.github/workflows/ci.yml`，Python 3.11 / Node 24）。

## 数据流与行情口径（修改回测/行情前必读）

- **单一事实源**：`bp_index_quote_daily` 保存原始 OHLCV；组合回测**只读** `bp_quote_clean`，绝不直接读原始表。
- **清洗规则**（`bp_api/quant/cleaning.py`，由 `bp_ingest clean` 或 ingest 自动刷新）：以 A 股交易日历重建面板 → 有左右锚点的内部缺口线性插值（`fill_flag=interp`）→ 保留前导空白（由回测 effective_start 处理）→ **尾部无右端锚点的缺口直接报错** → 基于清洗价重算收益率，保证协方差/净值/回撤/归因同口径。插值价 ≠ 可成交价。
- **收盘确认**：盘中今日行不入库；上海时区 15:10（`BP_CLOSE_CONFIRM_HHMM`）后才认「今日」收盘。CFFEX 快照要求期货品种与挂钩指数同交易日齐全且收盘已确认。
- **资产 key**：`{symbol}@{source}`（如 `000300@cn_index_em`），全栈通用。

## 回测与优化引擎（`bp_api/quant/`）

- 四种优化方法，前端 `web/lib/api.ts` 的 `METHOD_OPTIONS` 必须与后端一致：
  - `quadrant_inner_sharpe_outer_rp`（默认）：象限内最大化 sharpe/sortino × 象限间等风险贡献(ERC)
  - `all_risk_parity`、`all_max_sharpe`、`sharpe_sq_risk_budget`
- 求解器：ERC/风险预算用 Spinu 循环坐标下降(CCD)；最大比率用 SLSQP（支持 cov/mean 预算入参 + 上次权重热启动 `x0`）。
- **无未来函数**：`backtest.py` 用前缀和(cum1/cum2)做滚动增量矩，把每日窗口预算从 O(window·n²) 降到 O(n²)；当日 NAV 用当日收益更新，次日才用新权重。`test_backtest.py` 固定约束：篡改某日之后的收益不得改变该日之前的净值/持仓。
- 成分逐步纳入：不足 `min_window` 历史的品种权重为 0，不拖后整体 effective_start。
- 再平衡：任一品种漂移偏离目标 > `rebalance_band`(绝对值，默认 5pp) → 整体回到当日最优目标。

## 任务模型（`bp_api/tasking.py` / `workers/` / `tasks.py`）

- API 先写 `bp_task` 行（`tasking.create_task`），**事务提交后**再 `_dispatch_backtest`，避免 worker 看不到未提交行。
- `enqueue_task` 在 `BP_TASK_MODE=inline` 或 `send_task` 失败时返回 `None`，调用方降级到 `BackgroundTasks`（`tasks.run_*_background`）。Redis/Celery 全程是「可选增强」，缺失不阻断核心功能。
- Celery 任务：`bp_api.backtest`、`bp_api.ingest_all`、`bp_api.price_otc`、`bp_api.refresh_calendar`、`bp_api.enqueue_ready`。
- beat 每 20 分钟巡检排队就绪组合的 T-1 更新（`bp_api.enqueue_ready`），与 bp_ingest 的 6h 调度解耦；每周刷新交易日历。
- worker 启动时硬化 HTTP 会话 + 预热 EM 代码映射（`worker_process_init`），否则 ingest 走 Celery 时 push2his 会被掐断。
- 组合状态：`pending → running → done/error`；`running` 时编辑返回 409。结果按 `method`/`benchmark` 维度用 `cache.set_json` 缓存（带 result version 的 ETag）。

## API 层（`bp_api/`）

- `main.py` 是 FastAPI 入口；`cffex.py` 和 `otc_api.py` 通过 `register_routes(app)` 自注册。所有路由前缀 `/api/`。
- `db.py`：psycopg3 `ConnectionPool`（min 1 / max 8，`autocommit=False`）。用 `with db.get_conn() as conn:` 取连接，**提交必须显式 `conn.commit()`**。
- `repositories.py`（~1250 行）是数据访问层：资产清单、价格面板、组合 CRUD、`run_and_save` 编排回测（4 种方法并行，`ProcessPoolExecutor`；Celery 守护进程内自动回退 `ThreadPoolExecutor`）。新增数据读写应放这里。
- `repositories_otc.py`：OTC 交易与定价历史、交易日历刷新。
- **NaN/Inf 必须清洗**：所有 `Json()` 实参走 `_json_safe`，权重走 `_round`——psycopg 拒绝 NaN/Infinity token。
- `auth.py`：JWT + 管理员强制 TOTP。`require_user` / `require_super_admin` / `optional_user` 三个依赖。
- `cache.py`：Redis 封装，缺失时全部降级为 miss（不影响功能）。
- `settings.py`：`load_settings()` 在 `main.py` import 时执行一次；`BP_JWT_SECRET` 必填且 ≥32 字符，否则启动报错。组合级参数（risk_free/lookback/rebalance_band）存在组合上，环境变量仅作新建兜底。

## 鉴权与前端 Session（容易踩坑）

- 浏览器登录时，**Next.js Route Handler `web/app/api/session/route.ts` 写 httpOnly `bp_session` Cookie**，FastAPI 没有 `/api/session` 路由。
- 反向代理路由顺序必须严格：
  ```
  /api/session*  → Next.js :3000
  /api/*         → FastAPI :8000
  /*             → Next.js :3000
  ```
  若所有 `/api/` 都转给 FastAPI，登录返回 404。
- 前端 `/api/*` 经 `web/next.config.mjs` rewrites 代理到 `BP_API_BASE`（默认 `http://localhost:8000`）。

## 前端（`web/`）

- Next.js 16 App Router + React 19 + TanStack Query + Tailwind v4 + Radix UI + ECharts + KaTeX。
- `web/lib/api.ts` 是类型化 API 客户端，**也是方法/基准/OTC 产品的常量源**，改动需与后端注册表同步（`METHOD_OPTIONS`、`BENCHMARK_OPTIONS`、`OTC_PRODUCTS`、`OTC_ENGINES` 等）。
- `web/lib/auth.tsx`（AuthProvider）、`web/lib/session-server.ts`（Cookie 读写）、`web/components/`（Navbar、RiskMatrixSection、MiniTradingCalendar 等）、`web/components/ui/`（shadcn 风格基础组件）。
- 主要路由：`/dashboard`（回测）、`/builder`（组合构建）、`/cffex`、`/otc-pricing` & `/otc-derivatives-pricing`、`/admin`、`/methodology`、`/docs`。

## 数据源与 ingest（`bp_ingest/`）

- `sources.py` 是 akshare 适配器注册表，每个 source 归一化到标准列 schema（`trade_date, open, high, low, close, volume, amount, turnover_rate, pct_change`，close 必须存在）。
- `fetch_with_fallback` 在东财(em)连接级错误时降级到 sina/tx；`_is_conn_error` 判定反爬掐断。`prewarm_em_code_maps` 预热 secid 解析映射。
- 资产池以东方财富为主（`cn_index_em`/`etf_em` 等），新浪/腾讯作降级；CFFEX 走 `get_futures_daily`。资产配置存 `bp_index_config`，软删除(`is_deleted`)。
- `http_session.py` 用 curl-cffi 硬化指纹绕反爬；`BP_EM_COOKIE`/`BP_SINA_COOKIE` 可选注入。
- `scripts/`（`check_cookies.py`、`validate_candidates.py`、`gen_seed_sql.py`）是资产池维护脚本，不参与 API 运行；`candidates.json`/`validated_candidates.json` 本地维护、不入 git。

## 数据库迁移纪律

- `ddl/schema.sql` 是**合并后基线**（= 旧编号迁移 01-32），全新环境只执行它。
- 已部署环境升级时，只执行尚未应用的新编号迁移（`NN_description.sql`）；不要重跑历史迁移，不要改已应用脚本。`deploy/deploy.sh` **不**执行迁移。
- 主要表：行情(`bp_index_quote_daily`/`bp_quote_clean`)、组合(`bp_portfolio`/`bp_portfolio_asset`/`bp_backtest_*`)、任务(`bp_task`)、资产状态(`bp_asset_data_status`)、CFFEX(`bp_cffex_contract_daily`/`bp_cffex_premium_daily`)、交易日历(`bp_trading_calendar`)、OTC(`bp_otc_deal`/`bp_otc_deal_price_history`)、鉴权(`bp_admin_user`/`bp_user`)。`bp_index_quote_daily` 是 TimescaleDB hypertable。
- demo 组合由 schema.sql 末尾 seed；`/api/portfolios/demo` 公开可读。

## 环境与运行模式

- `.env` 不入 git（`.env.example` 是模板）。必填：`PGPASSWORD`、`BP_JWT_SECRET`、`BP_ADMIN_INITIAL_PASSWORD`（首次创建管理员后可移除）。
- `BP_TASK_MODE`：`celery`(生产，默认) / `inline`(本地，无 Redis 降级)。
- 弱机降并发：`BP_CELERY_CONCURRENCY=1`、`BP_BACKTEST_METHOD_WORKERS=1`。
- 部署：PM2 五进程（`bp-api`/`bp-web`/`bp-ingest`/`bp-worker`/`bp-beat`），配置见 `deploy/ecosystem.config.cjs`；运维速查 `deploy/OPS.md`；部署说明 `docs/deployment.md`。

## 本地参考目录（gitignored，非生产代码）

`vendor/`、`autocallables-pricing-master/`、`Balanced Portfolio Prototype Design Figma/`、`.claude/`、`风险平价理论资料/` 是本地参考/原型，不参与构建，勿提交。

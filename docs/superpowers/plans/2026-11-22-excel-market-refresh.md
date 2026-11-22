# Excel 行情自动刷新（/api/v1 全量数据 + 全量 A股/港股/ETF/基金 ETL）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 本计划由单个 agent 顺序执行（无 subagent 工具）。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 让 `C:\Users\Xingyu Liu\OneDrive\Investment.xlsx` 打开即自动刷新（Power Query + XLOOKUP），现价取自有库 **已落库确认的收盘价（不复权 bfq）** 并显示数据日期；同时一次性补齐全量 A股/港股/ETF/基金 日频 ETL 与 `/api/v1` 只读接口。

**Architecture:** 服务器（81.71.158.239, xushilu.com）PostgreSQL 落库 → FastAPI `/api/v1/market/{last,history}`、`/api/v1/market/fx`、`/api/v1/fund/nav` → Excel Power Query 取数落隐藏表 `BP_Quotes`/`BP_FX` → `持仓!G` 与 `Accounts!J` 用 XLOOKUP。**不使用**腾讯实时价兜底（口径一致：只读库内确认收盘价）；Excel 无法取数时保留上次数据并显示日期。

**Tech Stack:** Python 3.13 + psycopg3 + requests/akshare（服务端）；FastAPI + pytest；Excel Power Query (M) + XLOOKUP（桌面版 16.0.20527）；git（GitHub hxlog/balanced-portfolio）。

**Spec:** 用户 Q1–Q9 决策（本会话）：PQ；DB-only bfq；先 A（持仓+汇率）后 B（WatchList/国债/估值）；C 二期；全量 ETL 一次做完；token 放隐藏配置单元格；授权提交/部署/cron；仅 Windows 桌面 Excel；失败保留旧值+显示日期；备份后改工作簿。

## Global Constraints
- 不复权（bfq）为现价口径；非 CNY 资产在 Excel 直接使用原币价（HKD），汇率单独取。
- 接口只读、不重算；统一信封 `{data, meta, error}`；token scope 复用 `quotes`。
- 不改 `/api/v1/market/daily`（bp_quote_clean，人民币折算口径）语义。
- 迁移文件 `ddl/NN_desc.sql` 只追加，不改历史；`schema.sql` 不重写。
- 生产增量 cron 必须在 A股 23:35 / 港股 16:15 收盘确认后运行。

## Review Focus
1. Excel 现价必须与「库内 bfq 收盘」逐条相等（交叉校验 10/10），不能混入盘中价。
2. 刷新失败时 Excel 必须保留上次数据并可见数据日期，不能清空或报 #N/A 传播到盈亏列。
3. 港股/ETF 的 bfq 与 hfq 不可混用；ETF hfq 为「单位累计净值」口径需在文档标注。
4. token 不得进入 git / 聊天记录外的持久文件；工作簿内放隐藏配置表。
5. 大表查询必须走索引（symbol+adjust+trade_date），禁止全表扫描拖慢生产。

---

### Task 1: DDL 迁移（ETF 行情 + ETF 主数据 + SGDCNY 汇率对）
**Files:** Create `ddl/73_etf_quotes.sql`, `ddl/74_sgd_fx.sql`；Test: `scripts/test_migrations.py` 既有机制。
- [ ] 73: `bp_etf_master(etf_code PK, name, market, category, source, updated_at)`；`bp_etf_quote_daily(etf_code, trade_date, source, adjust, open,high,low,close,volume,amount,pct_change,captured_at, PK(etf_code,trade_date,source,adjust))` + 2 索引。
- [ ] 74: `bp_index_config` 插入 SGDCNY/fx_sina（is_selectable=false, is_deleted=0, category=fx, currency=CNY, adjust=bfq）。
- [ ] 本地与生产各执行一次（幂等）。

### Task 2: `/api/v1/market/last` 改为 DB-only + ETF/FX 名称
**Files:** Modify `bp_api/market_last.py`；Test: `bp_api/tests/test_market_api.py`
- [ ] `_normalize` 支持 6 位 A股/ETF、5 位港股、指数；新增 `live` 参数（默认 0，保留腾讯兜底代码但默认关闭）。
- [ ] 读取优先级：`bp_stock_quote_daily` → `bp_etf_quote_daily` → `bp_index_quote_daily`（只读，不写库）。
- [ ] 返回 `code,market,currency,kind,name,date,close,prev_close,pct,adjust,source,status`；`status` 仅 ok/unknown；`meta.as_of/latest_trade_date/unknown`。
- [ ] 测试：normalize 矩阵、已知/未知代码、信封、CSV。

### Task 3: 新端点 `market/history`、`market/fx`、`fund/nav`
**Files:** Create `bp_api/market_extra.py`；Modify `bp_api/main.py`；Test 同上文件。
- [ ] `GET /api/v1/market/history?codes=&start=&end=&adjust=bfq&limit=&format=` 读 stock/etf/index 原始表（原币、不复权默认），返回 OHLCV+amount+pct_change+source+adjust。
- [ ] `GET /api/v1/market/fx?pairs=USD/CNY,HKD/CNY,USD/HKD,USD/SGD` 读 `bp_index_quote_daily` 的 fx_sina 人民币腿，交叉汇率用 `A/CNY ÷ B/CNY` 计算；返回 pair,date,price,source。
- [ ] `GET /api/v1/fund/nav?codes=&start=&end=&latest=&format=` 读 `bp_fund_nav_daily`（OTC 基金净资产口径）。
- [ ] 注册路由并补 `docs/API.md`。

### Task 4: 港股 ETL 补全与日更
**Files:** Modify `scripts/hk_stock_quotes.py`；cron。
- [ ] 回填默认只补近 `--years 6`（floor=end-6y），避免 1986 起翻页触发 WAF；保留 `--full`。
- [ ] 全局限速（线程间最小间隔 ~0.06s）+ 3 次指数退避重试；失败写 `logs/hk-failures.txt`。
- [ ] 断点：已有区间跳过；`--force` 全量重拉。
- [ ] 日更 16:20 后检查 `parts[30]` 日期 == today 才写；周更三口径近 40 天。

### Task 5: `/api/v1` ETF 全量 ETL
**Files:** Create `scripts/etf_quotes.py`。
- [ ] 列表：`ak.fund_etf_category_sina("ETF基金"|"LOF基金"|"封闭式基金")` → `bp_etf_master`（category 区分 etf/lof/closed，market 由 sh/sz 前缀）。
- [ ] 历史：腾讯 fqkline `sh510300,day,,end,800,{""|qfq|hfq}` 分页 6 年 → `bp_etf_quote_daily`（source=tencent_etf_kline）。
- [ ] 日更：腾讯 qt 批量 60 只/请求，写当日 bfq（source=tencent_etf_qt，16:20 后）。
- [ ] 周更：近 40 天三口径补齐。

### Task 6: 基金净值全量日更修复
**Files:** Modify `scripts/incremental_fund_nav.py`。
- [ ] 日更：`fund.eastmoney.com/data/rankhandler.aspx`（dt=kf&ft=all，42 页/日期）逐交易日补最近 N 天 → `bp_fund_nav_daily`（nav/acc_nav）。
- [ ] 未覆盖基金（ETF/LOF/封闭）：按 `--rotate 1500` 每晚轮转 `pingzhongdata` 补缺。
- [ ] 所有请求带 Referer + 重试。

### Task 7: 覆盖率快照 + crontab + 文档
**Files:** Modify `scripts/refresh_asset_coverage.py`, `docs/API.md`, `docs/data/asset-pool-etl.md`.
- [ ] coverage 增加 kind=etf（含 adjust）与 hk 股票显式统计。
- [ ] crontab：港股日更 23:40、港股周更周日 02:40、ETF 日更 23:45、ETF 周更周日 02:50、基金净值 22:30、coverage 23:55。
- [ ] 文档补新端点、DB-only 口径、ETF hfq 口径说明。

### Task 8: 测试 / 提交 / 部署
- [ ] `python -m pytest bp_api/tests -q` 全绿；`python -m bp_ingest --help` 冒烟。
- [ ] git commit（中文短句）+ push origin；生产机 `git reset --hard origin/main`（先备份未跟踪文件）→ `pm2 restart bp-api`。
- [ ] 生产执行迁移 73/74；启动回填后台任务并跟踪日志。

### Task 9: Excel 工作簿改造
**Files:** `C:\Users\Xingyu Liu\OneDrive\Investment.xlsx`（先备份 `Investment.backup-20261122.xlsx`）。
- [ ] 隐藏表 `BP_Config`（BpToken、BaseUrl）；`BP_Quotes`、`BP_FX` 隐藏表（PQ 输出）。
- [ ] PQ 查询 `bp_market_last`（读 持仓[代码] → codes；Web.Contents 带 Bearer）与 `bp_fx`（4 个货币对）。
- [ ] `持仓!G` = XLOOKUP(代码 → BP_Quotes[close])；新增 `行情日期` 列 = XLOOKUP(date)；条件格式标陈旧。
- [ ] `Accounts!Forex`：I 列改文本对、J 列 = XLOOKUP(BP_FX)；修好 USD/HKD、USD/SGD、USD/CNY、HKD/CNY。
- [ ] 连接属性：打开刷新 + 每 60 分钟；失败保留旧值。

### Task 10: 端到端验证
- [ ] 刷新后 13 行现价与 DB bfq 收盘逐条一致（10 个唯一代码），行情日期=2026-11-20 或最新交易日。
- [ ] 断网/无 token 场景验证保留旧值 + 日期可见。
- [ ] 输出验证证据（表格）与部署/使用说明。

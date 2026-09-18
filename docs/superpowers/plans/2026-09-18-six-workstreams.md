# 六项跨栈改造 实施计划（持仓变动 / 汇率折算 / 资产治理 / umami 回放 / 推荐ETF / 调仓计算器）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 逐任务实现。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 修复「调仓变动」清仓行缺失、接入新浪汇率并落库折算 CNY、资产管理滞后语义与批量操作、恢复 umami 会话回放、重建 /builder 推荐 ETF 四类 17 只、新增本地调仓计算器。

**Architecture:** 后端沿用 `bp_ingest` source adapter 注册表 + `bp_quote_clean` 清洗管线；汇率作为**独立 `fx` source**（不进 `bp_index_config` 可选池），在 `cleaning.py` 插入窗口按日折算非 CNY 资产收盘价到 CNY。前端改动集中在 `DashboardClient.tsx` / `admin/assets` / `BuilderClient.tsx` + 一个新组件 `RebalanceCalculatorDialog.tsx`。

**Tech Stack:** FastAPI + psycopg3 + PostgreSQL18/TimescaleDB + akshare；Next.js 16 + React 19 + Tailwind v4 + Radix + ECharts。

## Global Constraints

- **不 commit**：git 由用户自己操作；每任务以「测试/构建通过」为完成检查点。
- 改动直接落主 checkout `D:\balanced-portfolio`（无 worktree）。
- DB：`PGHOST=81.71.158.239 PGPORT=5432 PGDATABASE=postgres PGUSER=postgres`，密码见 `.env`（`Lxyblbq2233@`，`@` 属于密码本身）。**含中文的 SQL 必须写 utf-8 文件后 `psql -f`**。
- DDL 纪律：新迁移编号从 **43** 起；同步合并进 `ddl/schema.sql` 基线；不重跑历史迁移。
- 颜色：sky 主色、`text-up`/`text-down` 仅用于方向性涨跌、滞后用 warning/amber、四象限色保留；图表色经 `web/lib/chart-theme.ts`。
- 禁止 `window.alert/confirm`；确认用 Radix AlertDialog；反馈用 sonner toast。
- 每任务收尾必跑：`python -m pytest bp_api/tests -q` + `cd web && npm run build`。
- Python venv：`.venv\Scripts\python.exe`。

---

## Phase 0：事实固化（已完成侦察）

| 事实 | 证据 |
| --- | --- |
| 清仓行丢失根因 | `DashboardClient.tsx:1238-1240` 对 `rb.target_weights` 做 `w >= ZERO_EPS` 过滤 + 按目标权重降序 → 本期权重为 0 的标的被整体剔除 |
| 持仓卡同类问题 | 同文件 `483-493` `holdingsAtOptimal` 亦有 ZERO_EPS 过滤（该处是「当前持仓」语义，正确；计算器不得复用） |
| 汇率仅新浪可用 | 新浪 vs 中行中间价：USD 日变动相关 0.149、HKD 0.109、EUR 0.053；±2 日移位检验排除错位 → **不同口径，不可聚合** |
| umami 回放为空 | `layout.tsx` 只注入了 `script.js`，v3.3.1 的回放是**独立 bundle** `recorder.js`，从未加载 |
| 删后回顶根因 | `admin/assets/page.tsx:61-70` `load()` 无条件 `setLoading(true)`；`507-511` 据此卸载 `<Table>` 换成「加载中」→ 容器塌陷，滚动位置复位 |
| 滞后口径 | 现有 `is_stale` = `last_clean_date < MAX(last_clean_date)`，只差 1 个交易日即判滞后，且徽章文案为「停更」 |
| ETF 错映射 | 交叉校验东财/新浪实盘名称 vs DB `name`，已确认 9 只（如 `159870` 实为「化工ETF鹏华」却标「标普500ETF（易方达）」）；`161129/161226/161725/164824/501031/511010` 等在场外/LOF 或无 EM 行情 |

---

## Phase A：后端与数据层

### Task 1: DDL 43 — `fx_rate` 审计列 + 来源 seed + 资产纠正

**Files:** Create `ddl/43_fx_and_asset_fix.sql`；Modify `ddl/schema.sql`

- [ ] `bp_quote_clean` 增 `fx_rate NUMERIC(18,8)`（折算所用汇率；CNY 资产为 1，无汇率为 NULL），加注释说明「已折算到 CNY 的收盘价 + 所用汇率」
- [ ] `bp_data_source` 增 `fx` 源行（`asset_class='fx'`, `is_addable=FALSE`, `is_selectable=FALSE`），使汇率可被 ingest 拉取但不进 /builder 资产池
- [ ] `bp_index_config` 增 3 行汇率标的（`USDCNY@fx_sina`, `HKDCNY@fx_sina`, `JPYCNY@fx_sina`，`is_selectable=FALSE`, `is_deleted=0`）
- [ ] 纠正错误映射：对已确认错映射的 ETF **原地改名**（`UPDATE bp_index_config SET name=... WHERE symbol=... AND source='etf_em'`），不改资产 key（`{symbol}@{source}` 全栈通用，改名不失效）
- [ ] 同步合并进 `ddl/schema.sql`

### Task 2: FX 数据接入（`bp_ingest`）

**Files:** Modify `bp_ingest/sources.py`、`bp_ingest/db.py`

- [ ] 新增 `fx_sina` adapter：akshare `currency_boc_sina` 之外的**新浪外汇即期**口径；归一化 `trade_date/open/high/low/close`
- [ ] `AGGREGATE_CHAINS` **不注册**该源（用户已确认：新浪口径不可与中行聚合）
- [ ] `fetch_active_configs`（`bp_ingest/db.py:70-104`）：空 `symbols`（调度器路径）时当前过滤 `is_selectable=TRUE` → 改为 `is_selectable = TRUE OR source = 'fx_sina'`，让汇率可被定时拉取但不进可选池
- [ ] `python -m bp_ingest run --symbols USDCNY HKDCNY JPYCNY` 验证落库

### Task 3: 清洗期 CNY 折算（`bp_api/quant/cleaning.py`）

- [ ] `clean_one` 插入窗口：读该资产的 `currency`；非 CNY 时按日取对应汇率序列（USD→`USDCNY`，HKD→`HKDCNY`，JPY→`JPYCNY`），把 OHLC **同时**折算（保持收益/协方差不失真），`fx_rate` 落列
- [ ] 无汇率日按用户决策**不处理**（该日不产出清洗行，交由既有尾部缺口报错/前导空白机制）
- [ ] DXY / QDII 这类「本身以美元计价的境内挂牌品」排除在外：QDII ETF 以 CNY 挂牌 → `currency='CNY'` 不折算；`dxy_em` 保留 USD 语义但**不参与回测**（`is_selectable` 现状已限制）
- [ ] 交叉汇率用美元三角：非 USD/HKD/JPY 的币种走 `USDCNY / USDFX` 推导
- [ ] `python -m bp_ingest clean` 全量重建，抽样断言：某 QDII/QDII 类资产折算前后净值序列在汇率平稳段差异 < 汇率波动幅度

### Task 4: 后端滞后语义（≥2 交易日）

**Files:** Modify `bp_api/repositories.py`（`_stale_frontier` 240-255 / `list_assets` 256-289 / `list_admin_assets` 1478-1524）

- [ ] 新增 `_lag_trading_days(conn, frontier, last_clean_date)`：用 `bp_trading_calendar`(market='CN') 数 frontier 与 `last_clean_date` 之间的交易日数
- [ ] `list_assets` / `list_admin_assets` 改为发出 `lag_trading_days: int | null` + `is_lagging: bool`（`is_lagging = lag_trading_days >= 2`），**保留 `is_stale` 字段**（1 日差）以兼容既有 /builder 逻辑
- [ ] 同步 `web/lib/api.ts` 类型
- [ ] 加 pytest：构造 0/1/2/3 交易日差断言 `is_lagging` 边界

---

## Phase B：前端

### Task 5: W2 资产管理 UX

**Files:** Modify `web/app/admin/assets/page.tsx`、`web/app/admin/users/page.tsx`

- [ ] `load()` 拆 `loading`（首屏）与 `refreshing`（后续）：`refreshing` 时**不卸载** `<Table>`，只在表头旁显示细进度条/旋转图标 → 删除/保存后滚动位置保持
- [ ] 徽章 `停更` → `滞后 N 个交易日`（amber/warning），仅 `is_lagging` 时显示
- [ ] 筛选：`sourceFilter` 现按 `a.vendor` 过滤但行内渲染 `logical_source` → 改为按 `logical_source` 过滤
- [ ] 新增「仅显示滞后」快捷筛选 + `is_lagging` 排序
- [ ] 多选：表头全选 Checkbox + 行 Checkbox；批量操作「批量删除」「批量启用/停用」，走 AlertDialog 二次确认并展示将影响的**组合数量**

### Task 6: W4 持仓变动完整性

**Files:** Modify `web/app/dashboard/DashboardClient.tsx:1212-1273`

- [ ] 数据源改为 `union(target_weights, prev_weights, delta)`，**不**按 `w >= ZERO_EPS` 过滤
- [ ] 排序改为 `|Δ|` 降序；`Δ` 缺失（新入池无上期）视为建仓，排在末位并标「建仓」
- [ ] 两期皆为 0 的行**不显示**（用户确认）
- [ ] 视觉：清仓行「本期权重」显示 0.0%，`Δ` 为负红；建仓行「上期权重」显示 `—`
- [ ] 卡片右上角加入口按钮打开 Task 7 计算器（传 `rb` + `nameMap`）

### Task 7: W5 调仓计算器（本地计算，零存储）

**Files:** Create `web/components/RebalanceCalculatorDialog.tsx`；Modify `DashboardClient.tsx`

- [ ] 5 列：标的 / 当天最优化权重 / 用户输入当前持仓金额 / 自动换算权重 / 差值买卖金额±
- [ ] 换算权重 = 金额 ÷ 总金额；差值 = (目标权重 − 换算权重) × 总金额
- [ ] 自动输出**总调仓金额**（Σ|差值|）
- [ ] 金额显示：整数元千分位（用户确认）
- [ ] 隐私声明：本地计算、不上传不存储
- [ ] 预填：金额列留空，用户可一键「按当前权重填充」做示例

### Task 8: W3 /builder 推荐 ETF 与滞后沉底

**Files:** Modify `web/app/builder/BuilderClient.tsx:62-66`、`:786-794`

- [ ] `RECOMMENDED_GROUPS` 改为 4 组 17 只（国内宽基 4 / 红利类 5 / 固收类 4 / 海外投资 4），每指数**恰好一只**场内 ETF，取成立最久 + 规模流动性尚可
- [ ] 修 `rank()` 死代码：`if (a.logical_source === "etf" && a.adjust === "hfq") return 0 + fx;` 令 `:790` 的 `is_stale` 分支不可达 → 改为**先判滞后再判复权**，滞后资产沉底
- [ ] 移除清单中不可用标的（无 EM 行情 / 长期滞后）仅从推荐移除，保持可选（用户确认）

### Task 9: W1 umami 回放（已完成，记录备查）

- [x] `layout.tsx` 注入第二个 `recorder.js` bundle；`.env` / `.env.example` / `ecosystem.config.cjs` / `README.md` / `deploy/OPS.md` 同步
- [x] 浏览器验证：`recorder.js 200` + `POST /api/record 200 ×2`

---

## Phase C：收口

### Task 10: schema 对齐 + 并发重算 + 全链路验证

- [ ] `ddl/schema.sql` 与生产库逐列 diff，确保基线可全新安装
- [ ] **并发**全量重算全部组合（`POST /api/admin/portfolios/recompute-all`）
- [ ] `python -m pytest bp_api/tests -q` 全绿
- [ ] `cd web && npm run build` 通过
- [ ] 浏览器端到端：/dashboard 调仓变动含清仓行 + 计算器、/admin/assets 删后不回顶 + 滞后徽章 + 批量、/builder 四类推荐 + 滞后沉底
- [ ] 产出受影响的组合清单（资产改名/折算会改动历史 NAV）

---

## 风险与回滚

- **折算改变历史净值**：所有含非 CNY 资产的组合 NAV 会变，属预期（这正是「科学纳入」的目的）。审计列 `fx_rate` 可回溯口径。
- **迁移回滚**：`fx_rate` 为可空列，回滚只需 `DROP COLUMN`；资产改名无副作用（key 未变）。
- **不 commit**：所有改动留在工作区，由用户决定提交时机。

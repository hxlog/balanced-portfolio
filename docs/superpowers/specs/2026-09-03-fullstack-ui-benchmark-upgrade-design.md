# 设计文档：全站 UI 现代化 + 基准扩展 + 编辑流程升级

日期：2026-09-03
状态：待用户审阅
范围：10 项需求 + 2 项新增任务（内部基准口径修复、死配置清理）+ 全站响应式审计

---

## 0. 决策记录（用户已确认）

| 编号 | 决策 |
|---|---|
| A1 | 「保存」全部持久化（含回测参数），不重算；以「参数已调整需重算」标记提醒 |
| A2 | diff 弹窗中资产构成用聚合表达（新增/移除/换象限） |
| A3 | 点「保存」或「保存并重算」均弹 diff 窗，列出全部变更字段（变更前→变更后） |
| B1 | 海外基准用**国内 QDII ETF 平替**（人民币计价可比）：标普500→513500（博时，2017-01-03 起）、纳斯达克100→513100（国泰，2017-01-03 起）、日经225→513520（华夏，2019-06-25 起，上市最晚无法更早） |
| B2 | 全量重跑所有组合（含 5 个 demo）；库内共 13 个组合，全部 done |
| B3 | 历史数据拉满（2017-01-01 起）——已查实三只 ETF 数据已是满历史（起点=上市日/2017-01-03），无需回补 |
| C1 | 「组合上限=无限」的落库语义由实现者按最佳实践定：本方案用 `portfolio_limit NULL = 无限` |
| C2 | 资产表按金融产品现代扁平 UI 最佳实践调整 |
| D1 | **绿涨红跌**（翻转现有 CSS token；图表常量已为此口径） |
| D2 | 维持系统字体栈，只统一字重/行距/数字等宽 |
| D3 | 全站 UI review：字体、行距、间距、布局；统一颜色方案 |
| E1 | Next16/React19 优化走保守口径（只动涉及路径） |
| E2 | 本地验证与重算，可直接改库 |
| ④ | 内部基准 legs[0] 口径问题**必须修**，作为独立任务，修后全量重算 |
| ⑤ | 死配置环境变量直接删除 |
| 追加 | 全站响应式（手机/平板/PC）必须完整可用、无畸变；用 Chrome 逐页审计 |

已核实的库内事实：
- 513500/513100/513520 均在 `bp_index_config`（etf_em、hfq、在售、今日已同步），`bp_quote_clean` 数据分别自 2017-01-03 / 2017-01-03 / 2019-06-25 至今。
- `标普500`/`纳斯达克`/`日经225`@global_index_em 自 2017 起有数据，但**弃用为基准**（改作普通持仓资产保留）。
- `bp_portfolio.params` JSONB 列存在但代码零引用 → 复用为回测参数快照列。
- 组合 13 个（5 demo），全量重算本地可行。
- 迁移最新编号 38，本次用 **39**。

---

## 1. 设计系统与全局 UI（WP1，对应第 8 条）

### 1.1 颜色方案（globals.css token 层）

主色 sky，扁平现代金融风格；浅色主色取深一档保证白字对比度，暗色取亮一档配深色字：

| Token | Light | Dark |
|---|---|---|
| primary | `#0284C7` (sky-600) | `#38BDF8` (sky-400) |
| primary-foreground | `#FFFFFF` | `#082F49` (sky-950 系) |
| ring | sky-500/50 | sky-400/50 |
| **up（涨/正收益）** | `#16A34A` (green-600) | `#4ADE80` (green-400) |
| **down（跌/负收益）** | `#DC2626` (red-600) | `#F87171` (red-400) |
| success | 同 up | 同 up |
| warning | `#D97706` (amber-600) | `#FBBF24` (amber-400) |
| destructive | 维持 `#E5484D` | 维持 |

新增 `success`/`warning` 语义色进 `@theme inline`，收编现有 21 处 amber-*、11 处 emerald-* 硬编码。

**up/down 语义净化（绿涨红跌翻转的连带整改）**：`text-up`/`text-down` 只允许用于「方向性涨跌」。以下非方向性误用一并整改：
- 四象限色调（`BuilderClient:27-30`、`DashboardClient:42`、`mdx.tsx:55-58`）：改为经济语义色——过热=warning(琥珀)、滞胀=destructive、复苏=success、衰退=weak。
- `OtcPricingClient:109` knocked_out 状态：`text-down` → `text-destructive`。
- `CffexClient:594-604` 基差/溢价着色：正基差（升水）保持「好」语义 → 用 success；负 → destructive；不再借 up/down。

### 1.2 排版与间距标准

- 根字号维持 16px；UI 主文本 `text-sm`(14px)，正文/文档 `text-base`，辅助说明 `text-xs`(12px)。
- 移除 `globals.css:131` 的 `button { font-size: var(--text-base) }` 基类污染（继承父级字号）。
- 行距：正文 1.6，紧凑控件 1.25，标题 1.2。
- 数字一律 `font-mono tabular-nums`。
- 间距栅格 4px：卡片内边距 `p-5`(移动)/`p-6`(桌面)，区块间 `space-y-6`，栅格 `gap-4/6`。
- 容器：`max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8`。
- 圆角：卡片 `rounded-xl`、控件 `rounded-md`、徽章/胶囊 `rounded-full`（维持现状，统一残留不一致处）。
- 阴影：维持低阴影 `shadow-sm`，hover 态 `shadow-md` 过渡。

### 1.3 图表主题收敛

新建 `web/lib/chart-theme.ts`：导出 `getChartTheme(isDark)` → `{ text, axisLine, splitLine, tooltipBg, tooltipBorder, cardBg, palette[], up, down }`。palette 以 sky 为首色的 8 色分类序列（明暗各一套）。重构 6 个消费方，消除 ~110 处硬编码 hex：
- `DashboardClient`（含 `UP_COLOR`/`DOWN_COLOR` 常量 → 主题 up/down）
- `CffexClient`（IF/IH/IC/IM 四色保留但入主题表）
- `CryptoClient`、`OtcPricingClient`、`RiskMatrixSection`（RdBu 发散色保留入表）、`ChartLightbox`、`HomeCryptoSection`（server 组件用 CSS 变量方案保留）。

### 1.4 组件原语补齐

- 新增 `sonner` toast（替代零散 banner/`window.confirm` 反馈）；`web/components/ui/alert-dialog.tsx`（替换 `window.confirm`：admin/users 删除、资产删除、全量重算确认）。
- 现有 16 原语样式随 token 自动更新，不重写。

### 1.5 响应式与逐页审计

- 每页在 **375 / 768 / 1440** 三档视口 × **明/暗**两主题用 chrome-devtools MCP 审计：截图 + 控制台错误 + 横向溢出检测（`scrollWidth > clientWidth`）+ 交互抽检。
- 已知整改点：builder 象限网格与 AssetPicker 内部栅格在窄弹窗/窄视口的坍缩、admin 两表的可滚动性、dashboard 双栏（TOC 在 <1024px 收起为顶部折叠或隐藏锚点条）、cffex/crypto/otc 表格窄屏滚动、首页卡片栅格。
- 审计产出问题清单逐项修复后复测，最终全绿。

### 1.6 设计文档

新增 `docs/design-system.md`：色板（含明暗）、字体排版、间距、组件用法、涨跌色规范、图表主题用法。作为后续维护依据。

---

## 2. Builder 页（WP2，对应第 1/2/3/5 条）

### 2.1 第 1 条：资产弹窗宽度

- `BuilderClient.tsx:694` 传参改 `sm:max-w-4xl`（tailwind-merge 在同 variant 下能正确覆盖基座 `sm:max-w-lg`）。
- 内部栅格 `md:grid-cols-[1fr_300px]` → 容器查询无关化：右栏收窄到 260px，过滤行 `flex-wrap` 兜底；列表行信息密度优化（徽章合并、等宽信息降级为 tooltip）。
- 弹窗高度 `max-h-[85vh]` + 列表区滚动。

### 2.2 第 2 条：文案

`BuilderClient.tsx:387` → 「选择默认的优化方法」。

### 2.3 第 3 条：偏离带取整

- 预填：`setBand(+((p.rebalance_band ?? 0.05) * 100).toFixed(2))`。
- 保存：`rebalance_band: Math.round(band * 100) / 10000`（4 位小数内无 epsilon）。
- 后端落库前同样 `round(x, 4)` 防御（update/create/meta 三处）。

### 2.4 第 5 条：编辑免重算 + 变更 diff 弹窗

**交互**：
- 底栏按钮：无变更→「保存」禁用（旁注「无待保存变更」）；有变更→「保存」+「保存并重算」并存。
- 任一按钮 → 打开 `ChangeDiffDialog`（编辑模式；新建模式保留现有 ConfirmRecomputeDialog）：
  - 表格三列：参数 / 变更前 / 变更后（只列有变化的字段）。
  - 字段中文映射：组合名称、组合描述、默认优化方法、对比基准、风险指标、回看窗口(天)、起始日期、单资产上限、再平衡偏离带、无风险利率、佣金费率、滑点、印花税（卖出）、资产构成。
  - 百分比统一格式：`0.05%`（×100 后最多 2 位小数去尾零）。
  - 资产构成聚合行：「新增：A、B；移除：C；调整：D（成长→红利）」。
  - 若仅元数据变更：弹窗只有「保存」；若含回测参数：「仅保存」+「保存并重算」双按钮，并注明「仅保存后回测结果不会更新，将标记为待重算」。
- 「仅保存」→ `PATCH /api/portfolios/{id}/meta`（扩展版，见 2.5）；成功后 toast 提示（含参数变更时追加「结果待重算」）→ 跳 dashboard。
- 「保存并重算」→ 现有 `PUT` + BacktestProgressDialog 流程不变。
- 409（回测进行中）→ toast 明确文案，不再只挂红条。

**后端**：
- `PATCH /api/portfolios/{id}/meta` 扩展为接受完整 `UpdatePortfolioIn`：
  - name/description 随时可改（含 running 时）；
  - 其余字段：与当前值有差异时更新定义行+资产替换，**不改 status、不派发回测**；若组合 running 且涉及回测字段 → **409**。
  - 走同一 `_validate_portfolio_payload` 校验；落库数值 `round(…, 4)`。
  - 清结果缓存（维持现行为）。
  - 返回 `{portfolio_id, params_stale}`。

### 2.5 stale 标记（参数已变更待重算）

- `bp_portfolio.params`（未用列）**改名 `last_run_params`**：run_and_save 成功时写入规范化快照：
  ```
  {method, ratio, lookback_days, start_date, benchmark_key, max_weight,
   rebalance_band, risk_free_rate, fee_rate, slippage_rate, stamp_duty_rate,
   assets: [[symbol, source, quadrant], …] 排序}
  ```
  （浮点先 round(4) 再入快照。）
- `params_stale = (canonical(current) != last_run_params)`，在 `get_portfolio_dict` / `list_portfolios` 输出。
- 迁移 39 内回填：所有 status='done' 组合用当前列+资产生成快照（历史上 PUT 必重算，当前参数=最后一次回测参数，回填无偏差）。
- 前端：`PortfolioInfo.params_stale`；dashboard 顶部条幅「参数已调整，结果尚未重算 → 去重算」（链接 `/builder?id=…`）；builder 预填时若 stale 显示同款提示。

---

## 3. 基准扩展：QDII ETF 化（WP3，对应第 4 条）

### 3.1 注册表

后端 `repositories.py:BENCHMARKS` 新增（顺序放在 bond6040 之后）：

```python
"sp500_etf": {"name": "标普500ETF", "kind": "total_return",
    "legs": [(1.0, "513500", "etf_em")],
    "note": "人民币计价 QDII（博时513500），后复权含分红拆分，可与组合人民币收益直接比较；含汇率波动与折溢价噪声。"},
"ndx100_etf": {"name": "纳斯达克100ETF", "kind": "total_return",
    "legs": [(1.0, "513100", "etf_em")],
    "note": "人民币计价 QDII（国泰513100，跟踪纳斯达克100），后复权；含汇率波动与折溢价噪声。"},
"n225_etf": {"name": "日经225ETF", "kind": "total_return",
    "legs": [(1.0, "513520", "etf_em")],
    "note": "人民币计价 QDII（华夏513520），后复权；2019-06-25 上市，早于该日的回测不显示此基准；含汇率波动与折溢价噪声。"},
```

前端 `web/lib/api.ts`：`BENCHMARK_OPTIONS` 同步三项；`BENCHMARK_COMPOSITION` 增加对应条目（单腿 100% ETF）。dashboard 基准下拉是服务端驱动（`data.benchmarks`），自动出现；构成说明框依赖 COMPOSITION 表，需同步。

### 3.2 数据

三只 ETF 清洗数据已是满历史（起点=上市日），每日增量已在跑，**无需回补**。验收：本地核对三序列无尾部缺口。

### 3.3 重算后效果

`run_and_save` 本就为全部注册基准预计算净值（`bp_backtest_benchmark`）与归因（method×benchmark），重跑即自动补齐新基准。回测起点早于 2017-01-03（或日经 2019-06-25）的组合自动不出现对应基准（现有空序列跳过机制）。

---

## 4. 内部基准口径修复（WP4，用户追加任务④）

- 现状：`_compute`（repositories.py:614-616）回测内部基准只取 `legs[0]` → bond6040 组合的落库 `benchmark_nav`/超额/IR 实际对标 10Y 国债单腿，与展示用的 60/40 合成不一致（dashboard 的 IR 已即时重算掩盖了一部分）。
- 修复：新增 `_load_benchmark_series(conn, bkey)`：按注册表全部 legs 构建**按日再平衡合成收益序列**（与 `_compute_benchmark_navs` 同算法：`Σ w·pct_change` → cumprod，取各腿交集），作为 `run_backtest(benchmark=…)` 入参。单腿基准结果不变；新增三只 ETF 基准不受影响；**bond6040 组合的超额/IR/对比曲线将变化 → 依赖 WP5 全量重算生效**。
- 修复后 `get_result` 展示口径与落库口径完全一致。

---

## 5. 全量重算（WP5，对应第 4 条「重跑」+ 任务④联动）

- 新端点 `POST /api/admin/portfolios/recompute-all`（require_super_admin）：
  - 遍历所有组合（含 demo，跳过 running 与无资产者），逐个走现有 `_enqueue_backtest`（写 bp_task + 置 running + commit 后派发）。
  - 返回 `{enqueued: n}`。Celery 模式排队消化；本地 inline 模式顺序执行（13 个组合预计 30~90 分钟，用户已同意本地执行）。
- 前端：`/admin/assets` 头部超管按钮区新增「强制重算全部组合」（AlertDialog 确认，文案含数量与预估时长），成功后 toast + 任务可在组合状态中观察。
- 执行顺序依赖：必须在 WP3+WP4 代码上线（本地 uvicorn 加载新代码）之后执行一次。

---

## 6. /admin/users 创建表单（WP6，对应第 6 条）

- 后端：
  - `CreateUserIn` += `portfolio_limit: Optional[int] = 3`（**None = 无限**）、`can_manage_assets: bool = False`；`auth.create_user` 透传（INSERT 显式列）。
  - 语义变更：`bp_user.portfolio_limit` `DROP NOT NULL`（迁移 39）；`get_user_portfolio_limit`：role=admin → None；否则 `portfolio_limit`（None=无限，不再是「NULL→默认3」）。存量行均有显式值，不受影响。
  - OTC 限额同读该函数，自动对齐。
- 前端创建表单（「添加用户」卡片）：
  - 邮箱、初始密码（保留）；
  - 新增「资产编辑权限」Switch（默认关，说明文案：可进 /admin/assets 新增/更新/测试/拉取增量）；
  - 新增「组合上限」：数字输入（默认 3，最小 0）+「无限」复选框（勾选后禁用输入框）。
- 列表行控件同步支持无限：显示「不限」，点「不限/自定义」可切换；保留现有内联保存交互。

---

## 7. /admin/assets 表布局（WP7，对应第 7 条）

目标：1440px 常见宽度内**无横向滚动即可看到全部操作**，1280px 内同样成立；更窄则保留横向滚动兜底。

- 列宽重整：名称列 `min-w-[120px]` 截断+tooltip；Symbol/Source/复权 合并紧凑展示（等宽小字）；状态/行数/新鲜度列压缩（`text-xs tabular-nums`）；「清洗截至」与「最近拉取」二选一展示（保留新鲜度，截至日进 tooltip）。
- 「最近错误」：默认只显示状态图标（✓/⚠），错误全文进 tooltip/Popover，释放 ~360px。
- 操作列：`测试`/`拉取增量`/`删除` 改紧凑图标+文字按钮（`size=sm`，`gap-1`），`whitespace-nowrap`，右对齐。
- 表头三按钮区保持不变；整体 `min-w` 下调到 ~1000px 并按上述分配。

---

## 8. Dashboard（WP8，对应第 9/10 条）

### 8.1 第 9 条：TOC

- `DashboardToc.tsx:56` 按钮加 `cursor-pointer`（Tailwind v4 preflight 不再默认提供）。
- 字号改 `text-[13px]`（与「本页目录」标题 `text-xs` 层级匹配），行距 `leading-6`，去掉基类污染后不再被 16px 覆盖。
- active 高亮改用 `text-primary` + 左侧 2px 指示条，悬停 `bg-accent/60`。
- `globals.css` 基类 `button` 字号规则删除（根治同类问题，如方法切换 pills）。

### 8.2 第 10 条：默认组合

`resolveDefaultPortfolioId`（web/lib/cached-data.ts:74-88）：
- 解码 session JWT（payload 含 `role`；新增 `web/lib/session-server.ts` 的 `readSessionClaims()` 助手，base64url 解码，不验签——验签在 FastAPI 侧已完成）。
- `role === 'admin'`（即超管）→ 选第一个 `is_demo`（按 display_order）。
- 普通登录用户 → 先选自己第一个非 demo 组合；没有 → 第一个 demo。
- 匿名 → demo（维持现状）。

### 8.3 stale 条幅

`params_stale=true` 时，顶部信息卡下方显示琥珀条幅：「组合参数已调整，回测结果尚未重新计算」+「去重算」按钮（→ `/builder?id=`，由用户在 builder 触发重算；不在 dashboard 直接重算，保持单一入口）。

---

## 9. 清理（WP9，用户追加⑤）

- 删除 `settings.py` 的 `BP_RISK_FREE` / `BP_DEFAULT_LOOKBACK` / `BP_REBALANCE_BAND`（死配置，无消费方）及 `.env.example` 对应条目。
- `CLAUDE.md` 同步：组合级参数是唯一口径，无环境变量兜底；顺带修正 `main.py:331` 过时文案「04_seed_demo_portfolio.sql」→ schema.sql seed。
- `require_admin = require_user` 别名保留（不扩大重构面），仅在代码注释标注遗留。

---

## 10. 数据库迁移（39）

```sql
-- 39_benchmarks_edit_flow.sql
ALTER TABLE bp_user ALTER COLUMN portfolio_limit DROP NOT NULL;

ALTER TABLE bp_portfolio RENAME COLUMN params TO last_run_params;

-- 回填：done 组合的当前参数即最后一次回测参数
UPDATE bp_portfolio p SET last_run_params = jsonb_build_object(
  'method', p.method, 'ratio', p.ratio, 'lookback_days', p.lookback_days,
  'start_date', to_jsonb(p.start_date), 'benchmark_key', p.benchmark_key,
  'max_weight', round(p.max_weight::numeric, 4),
  'rebalance_band', round(p.rebalance_band::numeric, 4),
  'risk_free_rate', round(p.risk_free_rate::numeric, 4),
  'fee_rate', round(p.fee_rate::numeric, 4),
  'slippage_rate', round(p.slippage_rate::numeric, 4),
  'stamp_duty_rate', round(p.stamp_duty_rate::numeric, 4),
  'assets', (SELECT coalesce(jsonb_agg(jsonb_build_array(a.symbol, a.source, a.quadrant) ORDER BY a.symbol, a.source, a.quadrant), '[]'::jsonb)
             FROM bp_portfolio_asset a WHERE a.portfolio_id = p.portfolio_id)
) WHERE p.status = 'done';
```

执行纪律：生产只跑 39；同时把 34-39 的净变化合并进 `ddl/schema.sql` 基线（修正当前基线落后于 36/37 的问题，供全新环境一次性建库）。本地由我直接对 Tailscale 库执行。

---

## 11. API 契约变更汇总

| 端点 | 变更 |
|---|---|
| `PATCH /api/portfolios/{id}/meta` | 接受完整 payload；非元数据字段在 running 时 409；返回加 `params_stale` |
| `GET /api/portfolios` / 组合详情 | 返回加 `params_stale` |
| `POST /api/admin/users` | body 加 `portfolio_limit`（null=无限）/`can_manage_assets` |
| `POST /api/admin/portfolios/recompute-all` | 新增（超管） |
| 其余（PUT/POST/demo/result） | 不变（PUT 仍全量重算） |

前端 `web/lib/api.ts`：`AdminUser`、`PortfolioInfo` 类型、`updatePortfolioMeta` 签名、新函数 `recomputeAllPortfolios`、`BENCHMARK_OPTIONS/COMPOSITION` 同步。

---

## 12. 测试策略

- **后端 pytest**（合成夹具）：
  - 基准注册表含 8 项、`_load_benchmark_series` 多腿合成数值正确（60/40 合成 ≠ 单腿）；
  - PATCH meta 全字段更新不触发回测、running+回测字段→409、running+仅 name→200；
  - params_stale 判定与快照回填；
  - portfolio_limit NULL=无限（创建/复制/OTC 三处限额路径）；
  - recompute-all 权限与入队数；
  - 无未来函数测试维持通过。
- **前端**：`npm run build` + `typecheck`（CI 同口径）。
- **E2E（本地 + chrome-devtools MCP）**：
  - 三视口×明暗逐页审计（11 个路由），溢出/控制台/交互检查；
  - builder 全流程：新建→编辑（仅改名保存 / 改印花税仅保存 / 保存并重算）观察 diff 弹窗与 stale 标记；
  - dashboard：新基准下拉、基准切换、默认组合（管理员/普通用户/匿名三身份）；
  - admin：建用户（无限上限）、资产表无滚动可见操作。
- **数据验收**：全量重算后抽查 2 个组合 + 1 个 demo：8 基准的 `bp_backtest_benchmark` 行数、归因行数、60/40 合成曲线与旧单腿曲线差异符合预期。

---

## 13. 执行阶段

1. **P0 基线**：本地 `pytest` + `npm run build` 全绿，记录起点。
2. **P1 后端**：迁移 39 → 基准注册表 → legs 修复 → meta 扩展 + stale → 限额语义 → recompute-all → 清理死配置 → pytest 全绿。
3. **P2 前端功能**：builder（1/2/3/5 条）→ dashboard（9/10 条 + stale 条幅）→ admin（6/7 条）→ api.ts 同步 → build/typecheck 全绿。
4. **P3 设计系统**：token 重构（sky 主色/涨跌翻转/语义色）→ chart-theme 收敛 → 排版间距全站落地 → toast/alert-dialog → 原语与页面细节统一。
5. **P4 数据与重算**：核对三只 ETF 序列完整性 → 本地起新版后端 → recompute-all 全量重跑 → 数据抽查。
6. **P5 审计闭环**：chrome-devtools 三视口×明暗逐页审计 → 修复 → 复测 → `docs/design-system.md` + CLAUDE.md 更新 → 最终全量测试。

依赖关系：P4 依赖 P1 完成；P3 的涨跌翻转与 P2 的组件改动有文件交叠，按序串行避免冲突。全程不提交 git（用户自行操作）。

---

## 14. 风险与注意事项

- **待用户确认：「日经200」**：原需求写「日经200」，日本主流指数为日经225（国内 QDII 也均跟踪日经225），本方案按 **日经225（华夏513520）** 实现；若确需日经200 需另寻标的（国内无对应 ETF，基本不可行）。
- **`bp_portfolio.params` 列**：探索报告显示该列存在且零引用，方案复用改名；实施前 `\d bp_portfolio` 复核，若不存在则迁移改为新增 `last_run_params` 列。
- **60/40 口径修复会改变存量组合指标**：用户已确认接受，重算即生效；dashboard 若缓存旧结果，靠 result_version 进缓存 key 自动失效。
- **日经基准起点 2019-06**：早于此的回测自动隐藏该基准（既有机制），文案已在 note 说明。
- **QDII 折溢价噪声**：ETF 价格含场内折溢价，与指数基准存在口径差，已在 note 披露。
- **涨跌色翻转**：全站约 40 处 up/down 用法需逐一确认语义（方向性保留，非方向性改语义色），漏改会造成「绿跌红涨」错觉——审计阶段重点核对。
- **全量重算时长**：本地 inline 顺序执行最坏 ~90 分钟，期间组合状态 running，编辑会 409（预期行为）。
- **schema.sql 基线更新**：合并 34-39 时需逐迁移比对，避免全新环境建库缺列。

# 设计文档：Builder / 调仓 UI 三视口重构 + 调仓计算器功能补全

日期：2026-09-20 · 状态：已与用户逐项确认（所有提问均有答案）

## 背景

用户提交 7 项 Builder / 调仓相关的 UI 与功能缺陷。根因分析由 7 个并行只读探索完成（每个结论均带
file:line 与编译产物证据），并在本地 Next.js :3000 + FastAPI :8000 上用 Playwright 以真实登录态实测复核。

**探索推翻了三条原始描述，这是本方案范围的基础：**

| 用户描述 | 实测事实 | 证据 |
|---|---|---|
| Builder 三区「从上到下固定高度」 | 三区是**互斥向导步骤**，同刻只有一个在 DOM 里；用户看到的竖排是顶部**步骤条** | `BuilderClient.tsx:466/508/553` 的 `{step === N && …}`；`:435` `flex flex-col sm:flex-row` |
| 漏掉创业板指/沪深300ETF/标普500/恒生指数 | 四个**全部存在且可添加**，数据到 2026-09-18 | 生产 `bp_index_config` 278 可选行：`399006` / `510300` / `513500` / `159920` / `HSI`；`/api/assets` 含之；推荐分组是前端硬编码常量 `:66-72` |
| 新建方案残留其他组合配置 | 未能复现（三种点击序列均得到 `已配置 0 项`） | Playwright 实测；跨路由导航在本构建下发生 document reload（`window.__spa_marker` 消失） |

「推荐资产里找不到」的真实机制是三个叠加：推荐侧栏把**已选进象限的标的从分组隐藏**（`:817`）、
**空分组整体不渲染**（`:818`）、组内渲染的是基金名而非指数名（`:990`）。

## 已确认的决策

| # | 决策 |
|---|---|
| 1 | 计算器金额列：**保留「计划持仓」语义并新增「当前持仓」列**，`买入 = max(0, 计划−当前)`、`卖出 = max(0, 当前−计划)`，`0` 为合法值 |
| 2 | Builder 布局：**保留向导**，把步骤条压扁成一行；三区内容各自瘦身 |
| 3 | 四个「缺失资产」：**ETF 代理就是想要的**，属显示问题（修 §3） |
| 4 | 交易费用：**只算现有三项**（佣金/滑点/印花税），费率取组合参数，不动 DDL |
| 5 | 「按目标权重填充」的拟投资金额：**工具栏内联展开** |
| 6 | 费用位置：**计算器内独立卡片 + Dashboard 调仓卡片摘要** |
| 7 | UI 统一范围：**四个面改造 + 全站同类偏差清单** |
| 8 | **不用 Figma**，按 `docs/design-system.md` 定稿，Playwright 三视口实测验收 |
| 9 | 四态 Badge 配色：新建仓 `success` / 加仓 `success` 淡化 / 减仓 `warning` / 清仓 `destructive`（语义色，**不得**使用 `text-up`/`text-down`） |
| 10 | 计算器宽度：`sm:max-w-5xl`（1024px），平板 `calc(100vw-2rem)`，手机卡片 |
| 11 | 拟投资金额：`localStorage` **按组合分别记住** |
| 12 | 份额取整：**100 份/手向下取整**，不足一手并入「取整后剩余现金」 |
| 13 | 「当前持仓」默认值**按日期类型自动切换**（历史调仓日 → 上期权重×拟投资金额；最近交易日 → `actual_holdings`） |
| 14 | 资产弹窗手机端：**吸底按钮 + Tabs 切换「全部资产 / 推荐 ETF」**（`< 768px`），≥768 保持双栏 |
| 15 | 计算器标的列：**名称右侧显示标的代码**（补充需求） |

> 说明：本表只收录用户明确回答过的选项。任何未提问的设想一律不进本方案。

## 一、Builder 页面三视口重构（`web/app/builder/BuilderClient.tsx`）

### 1.1 步骤条（唯一真正的「竖向堆叠」）

| 位置 | 现状 | 改法 |
|---|---|---|
| 容器 | `:430` `py-8 px-6 sticky top-16 z-40` | `py-3 px-4 sm:px-6 sticky top-14 sm:top-16 z-40` |
| 排列 | `:435` `flex flex-col sm:flex-row … gap-6` | `flex items-center`（**始终单行**） |
| 连接线 | `:436` `hidden sm:block` | 去掉 `hidden sm:block`，始终显示 |
| 单步 | `:441` `flex flex-col items-center gap-2` | `flex items-center gap-1.5 sm:gap-2`；圆点 `w-8 h-8 → w-6 h-6 sm:w-8 sm:h-8` |
| 标题 | 全称 | `< sm` 用 `QUADRANT_SHORT` 式短标签或缩短标签；`≥ sm` 用全称 |

`top-14 sm:top-16` 修掉手机端 Navbar `h-14` 与 `top-16` 之间 8px 的内容穿透（`Navbar.tsx:70`）。

### 1.2 步骤 1 四象限

- `:475` 删 `md:min-h-[500px]`。
- `:477` 删 `min-h-[240px]`；卡片 `flex flex-col`，`CardContent` 由 `p-4` 改 `p-3 sm:p-4`。
- 手机端从「1 列 4 张大卡」改为 `grid-cols-2 gap-3`（2×2 紧凑格），标题换短标签，空态文案 `text-xs`。
- 已选资产 chip 收紧：`text-xs`，`gap-1.5`，超过 4 个折叠显示 `+N`。
- `添加资产` 按钮 `mt-4 → mt-3`，`size="sm"`。

### 1.3 步骤 2 优化方法

- `:514` `space-y-4` → `grid sm:grid-cols-2 gap-3`。
- `:520` `CardContent p-5` → `p-4`；`:526` 描述 `text-sm leading-relaxed` → `text-xs leading-snug`。
- `优化指标` 开关区 `mt-8 pt-8` → `mt-5 pt-5`。

### 1.4 步骤 3 回测参数

- `:559` `CardContent p-6 space-y-8` + 7 处 `border-t pt-8` 分隔 → 改为无分隔线的栅格：
  `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-5`，每组 `<label>` + 控件自成一格。
- 四个费率项 `:613` `md:grid-cols-3`（4 个子项导致末项孤儿）→ `sm:grid-cols-2 lg:grid-cols-4`。
- 控件宽度 `w-full max-w-xs` 改为 `w-full`（栅格自带约束）。

### 1.5 响应式层级

补 `lg:` 层（当前文件 `lg:` 与 `xl:` 各 **0** 处，布局止步 768px，与 `design-system.md §6`
「1024+ 多列参数网格」不符）。**容器 `max-w-4xl` 保持不变**——那是设计系统 §3 对 builder 的正式豁免。

### 1.6 步骤条与底栏的空间回收

- `:429` `pb-24` → `pb-20 sm:pb-24`（底栏改单行后高度下降）。
- `:713-714` 底栏保持 `fixed bottom-0 left-0 w-full`，内部 `max-w-4xl mx-auto flex flex-wrap`；
  手机端按钮改 `flex-1` 等分，避免换行撑高。

## 二、资产选择弹窗（`BuilderClient.tsx:763-1049`）

### 2.1 三个根因

1. **确认添加要滚到底**：`DialogContent` 自身是唯一滚动容器（`:877` `max-h-[85vh] overflow-y-auto`），
   `DialogFooter` 是它**最后一个子元素**（`:1004`），无 sticky/fixed。
2. **推荐栏被挤出首屏**：`:881` `grid-cols-1 md:grid-cols-[minmax(0,1fr)_260px]`，`< md` 时堆叠，
   列表自身可达 `max-h-[60vh]`（`:905`）。
3. **三层嵌套滚动**：外层 `max-h-[85vh]` + 两个 `max-h-[60vh]`，且无 `min-h-0`/`flex-1` 链。

字体问题独立成因：`text-[10px]` 在 Tailwind v4 只输出 `font-size`、不输出 `line-height`，
于是继承 `DialogContent` 的 `text-sm` 行盒（20px）。全站 12 处 `text-[10px]`，本文件占 5 处。

### 2.2 改法

- 骨架改 `flex flex-col`，链上补 `min-h-0`：Header（`shrink-0`）→ 切换器（`shrink-0`）→
  滚动区（`flex-1 min-h-0 overflow-auto`）→ **Footer（`shrink-0`，移出滚动区）**。
  `DialogContent` 不再自己滚，改为 `max-h-[85vh] flex flex-col`。
- `useIsMobile()`（`web/components/ui/use-mobile.ts`，阈值 768，**builder 目前未使用**）：
  - `< 768`：segmented 切换「全部资产 / 推荐 ETF」，同一时刻只渲染一个，各自独立滚动。
  - `≥ 768`：保持现有双栏 `md:grid-cols-[minmax(0,1fr)_260px]` —— **PC/平板零回归**。
- 排版归一：5 处 `text-[10px]` → `text-xs`（设计系统唯一辅助字号）；行内 `· ${a.category}`
  改用 `ASSET_CATEGORY_LABELS[a.category]`（现在显示原始 db 值 `etf`，旁边下拉却显示「ETF」）；
  `border-l border-border md:pl-4` → `md:border-l md:pl-4`。
- 筛选行 `:884` `flex flex-wrap gap-2` + 两个 `w-28` 下拉 + `flex-1` 输入在手机端换 2–3 行；
  改 `< sm` 为 `grid grid-cols-2 gap-2`（搜索跨两列，两个下拉各占一列）。

## 三、推荐侧栏「找不到资产」（`BuilderClient.tsx:814-818`）

- `:817` 去掉 `!usedSet.has(keyOf(a))` 过滤：**已选标的保留在分组内**，以置灰 + `已选` 角标呈现。
  点击行为定为**禁用**（`disabled` + `title="已选入该象限，可从象限卡片移除"`），不引入跳转定位。
- `:818` 去掉 `.filter((g) => g.assets.length > 0)`：**空分组不再消失**，显示「本组已全部选入该象限」。
- 分组标题文案 `推荐 ETF（点击整组多选）` 保留；组内条目维持基金名（用户确认 ETF 代理即所需）。

## 四、调仓变动表 + Badge（`DashboardClient.tsx:1299-1363`、`ui/badge.tsx`）

### 4.1 换行根因

`badge.tsx:7` 基类**无 `whitespace-nowrap` 无 `shrink-0`**；标签是裸 CJK 文本节点（`:1328`/`:1336`），
CJK 无词边界 → `min-content` = 一个汉字宽。表格又是 `min-w-0`（`:1300`）+ 无列宽 + 表头无 nowrap →
**压缩列而非横滚**。同文件 `:1376` 的区间收益率表是正确写法（`min-w-[640px]` + `whitespace-nowrap`）。

### 4.2 改法

- `badge.tsx:7` 基类加 **`whitespace-nowrap`**（全站 17 个消费方一并受益，零副作用）。
- 调仓表 `:1300` `min-w-0` → `min-w-[560px]`；表头/单元格补 `whitespace-nowrap`。
- `:1249` `<Card id="rebalance">` 补 `min-w-0`（同 grid 内其他卡片都有，唯独这张漏了）。
- 四态 Badge（决策 9）：新建仓 `success` / 加仓 `success` 淡化 / 减仓 `warning` / 清仓 `destructive`。
  行派生逻辑 `:509-513` 已能区分 `isNew`/`isClose`，补 `isAdd`/`isCut`（`delta` 符号即可推导）。

## 五、调仓计算器（`web/components/RebalanceCalculatorDialog.tsx`）

### 5.1 三个 UI bug（均已确证）

| # | 症状 | 根因 |
|---|---|---|
| 1 | PC/平板太窄，多数列看不到 | `:142` `<DialogContent className="max-w-4xl">` 与基座 `dialog.tsx:61` `sm:max-w-lg` **变体不同**，twMerge 不合并；编译产物中 `@media (min-width:40rem)` 的 `.sm\:max-w-lg` 排在 `.max-w-4xl` 之后，同层同优先级 → **512px 在 ≥640px 全胜** |
| 2 | 平板/手机右上角关闭按钮不可见 | 无任何 `max-h`；框用 `translate-y-[-50%]` 垂直居中，内容 ≈52vh 表格 + ~250px 头尾 → 顶边为负；Close 是 `absolute top-4 right-4` 在框**内部**，随框移出视口 |
| 3 | 表格横滚 | `:181` `max-h-[52vh] overflow-auto` + `:182` `min-w-[720px]`，在 512px 内滚动 |

**改法**
- `:142` → `sm:max-w-5xl w-[calc(100vw-2rem)] max-h-[85vh] flex flex-col min-h-0`（决策 10）。
  宽度类必须带 `sm:` 前缀才能覆盖基座 `sm:max-w-lg`（既有计划
  `docs/superpowers/plans/2026-09-03-*.md:860-899` 已记录该规则）。
- 头部/工具栏/费用卡/页脚 `shrink-0`，表格区 `flex-1 min-h-0 overflow-auto`。
- Close 按钮：`< 768` 时改由底部「关闭」按钮承担（`useIsMobile`），保证任何视口都有可点关闭入口。
- `≥ 768` 表格；**`< 768` 卡片列表**（决策：手机端表格→卡片），每张卡 = 标的名称+代码 + 右侧权重 +
  两个金额输入 + 买入/卖出大字号结论 + 份额。

### 5.2 金额计算缺陷（用户报的「减仓/清仓显示不正确」）

**两个独立机制，均已数值复现：**

- `total`（`:61-68`）只累加 `n > 0`，`valid = amt > 0`（`:75`）把空白 / `"0"` / 负数一律判无效。
  - **清仓行永远无金额**：目标是 0 → `fillByTarget` 写入字符串 `"0"`（`:115`）→ `Number("0") > 0` 为假 →
    `—`。实测快照 `page-2026-09-18T15-37-46-930Z.yml:737-742`：摩根红利清仓行 5.93%→0.00%，
    计算器却显示 `最优化权重 0.00% / 金额 "0" / 自动换算权重 — / 差值 —`。
  - **卖单挂错标的**：被丢弃的行从分母消失，其余行 `curWeight = amt/total` 虚高 → 凭空造出卖单。
    复算：目标 .5/.3/.2，填 500000/300000/空 → `total=800000`，A 卖 100,000、B 卖 60,000，两笔皆假。
- `noiseFloor = max(1, total×1e-4)`（`:92`，用于 `:99` 汇总与 `:233` 明细）→ 百万级组合 **¥100 盲区**。

**改法**：按决策 1 重写为新模型（`0` 为合法值，`total` 只用于展示与费用基数）：

```
targetAmt_i  = 最优权重_i × 拟投资金额                // 计划持仓
currentAmt_i = 用户输入（默认见 §5.3）               // 当前持仓
buy_i  = max(0, targetAmt_i − currentAmt_i)
sell_i = max(0, currentAmt_i − targetAmt_i)
```

删除 `noiseFloor` 对明细行的抑制；仅保留最小显示阈值（< ¥1 显示 `-`），并保证
`Σ买入 + Σ卖出` 与明细逐行自洽（不再依赖「把残差补到最大行」这一 hack，改为在最后一行按
`拟投资金额 − Σ其他行` 反推，彻底消除舍入残差）。

### 5.3 功能增量

- **日期下拉新增「最近交易日 {as_of} 最优化权重」**：数据已在 payload（`optimal_holdings`，
  来源 `bp_backtest_cov.optimal_weights`，`backtest.py:317-332` `last_k = len(price_dates)-1`），
  **零后端改动**。选该档时行集改为 `optimal_holdings.holdings`（权重 ≥ `ZERO_EPS`），
  `asOf` 取 `optimal_holdings.as_of_date`。
- **当前持仓默认值按日期类型切换**（决策 13）：
  - 历史调仓日 → `上期权重_i × 拟投资金额`（对该日恒可算，清仓行自动 = 上期权重×金额）。
  - 最近交易日 → `actual_holdings`（`_build_actual_holdings` 漂移后市值，`repositories.py:1048`）。
- **工具栏内联展开拟投资金额**（决策 5）：默认 `1,000,000`，`localStorage` 键
  `bp_calc_amount:{portfolioId}` 按组合记住（决策 11）。修改后**自动重算**，无需再点按钮。
- **「按目标权重填充」**：重命名（去「示例」），写入 `targetAmt_i` 到计划持仓列。
- **ETF 份额**（决策 12）：新增批量价格接口 `GET /api/quotes/latest?keys=a@b,c@d`
  （单次请求，读 `bp_quote_clean` 的 CNY 清洗收盘价，与金额同币种）。
  `份数 = floor(金额 / 价格 / 100) × 100`，显示「买入 12,300 份（123 手）」；
  零头并入「取整后剩余现金」。
- **标的列名称右侧显示代码**（决策 15）：`name` 后跟 `text-xs text-muted-foreground font-mono`
  的 `symbol`（`ActualHolding` / `Holding` 均带 `symbol`/`source` 字段，`api.ts:317-334`）。
- **费用独立卡片**（决策 4/6）：计算器内表格下方独立区块，
  `佣金 = (Σ买 + Σ卖) × fee_rate`、`滑点 = (Σ买 + Σ卖) × slippage_rate`、
  `印花税 = Σ卖 × stamp_duty_rate`，费率取自 `portfolio`（`api.ts:375-377`，已在 Dashboard payload 内），
  与 `backtest.py:260` 同口径。Dashboard 调仓卡片也带一行费用摘要（决策 6）。

### 5.4 隐私文案（必须同步修改）

现状三处硬编码（`:160-163`、`:260-262`、`:266-270`）声称「金额不会上传服务器」。
新增取价请求后必须改为：「金额本地计算不上传；仅按标的代码查询最新收盘价」。

### 5.5 后端新增（`bp_api/otc_api.py` + `repositories_otc.py`）

```python
# repositories_otc.py
def latest_closes(conn, keys: list[tuple[str, str]], on_date: date | None = None) -> list[dict]:
    """批量取 (symbol, source) 在 on_date(含)之前最近交易日的清洗收盘价。一条 SQL 取全部，
       按 symbol+source 分组取 max(trade_date)。symbol/source 来自 bp_quote_clean。"""

# otc_api.py（公开端点，与 /api/otc/spot 同级）
@app.get("/api/quotes/latest")
def quotes_latest(keys: str = Query(...), date: str | None = Query(None)) -> dict:
    """keys: 'symbol@source,symbol@source'；返回 {date, quotes: [{symbol,source,date,close}|null]}"""
# 注: date 为本次批量查询的代表日(首个有值标的的交易日), 可为 null; 逐条 date 是该标的自己的交易日
```

单条 SQL（UNION/`DISTINCT ON`）取全部标的，避免 N 次往返。`source` 由前端以 `symbol@source`
形式提供（`DashboardClient` 的行 key 即该格式），故**不依赖** `resolve_source`（该函数只
自动解析 `asset_class LIKE '%index%'`，对 ETF 无效）。

**取价失败的降级路径**：若新端点在旧后端上不存在（前后端版本错配）或请求失败，
份额列整体隐藏、剩余现金不显示，其余功能不受影响（不弹错误、不阻断）。

## 六、全站同类偏差清单（决策 7）

四个面改完后跑 375/768/1440 × 明暗主题矩阵截图，产出清单。已知至少：

1. `ConfirmRecomputeDialog.tsx:26` `max-w-md` —— 与基座 `sm:max-w-lg` 同一个 twMerge 宽度 bug。
2. 全站 `text-[10px]` 共 12 处（本文件已修 5 处），其余 7 处在
   `DashboardClient:953`、`app/page.tsx:338`、`RiskMatrixSection:425`、
   `MiniTradingCalendar:134/178`、`CffexClient:454` —— 全部无行高。
3. `Navbar.tsx:201/287/491/610` `max-w-sm` —— 同类宽度变体问题。

清单只出**报告**，是否修复由用户二次定夺（用户选「全站差异报告」口径）。

## 七、验收

1. `python -m pytest bp_api/tests -q`（新增 `latest_closes` 单测）。
2. `cd web && npm run build` 与 `npm run typecheck`。
3. Playwright 三视口（375 / 768 / 1440）× 明暗主题，逐面截图核对
   `design-system.md §6` 验收标准：**无内容截断、无意外横滚、文字不重叠**，且后台 console 无 error。
4. 计算器功能回归：清仓行有卖出额、减仓行金额正确、份额为 100 整数倍、
   费用三项与手算一致、`0` 为合法金额、`Σ买入 − Σ卖出` 与总调仓金额自洽。
5. `git` 提交并推送 GitHub。

## 八、风险与回归面

- **Badge 基类加 `whitespace-nowrap`** 影响全站 17 个消费方。风险：长标签徽章（如 builder 的
  `已选 {n}`、admin 列表）本可换行的现在不换行。缓解：跑三视口矩阵检查这些页面。
- **计算器金额语义变更**是行为变更：老用户习惯「只填当前持仓」。缓解：新列有默认值，
  且默认值即原语义（历史调仓日 = 上期权重×金额），无需手工输入即可看到结论。
- **Builder 步骤条改单行**在 375px 下三格横向排布，标签必须缩短，否则溢出。
- **新端点 `/api/quotes/latest`** 的前后端版本错配已按 §5.5 降级处理。

# Builder / 调仓 UI 三视口验收报告

- 任务: Task 24（三视口浏览器验收 + 全站同类偏差清单）
- 日期: 2026-09-20（测量跨 09-20 夜 ~ 09-21 凌晨）
- 被测对象: `web/`（Next.js 16 App Router + React 19 + Tailwind v4）
- 结论: **DONE_WITH_CONCERNS** —— 7 个面在 3 个视口全部断言通过；存在 2 类共 16 处全站性残留偏差（7 处 `text-[10px]` + 9 处 `max-w-*`，均为既有存量、非本次改动面）与 5 项未能完全验证的边界，均已逐条列明，未修代码。

### 测量基线与被测工作树的时间关系（报告有效性边界）

**先纠正本报告初稿的一处表述错误**：初稿称「本报告写于这些改动之前，未覆盖其后状态」。按文件 mtime 事实并非如此——
本报告文件写于 **03:16:32**，而下列三次改动分别落在 02:40:29 / 03:06:34 / 03:07:09，**均早于报告落盘**。
准确的表述是：**报告文本晚于这三次改动，但报告内的截图与数值采于这些改动之前**（采样时工作树是改动前状态），
故这些改动确实不在测量覆盖内，但原因是采样早于改动，而非成文早于改动。

| 时刻 | 文件 | 改动 | 与报告的关系 |
| --- | --- | --- | --- |
| 03:07:09 | `web/components/RebalanceCalculatorDialog.tsx` | 「份额暂不可用」提示门控从 `!hasAnyPrice` 改为逐行谓词 `rows.some(r => r.category === "etf" && 无价)` | 采样**早于**改动 |
| 03:06:34 | `web/app/builder/BuilderClient.tsx` | Task 22 重置列表抽出 `FORM_DEFAULTS` 共用 | 采样**早于**改动 |
| 02:40:29 | `web/app/dashboard/DashboardClient.tsx` | `String(portfolio.portfolio_id ?? "demo")` → `Number.isFinite(...) ? ... : "demo"` | 采样**早于**改动 |

**此外还有一次真正落在报告落盘之后（03:16:32 之后）的改动，初稿完全未记录**：

| 时刻 | 文件 | 改动 |
| --- | --- | --- |
| ~03:3x | `web/app/builder/BuilderClient.tsx`（四象限 chip 渲染） | 象限内已选标的 chip 补 `max-w-full` + 名称 span `min-w-0 truncate` + X `shrink-0`，修复 375 下长名 chip 撑破卡片被 `overflow-x: clip` 裁切、删除 X 不可达 |
| ~03:5x | `web/app/dashboard/DashboardClient.tsx:1432,1449`（调仓变动卡 header） | 日期档位容器加 `min-w-0`、`<select>` 加 `max-w-full min-w-0`，修复新增档位把 select 撑到 263px 后 375 下档位切换控件不可达 |

该 chip 修复的终态实测（本次补测，30 个 chip / 组合 20）：

| 视口 | 溢出元素 | chip 溢出 | X 不可达 | bodyScrollW | 长名截断数 |
| --- | --- | --- | --- | --- | --- |
| 375 | 0 | 0 | 0 | 360（=视口） | 22 / 30 |
| 1440 | 0 | 0 | 0 | 1425（=视口） | 8 / 30 |

调仓卡日期档位的终态实测：

| 视口 | 不可达元素 | select 右缘 / 视口 | bodyScrollW |
| --- | --- | --- | --- |
| 375（修前） | 2（header 行 + select） | 400 / 360 | 400 |
| 375（修后） | 0 | 319 / 360（宽 182） | 360 |
| 768（修后） | 0 | — | 753 = 视口 |

**注意**：03:59 起本机到 `PGHOST` 的 PostgreSQL **握手超时**（TCP 可连、`connect_timeout=20` 稳定失败），
`/api/assets` 返回 500。上述两项补测均在 DB 可用时完成；**此后的页面复核不再可能**，
故本报告各面的数值结论一律以「上述改动前的工作树」为准，终态未逐面重测。

控制器在改动后**已复测**与本报告结论直接相关的三处，结论未变：面 6 在 1440 的表格溢出 `dx = 0`（`[scrollWidth 959, clientWidth 959]`）、关闭按钮在 1440/768/375 三视口均 `inViewport`、面 6 在 375 仍为卡片分支（`document.querySelector('table') === null`，卡片数 11）。

---

## 环境与方法

| 项 | 值 |
| --- | --- |
| 前端 | Next.js dev server `http://localhost:3000`（已由控制器启动，**未重启**） |
| 后端 | FastAPI `http://localhost:8000`（同上，未重启） |
| 鉴权 | 复用共享浏览器上下文中**已注入**的 `bp_session` Cookie（**未 mint JWT**） |
| 视口 | 1440×900 / 768×1024 / 375×667 |
| 采样方式 | `browser_run_code_unsafe` 内 `browser.newContext({ viewport: {...} })` 起**独立上下文**，每次采样在页内读 `window.innerWidth` 校验 |
| 一致性 | 全部批次 `window.innerWidth` 与目标值 **精确相等**（1440/768/375），无一个样本因宽度不符被丢弃 |
| 暗色 | `newContext({ colorScheme: 'dark' })` + 页内 `localStorage.setItem('theme','dark')`（见「暗色主题」节） |
| 截图 | `.playwright-mcp/` 下 38 张 `t24-*.png`，每面每视口一张 `fullPage:false` 视口截图 |

### 为什么用独立上下文而非 `browser_resize`

多 agent 共用一个浏览器上下文，`browser_resize` 会重定向**当前聚焦标签页**，别人切页即污染样本。因此每个视口都在同一次 `browser_run_code_unsafe` 调用内新建 `browser.newContext({viewport})`，并在页内回读 `window.innerWidth` 作为准入条件：只有回读值等于目标值才采纳该样本。本轮全部样本通过准入，故**无编号被标记为不可信**。

`browser_run_code_unsafe` 每次调用是全新 VM，`globalThis` / 挂在 `browser`、`context` 上的属性**均不跨调用存活**（实测：写入 `browser.__t24ctx` 后下次调用为 `undefined`），且 `import('node:fs')` 报 `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`。因此每个视口的完整测量-截图流程都封装在单次调用内完成；只有 `screenshot({ path })` 落盘是持久的。

### 断言取值约定

以下表格记录的是**页面实测返回的数值**（`getBoundingClientRect()` / `getComputedStyle()` / `scrollWidth` 等），不是通过/失败的布尔结论。凡是模拟值或推断值，均在「已知边界/未验证」中单列。

---

## 验收矩阵

### 面 1 — `/builder` 步骤 1（四象限）

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 步骤条是否单行 | 是 | 是 | 是 |
| 象限网格列宽 | `203px × 4` | `354px × 2` | `150px × 2` |
| 实际列数 | 4 | 2 | 2（2×2） |
| 文档横向滚动 | `docSW 1425 == docCW 1425`，无 | 无 | 无 |

- 步骤条：`flex items-center justify-between sm:justify-center sm:gap-16`，三个 chip（四象限 / 方法 / 参数）在三种宽度下均落在**同一行**（chip 的 `offsetTop` 三者相等）。
- 视口截图：`t24-f1-1440.png`、`t24-f1-768.png`、`t24-f1-375.png`
- 补充：添加资产后的步骤条：`t24-f1b-{1440,768,375}-after-add.png`

### 面 2 — `/builder` 步骤 2（优化方法）

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 网格类 | `grid-cols-1 sm:grid-cols-2` | 同左 | 同左 |
| 实际列数 | 2 | 2 | 1 |
| 卡片高度 | 158 / 158 / 131 px | 158 / 158 / 131 px | 158 / 158 / 131 px |
| 网格容器高度 | 505 px | 300 px | 257 px |

- 说明：`sm:grid-cols-2` 的断点为 640px，故 768 与 1440 同为 2 列，375 降为 1 列；这与验收要求「4→2 列，640 以下 1 列」在**当前实现下**等价于「≥640 即 2 列」。原要求里的「4 列」是旧版并排面板时代的描述，本面实测没有出现 4 列。
- 「块高度明显降低」：375 下网格高度 257px < 卡片两行叠加的更高布局，方向正确；768/1440 的高度缩减**未能可信测量**（见「已知边界/未验证」第 2 条）。
- 视口截图：`t24-f2-1440.png`、`t24-f2-768.png`、`t24-f2-375.png`

### 面 3 — `/builder` 步骤 3（回测参数）

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 外层网格列宽 | `181.5px × 4` 布局，`rowCount 1` | `315.5px × 2`，`rowCount 2` | `270px`，`rowCount 4` |
| 四个费率输入是否同一行 | **是**（`rowCount === 1`） | 否（2 行） | 否（4 行） |
| 输入框宽度 | 158 px（`sw 156 ≤ cw 156`） | 292 px | 247 px |
| 标签截断 | 无（全部 `sw==cw`, `sh==ch==20`） | 无 | 无 |
| 文档横向滚动 | `docSW 1425 == docCW 1425` | 无 | 无 |

- 关键代码：外层 `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-5`；四个费率输入置于内层 `sm:col-span-2 lg:col-span-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`，故 1440（lg）下四个费率**独占一行**，与要求一致。
- 视口截图：`t24-f3-1440.png`、`t24-f3-768.png`、`t24-f3-375.png`

### 面 4 — 资产选择弹窗

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 弹窗布局 | `md:grid`，列 `570px 260px` | `md:grid`，列 `410px 260px` | 单列 + 顶部 tab |
| 移动端 tab | 不渲染（`isMobile=false`） | 不渲染（`isMobile=false`） | `全部资产 / 推荐 ETF`，各 `133×33` |
| 四个推荐组 | 全部存在 | 全部存在 | 全部存在 |
| 「确认添加」位置 | 视口内 | 视口内 | `top 556 / bottom 592`（667 高视口内，**无需滚动**） |
| 真实点击「确认添加」 | 成功 | 成功 | 成功，**未触发 AlertDialog** |
| 命中归属 | `hitOwns: true` | 是 | 是 |

- `isMobile` 来自 `useIsMobile()` = `matchMedia('(max-width: 767px)')`，故 375 为 true、768 为 false —— 两栏布局在 768 保持，与要求一致。
- 推荐组来自 `RECOMMENDED_GROUPS`：国内宽基（588080/159915/510300/510050）、红利类、固收类、海外投资，四组在三个宽度下均可点选（点击后已选计数变化，见 `t24-f4c-*-picked.png`）。
- 视口截图：`t24-f4-1440.png`、`t24-f4-768.png`、`t24-f4-375.png`；移动端 tab 态另存 `t24-f4b-375-rectab.png`；已选态 `t24-f4c-{1440,768,375}-picked.png`

### 面 5 — `/dashboard?id=20` 调仓变动

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 表容器横向溢出 dx | 48 px | 0 px | 289 px |
| 是否压缩表格 | 否（改为滚动） | 否 | 否（`min-w-[560px]` 生效，外层 `overflow-auto`） |
| 清仓 badge 数 | 1 | 1 | 1 |
| 减仓 badge 数 | 5 | 5 | 5 |
| 加仓 badge 数 | 4 | 4 | 4 |
| 新建仓 badge 数 | 0 | 0 | 0 |
| badge 单行高度 | 22 px | 22 px | 22 px |

- 四态 badge 均包裹在 `<span className="inline-flex items-center gap-1.5">` 内、文案 `font-normal shrink-0`；实测每个 badge `getBoundingClientRect().height === 22`，即**均单行**，未发生换行。
- 375 下表格不压缩（`min-w-[560px]` + 外层 `overflow-auto`），改为表容器内横向滚动，dx = 289px。
- 视口截图：`t24-f5-1440.png`、`t24-f5-768.png`、`t24-f5-375.png`

### 面 6 — 调仓计算器

| 指标 | 1440 | 768 | 375 |
| --- | --- | --- | --- |
| 呈现形式 | 7 列表格 | 7 列表格 | **卡片列表**（DOM 中无 `<table>`） |
| 表横向溢出 dx | **0**（`scrollWidth 0 ≤ clientWidth + 1`） | **263** | 不适用 |
| 关闭按钮可见 | 是 | 是 | 是 |

- 1440 表格溢出 dx = 0 → 表格**完整放下**，无横向滚动。
- 768 溢出 263px → 表格横向滚动。这是**已知且已接受**的限制（`min-w-[880px]`），此处按数字报告，**不作为失败**。
- 375 走 `isMobile` 卡片分支，`document.querySelector('table')` 为 null。
- 费率卡 6 项与手算核对（见下）全部吻合。
- 视口截图：`t24-f6-1440.png`、`t24-f6-768.png`、`t24-f6-375.png`

**终态补测（控制器自跑，在上述三次改动之后）**

`t24-f6-*` 三期采样在 `RebalanceCalculatorDialog.tsx` 03:07 改动之前。控制器随后在 1440×900 与 768×1024 各补测一次，脚本与取值如下（`[role="dialog"]` 内取值）：

| 指标 | 1440×900 | 768×1024 |
| --- | --- | --- |
| 弹窗矩形 | `left 201 / right 1225 / top 68 / bottom 833`，`w 1024` | `left 9 / right 745 / top 77 / bottom 947` |
| 弹窗完全在视口内 | `fits: true` | `fits: true` |
| 关闭按钮矩形 | `top 68` 区内，`inViewport: true` | `top 94 / left 712 / w 16`，`inViewport: true` |
| 列头数量 | **7** | **7** |
| 列头文案 | 标的 / 最优化权重 / 当前持仓（元）/ 计划持仓（元）/ 买入 / 卖出 / **份额** | 同左 |
| 表格宽度 | 959 px（容器 `959 == 959`，**无横滚**） | 934 px（容器 `scrollW 934 / clientW 671`） |
| 「份额」表头可见位置 | `right 968 ≤ 1440`，**无需滚动即见** | `left 870 / right 968`，**屏外**（`> 768`），需横滚 |
| 横滚到底后 | 不适用 | `scrollLeft 263`；「份额」表头 `left 607 / right 705`，份额格 `买 30,900 份` `left 607 / right 705`，**均可及** |
| 文档横向溢出 | `false` | `false` |

- **标的名右侧显示标的代码**（本轮新增需求）：1440 下逐行读取「标的」列的两个 `<span>`，得到 10 行全部 `{name, code}` 成对，例如 `日经225 ETF（易方达） / 513000`、`恒生指数ETF（华夏） / 159920`、`标普500ETF（博时） / 513500`、`科创50 / 000688`。实现为同一 `<td>` 内两个 `block` `<span>`（名称 `truncate max-w-[12rem]`，代码 `text-xs font-mono text-muted-foreground`），即代码在**名称正下方**右对齐块内，不换行、不挤占名称。
- **份额列**：ETF 行有份数、非 ETF 行为 `-`。1440 实测 8 行有份、2 行为 `-`（`科创50`、`上证10年期国债ETF（国泰）` 该行当期无成交故为 `-`，非缺陷）；768 横滚后份额格文案同样是 `买 30,900 份`。
- **「份额暂不可用」降级提示未触发**：本组合 10 行 ETF 全部取到价，`showShareHint === false`（与「已知边界」第 7 条为同一谓词的两种取向，两者都取到了证据）。
- 补测截图：`.superpowers/sdd/acc-6-calc-1440.png`、`acc-6-calc-768.png`。

**费率卡数值核对（id=20 自身费率）**

组合 id=20 的费率为 `fee_rate=0.00015`、`slippage_rate=0.00005`、`stamp_duty_rate=0.0005`（与 id=12 的 `0.0002/0.0001/0.0005` 不同）。页面价格为 `/api/quotes/latest` 返回的 **2026-09-07** 价（513000=2.321、513630=1.608、518880=9.0238、159920=1.571、513500=5.384、510050=3.815、561580=1.404、511090=1.266、511260=140.022）。

| 项 | 页面渲染 | 独立 python 手算 |
| --- | --- | --- |
| 预计佣金 | ¥30 | 29.71 |
| 滑点成本 | ¥10 | 9.91 |
| 印花税 | ¥50 | 49.52 |
| 合计 | ¥89 | 89.14 |
| 取整剩余现金 | ¥5,183 | 5,183 |
| 买入手数合计 | 400 手 | 400 |
| 卖出手数合计 | 459 手 | 459 |

- 口径：`computeFees` = 换手×`fee_rate` + 换手×`slippage_rate` + 卖出额×`stamp_duty_rate`；`lotRound` 为 floor + 1e-9 epsilon，`LOT_SIZE=100`；`applyShares` 仅对 `category === 'etf'` 生效。数字全部对齐，取整后与页面展示一致。
- 清仓行显示的是**卖出金额**而非 `—`（此前 bug 已修）；ETF 行显示**份数**（而非手数）。

### 面 7 — 新建方案重置（`/builder?id=20` → `/builder`）

**结论: 代码路径已逐条核实（code-verified），运行时闭合未被证明（runtime-unproven）。**

> **措辞约束（承自控制器对 rev1922 的裁定）**：本面**不得**写成「已实测复现修复」。rev1922 审查者指出，Task 22 报告里
> 「每条路径都得到 0 项 / 第 1 步」的断言与同节的 `?id=20 → /builder` 实测（marker `"M-A"`、**"re-render? no"**）
> 相互矛盾——同一 JS realm、未观察到 remount，而 DOM 标记消失与「Next root 的普通 re-render」完全兼容，
> **不能**证明 `BuilderKeyed` 的 `key` 真的触发了卸载重建。因此本报告只报告**能证明的部分**。

采用对照/处理组设计区分「重新挂载」与「重渲染」：

| 组 | 操作 | h1 节点是否同一 | h1 上的标记属性 | 结论 |
| --- | --- | --- | --- | --- |
| CONTROL 1 | 步骤 3 内输入（普通重渲染） | `sameH1Node: true` | 存活 | 重渲染不丢失标记 |
| CONTROL 2 | 连点「上一步」两次（同一挂载） | `sameH1Node: true` | 存活 | 同挂载不丢失标记 |
| TREATMENT | `window.next.router.push('/builder')` | `sameH1Node: false` | `null`（丢失） | **观察不到 remount 证据**（见下） |

- **TREATMENT 组能证明什么、不能证明什么**：处理组同时满足 `spaNonceSurvived` 为真（SPA 导航，未整页 reload），
  但 `sameH1Node: false` 与「`key` 变化触发卸载重建」**并非一一对应** —— 普通 re-render 只要重建 DOM 节点
  （例如条件分支切换、列表 key 变化）同样会得到 `sameH1Node: false`。**因此这一组只否定「整页刷新」，
  不构成 `BuilderKeyed` 的 `key` 已生效的运行时证据。** 这是本面唯一的运行时观测，记在此处而非当作闭合证明。
- 重置后表单状态：步骤回到 1（step 1 为 active），已选 `已配置 0 项 · 0 个品种`，与 `FORM_DEFAULTS` / `defaultStartDate()` 一致。
  **该状态读数是真的**；未证明的是「达成该状态的机制是 `key` 重挂载」这一因果。
- **代码侧闭合路径**（rev1922 已独立逐条核实，可采信）：`BuilderKeyed` 按 `modeKey = edit:${id} | copy:${id} | "new"` 作为 `key`
  渲染 `BuilderInner`，从 `edit:20` 切到 `new` 时 `key` 的值发生变化，React 语义上必然卸载重建；
  审查者另独立扫了 `:122-149` 的全部 `useState`，`else` 分支逐项覆盖了 16 个字段，无字段能带着旧值存活。
  即：**两半由构造闭合**，缺的是运行时那一环。
- 视口截图：`t24-f7-{1440,768,375}-step3-marked.png`（处理前）、`t24-f7-{1440,768,375}-after-newplan.png`（处理后）、`t24-f7-1440-before-edit20.png`
- **补充行为说明（rev1922 Minor 3）**：切换组合会**强制关闭**已打开的计算器并丢弃其中的行内编辑。审查者判定这**是正确行为而非缺陷**
  （行集绑定旧组合，保留编辑更糟），但此前的修复章节未记录该行为变化，故在此补记。

---

## 暗色主题

对 **面 1（`/builder` 步骤 1）、面 4（资产弹窗）、面 6（调仓计算器）** 在 **1440 与 375** 共 6 个组合做暗色采样。

**方法（重要）**：单纯 `newContext({ colorScheme: 'dark' })` **不足以**切换主题 —— `next-themes` 配置为 `attribute="class" defaultTheme="light" enableSystem`，暗色类由 `localStorage` 的 `theme` 键驱动，不随 `prefers-color-scheme` 自动生效。因此实际做法是：

```
context = await browser.newContext({ viewport, colorScheme: 'dark' });
page.addInitScript(() => localStorage.setItem('theme', 'dark'));
```

即 **`colorScheme: 'dark'` + 显式写入 `localStorage.theme='dark'` 两法并用**，以 `document.documentElement.classList.contains('dark')` 为「已切换」的判据（实测为 true）。

| 组合 | 截图 | 低对比度样本 |
| --- | --- | --- |
| f1 @1440 | `t24-dark-f1-1440.png` | 1 处 |
| f1 @375 | `t24-dark-f1-375.png` | 1 处 |
| f4 @1440 | `t24-dark-f4-1440.png` | 1 处 |
| f4 @375 | `t24-dark-f4-375.png` | 1 处 |
| f6 @1440 | `t24-dark-f6-1440.png` | 1 处 |
| f6 @375 | `t24-dark-f6-375.png` | 1 处 |

- 每次运行**恰好 1 个**低对比度样本：四象限中「衰退」象限文字 `rgb(110,110,110)`（即 `.dark` 下的 `--weak-foreground: #6E6E6E`）落在卡片背景 `rgb(22,22,22)`（`--card: #161616`）上，对比度 **3.55:1**，低于 WCAG AA 正文 4.5:1。
- 这是设计系统里的既有语义色（`docs/design-system.md` 规定衰退象限用 `weak`），在浅色下 `--weak-foreground: #a1a1aa`。**报告为发现，未修**。
- 其余暗色 token 采样未出现新的低对比组合。

**独立复核（控制器自跑，`browser_emulate_media({colorScheme:'dark'})` + 页内写 `localStorage.theme='dark'`）**

上述「单纯 `colorScheme:'dark'` 不足以切换主题」的结论被独立复现，且给出了**该结论是 `next-themes` 配置所致、而非暗色失效**的证据链：

| 采样 | 结果 |
| --- | --- |
| 仅 `emulateMedia({colorScheme:'dark'})` 后 | `documentElement.classList` **仍含 `light`**、不含 `dark`；弹窗 `background: rgb(255,255,255)` |
| 追加 `localStorage.theme='dark'` + `classList` 切到 `dark` 后 | `darkActive: true`；弹窗 `bg rgb(19,19,19)` / `color rgb(229,229,229)`；`body bg rgb(10,10,10)` / `color rgb(237,237,237)` |
| 语义色在暗色下的解析 | `text-success` → `rgb(22,163,74)`、`text-warning` → `rgb(217,119,6)`、表头 `rgb(102,102,102)`，均随 `.dark` 重解析 |
| 主题来源 | `app/providers.tsx` 用 `next-themes` 的 `ThemeProvider`，`app/globals.css:5` 为 `@custom-variant dark (&:is(.dark *))`，`:42` 定义 `.dark` 变量块 —— 即暗色**由 `html.dark` 类驱动**，`prefers-color-scheme` 不是触发器，与「方法与说明」一节完全一致 |

- 复核截图：`.superpowers/sdd/acc-1-builder-s1-375-dark.png`（builder 步骤 1 @375 暗色）、`acc-6-calc-1440-dark.png`（计算器 @1440 暗色）。
- 复核未发现新的低对比组合；唯一的低对比项仍是上面的「衰退」象限语义色。

---

## Console

对 7 条路由 × 2 视口（1440 / 375）采集 `browser_console_messages(level="error")` 与页面错误：

| 路由 | 1440 console error | 375 console error | pageerror |
| --- | --- | --- | --- |
| `/builder` | 0 | 0 | 0 |
| `/dashboard?id=20` | 0 | 0 | 0 |
| `/cffex` | 0 | 0 | 0 |
| `/otc-derivatives-pricing` | 0 | 0 | 0 |
| `/admin` | 0 | 0 | 0 |
| `/methodology` | 0 | 0 | 0 |
| `/docs` | 0 | 0 | 0 |

**实际消息列表为空**（不是「有消息但都被判为非错误」）：14 次采集全部返回 `[]`；另挂 `page.on('pageerror')` 收集未捕获异常，同为 `[]`。因此本节不存在需要列出的消息条目。

**终态复核**：在 `RebalanceCalculatorDialog.tsx` 03:07 改动之后、1440 视口、计算器打开状态下再采集一次 `browser_console_messages(level='error')` → **0 条**；`/builder` 路由 @375 亦为 **0 条**。即上述三次改动未引入控制台错误。

---

## 全站同类偏差清单

### 偏差 A：`text-[10px]` 硬编码字号 —— 7 处

原始输出（从 `web/` 运行；从仓库根目录跑会漏掉 `components/`）：

```
app/cffex/CffexClient.tsx:454:                  {idx.name} <span className="font-mono text-[10px] opacity-60">{idx.variety}</span>
app/dashboard/DashboardClient.tsx:1120:                        className="inline-flex items-center gap-0.5 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
app/otc-derivatives-pricing/OtcPricingClient.tsx:1371:      {hint && <p className="text-[10px] text-muted-foreground/60">{hint}</p>}
app/page.tsx:338:                      <span className="text-[10px] text-muted-foreground">
components/MiniTradingCalendar.tsx:134:          <div key={w} className="text-[10px] text-muted-foreground py-0.5">{w}</div>
components/MiniTradingCalendar.tsx:178:      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
components/RiskMatrixSection.tsx:425:              <Badge variant="secondary" className="text-[10px] shrink-0 font-normal">
```

**计数 = 7，与控制台预期一致。**

| # | 文件:行 | 元素 | 类 | 意图 vs 实际 |
| --- | --- | --- | --- | --- |
| 1 | `CffexClient.tsx:454` | 品种代码 `<span>` | `font-mono text-[10px] opacity-60` | 意图：表内品种代码做次级小字；实际：绕过字号 token，固定 10px，不随根字号/无障碍缩放 |
| 2 | `DashboardClient.tsx:1120` | 参数标签 `<span>`（圆角胶囊） | `... rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary` | 意图：紧凑 inline 标签；实际：同上 |
| 3 | `OtcPricingClient.tsx:1371` | 提示 `<p>` | `text-[10px] text-muted-foreground/60` | 意图：极小辅助说明；实际：10px 已低于常规可读下限（`text-xs` = 12px） |
| 4 | `app/page.tsx:338` | 首页说明 `<span>` | `text-[10px] text-muted-foreground` | 同上 |
| 5 | `MiniTradingCalendar.tsx:134` | 星期表头 `<div>` | `text-[10px] text-muted-foreground py-0.5` | 意图：日历表头平铺；实际：固定 10px |
| 6 | `MiniTradingCalendar.tsx:178` | 图例 `<div>` | `mt-2 flex ... text-[10px] text-muted-foreground` | 同上 |
| 7 | `RiskMatrixSection.tsx:425` | `<Badge variant="secondary">` | `text-[10px] shrink-0 font-normal` | 意图：风险矩阵内小标签；实际：同上 |

共同点：7 处均为「次要小字」，字面值 10px；设计系统未定义 10px 级别，最小阶为 `text-xs`（12px）。属**既有存量**（非本轮新增），未修。

### 偏差 B：`max-w-(sm|md|lg)"` 未加 `sm:` 前缀 —— 9 处

注意 grep 的原样正则 `max-w-(sm|md|lg)"` 会**同时命中** `sm:max-w-lg`（因为 `sm:max-` 里的 `max-` 后面紧跟 `lg"`，子串匹配成立），从 `web/` 运行得 **13** 条。剔除 `sm:max-w-` 后的净计数为 **9**：

```
$ grep -rEn '(^|[^:a-z-])max-w-(sm|md|lg)"' app components | grep -vE 'sm:max-w-'
app/dashboard/DashboardClient.tsx:2285:      <DialogContent className="max-w-md">
app/otc-derivatives-pricing/OtcPricingClient.tsx:1528:      <DialogContent className="max-w-md">
components/BacktestProgressDialog.tsx:88:        className="max-w-sm"
components/ConfirmRecomputeDialog.tsx:26:      <DialogContent className="max-w-md">
components/Navbar.tsx:201:      <DialogContent className="max-w-sm">
components/Navbar.tsx:287:        <DialogContent className="max-w-sm">
components/Navbar.tsx:357:        className="max-w-sm"
components/Navbar.tsx:491:      <DialogContent className="max-w-sm">
components/Navbar.tsx:610:      <DialogContent className="max-w-sm">
```

**计数 = 9，与控制台预期一致。**（被剔除的 4 条为 `ui/alert-dialog.tsx:53`、`ui/dialog.tsx:61`、`ui/sheet.tsx:63`、`ui/sheet.tsx:65` 的 `sm:max-w-lg` / `sm:max-w-sm` 基类，是**预期行为**，非偏差。）

| # | 文件:行 | 元素 | 传入的类 | 作者意图 | 实际输出 |
| --- | --- | --- | --- | --- | --- |
| 1 | `DashboardClient.tsx:2285` | 调整组合顺序 `DialogContent` | `max-w-md` | 448px | 512px |
| 2 | `OtcPricingClient.tsx:1528` | 调整簿记顺序 `DialogContent` | `max-w-md` | 448px | 512px |
| 3 | `BacktestProgressDialog.tsx:88` | 回测进度 `DialogContent` | `max-w-sm` | 384px | 512px |
| 4 | `ConfirmRecomputeDialog.tsx:26` | 重算确认 `DialogContent` | `max-w-md` | 448px | 512px |
| 5 | `Navbar.tsx:201` | 登录 `DialogContent` | `max-w-sm` | 384px | 512px |
| 6 | `Navbar.tsx:287` | 修改密码 `DialogContent` | `max-w-sm` | 384px | 512px |
| 7 | `Navbar.tsx:357` | 强制绑定 2FA `DialogContent` | `max-w-sm` | 384px | 512px |
| 8 | `Navbar.tsx:491` | 两步验证管理 `DialogContent` | `max-w-sm` | 384px | 512px |
| 9 | `Navbar.tsx:610` | 注册 `DialogContent` | `max-w-sm` | 384px | 512px |

**根因（已实测）**：`cn()` = `twMerge(clsx(...))`；tailwind-merge **不跨变体去重**，基类的 `sm:max-w-lg` 与调用方传入的 `max-w-md` 属于不同变体，二者**都被保留**在最终 `class` 中；在 ≥640px 时 `sm:` 变体胜出。浏览器实测该元素 `class` 同时含 `sm:max-w-lg` 与 `max-w-md`，`getComputedStyle().maxWidth === "512px"`，证实**传入的 `max-w-*` 在 ≥640px 完全失效**。

**影响**：9 个弹窗在桌面端一律 512px 宽，而非各自意图的 384 / 448px。属**既有存量**（非本轮改动引入），且不影响功能（仅宽度）。修法应为调用方改用 `sm:max-w-*` 以同变体覆盖，或统一收敛到 token —— **本任务仅报告，未修**。

### 与控制台给出行号的两处不一致（显式标注）

| 偏差 | 控制台预期行号 | 实测行号 | 是否计数一致 |
| --- | --- | --- | --- |
| `text-[10px]` @ DashboardClient | 1110 | **1120** | 是（7） |
| `max-w-md` @ DashboardClient | 2281 | **2285** | 是（9） |

其余 6 + 8 行号**逐一精确吻合**。两处偏移的原因：`DashboardClient.tsx` 在本轮验收期间被其他 agent 持续编辑（mtime 02:40:29，git status 显示 ` M`），行号随插入/删除漂移。**计数（7 与 9）未受影响**。此差异按要求显式列出，未静默对齐。

---

## 已知边界/未验证

1. **面 5「新建仓」badge 未做高度实测**。组合 id=20 的调仓变动中「新建仓」行数为 **0**，故该态 badge 的 22px 单行高度**未被实测覆盖**（另三态已实测）。该态样式来自同一 `<span className="inline-flex items-center gap-1.5">` + `border-success/40 bg-success/10 text-success` 结构，**结构上同源，但未取得运行时证据**。

2. **面 2「块高度明显降低」仅在 375 方向可证，768/1440 未验证**。我用注入临时 `<style>` 覆盖 `p-5`/`gap-4` 来模拟改动前布局，得到 375 为 −44px（变矮），但 **768/1440 反而 +12px（比改动前更高）**。由于该模拟只覆盖了 padding/gap，而卡片内部 flex 行上的 `gap-4` 未同口径还原，**这个数字不可信**，故不作为结论。结论仅限：面 2 在 375 为 1 列（符合要求），768/1440 为 2 列；高度缩减幅度**未验证**。

3. **面 6 在 768（iPad 竖屏）需横滚 375px 才能看到「份额」列**。终态补测得的数字是**容器内需横滚 263px**（`scrollW 934 / clientW 671`），
   而「份额」表头在未滚动时位于 `left 870 / right 968` —— 相对 768 的视口，它**整体在屏外**；滚到底（`scrollLeft 263`）后到达 `left 607 / right 705`，才可及。
   两种算法（视口坐标 vs 容器 scrollWidth）差 112px，是因为弹窗左右各留了外边距、表格被 671px 的容器裁剪；**以容器横滚量 263px 为准**，
   但无论取哪个数，结论都是「768 下份额列不在初屏内」。**单列此条**：这不是「不改」的判断，而是本轮**未修**的限制（表格 `min-w-[880px]` + `isMobile` 断点为 767px，
   768 恰在断点之上故走桌面表格分支）。1440 已确认放下（溢出 dx = 0），375 走卡片分支（卡片内名称/代码/份额同屏，无需横滚）。
4. **暗色仅覆盖面 1/4/6 × 1440/375 六个组合**（按任务指定范围），未覆盖 768 与其余路由。`next-themes` 在 `colorScheme:'dark'` 单独作用下**不切换**主题，故全部暗色样本均为「context colorScheme + `localStorage.theme` 显式写入」两法并用所得，已在「暗色主题」节注明。

5. **未做真实数据写入型操作**（提交回测/重算/新建组合落库）。面 7 的处理组 `router.push('/builder')` 是唯一一次导航动作；其余断言均为只读测量。因此本报告不覆盖「写入后」的副作用路径。

6. **未重启 dev server、未 mint JWT**；`bp_session` Cookie 复用共享上下文。若期间有其他 agent 覆写 Cookie 或重启服务，本报告的采样时点（09-20 夜 ~ 09-21 凌晨）即为其有效边界。

7. **需求 #3（新建方案残留）的运行时闭合未被证明** —— 见「面 7」一节的措辞约束。本报告只声称**代码路径已逐条核实**，不声称运行时已复现修复。
   要拿到运行时证据，需要能在 `BuilderInner` 的挂载/卸载上观测到可区分的信号（例如在 `useEffect(() => {...}, [])` 里写一个只增不减的计数器并跨导航读取）；
   本轮的 `sameH1Node` 标记做不到这一点。

8. **「份额暂不可用」提示只取得了「不触发」一侧的证据**。终态复核时组合 id=20 的 10 行全部取到价，`showShareHint` 为 false（1440 实测），
   即该提示的**触发路径未被运行时覆盖**。其门控谓词为
   `rows.some(r => r.category === "etf" && !(Number.isFinite(priceByKey[r.key]) && priceByKey[r.key] > 0))`，
   刻意**不同于**审查者曾建议的 `!hasAnyPrice && rows.length > 0` —— 后者会在纯指数/商品组合（本就不显示份额列）上产生**误报**。
   谓词正确性由构造与 14 项单测覆盖，**未取得触发态的运行时截图**。

9. **需求 #2（四个缺失标的）的验证方式为 API 层，非 UI 层**。`GET /api/assets` 实测返回 **278** 个资产，四个目标全部在列：
   创业板指数 `399006`、沪深300ETF（华泰柏瑞）`510300`、标普500ETF（博时）`513500`（另有标普500 指数本体）、恒生指数 ETF（华夏）`159920`（另有恒生指数 `HSI`）；
   面 4 另在 375 实点了推荐组并断言已选计数变化。但**未逐个走完「搜到 → 勾选 → 确认添加 → 提交回测」的端到端路径**。

---

## 附：截图清单（38 张，均 `fullPage:false`）

### 本轮（t24 批次，38 张）

```
t24-f1-{1440,768,375}.png              t24-f2-{1440,768,375}.png
t24-f3-{1440,768,375}.png              t24-f4-{1440,768,375}.png
t24-f4b-375-rectab.png                 t24-f4c-{1440,768,375}-picked.png
t24-f1b-{1440,768,375}-after-add.png   t24-f5-{1440,768,375}.png
t24-f6-{1440,768,375}.png              t24-dark-f1-{1440,375}.png
t24-dark-f4-{1440,375}.png             t24-dark-f6-{1440,375}.png
t24-f7-{1440,768,375}-step3-marked.png t24-f7-{1440,768,375}-after-newplan.png
t24-f7-1440-before-edit20.png
```

路径前缀：`D:\balanced-portfolio\.playwright-mcp\`

### 终态复核（控制器自跑，8 张）

路径前缀：`D:\balanced-portfolio\.superpowers\sdd\`

```
acc-1-builder-s1-1440.png      acc-1-builder-s1-375.png
acc-1-builder-s1-375-dark.png  acc-4-picker-375.png
acc-6-calc-375.png             acc-6-calc-768.png
acc-6-calc-1440.png            acc-6-calc-1440-dark.png
```

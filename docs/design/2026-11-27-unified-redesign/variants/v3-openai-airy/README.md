# V3 · OpenAI Airy —— 全站 UI/UX 重构静态高保真原型

> 目录：docs/design/2026-11-27-unified-redesign/variants/v3-openai-airy/
> 单文件原型：index.html（内联 CSS/JS，零外部依赖、零网络请求）
> 数据快照：2026-11-27（数字来自 content-spec.md，补充合理 mock 序列；非真实行情，仅用于视觉/交互评审）

---

## 0. 如何查看

直接用 Chrome / Edge 打开 index.html：

- 顶部 pill 导航或 URL hash 切换三屏：#/a（指数估值首页）、#/b（HSI 详情）、#/c（Dashboard）
- 右下角：暗色 / 明色（跟随系统，可手动切）、演示加载（对当前屏所有卡片重播局部 Skeleton，页头/布局不动）
- 交互点：卡片 hover 光晕、行情徽标 hover 展开 8 类数据明细、MVI 两个 ? 公式、指标 tab、行业热力 hover、散点气泡 hover、表头排序、HSI modal、Dashboard 模式切换 / 组合下拉、涨跌/分位拆线等
- 推荐桌面 1440 宽、移动 390 宽查看；已验证两档均无横向滚动（scrollWidth === clientWidth）

---

## 1. 这个变体是什么

V3「OpenAI Airy」= 接近纯白/米白的画布 + 大留白 + 低对比灰阶 + 克制的 sky 点缀。

- 正文 15.5px / 行高 1.75（比基线 13-14px 工作台更松弛）；H1 clamp(27–33px)；卡片标题 19px；关键数字用等宽字体，hero 数字 52–58px
- 卡片无边框（暗色用 5.5% 白描边分层）、圆角 20px、极浅投影；hover 仅 1px 抬升 + 柔和光晕
- sky 只出现在主按钮、链接、选中态、主折线、焦点环——全屏彩色面积占比 < 2%
- 图表单色细线 + 6%–14% 面积渐变；去图例盒，改直接标注 + 紧凑图例；坐标轴/网格极浅
- 暗色是深灰（#161618）而非纯黑，卡片/次级面色阶 #1f1f22 / #27272b
- 动效 150–300ms，全部 transform/opacity，cubic-bezier(.16,1,.3,1)，尊重 prefers-reduced-motion

---

## 2. Design tokens

### 2.1 颜色

| Token | Light | Dark | 用途 |
|---|---|---|---|
| --bg | #fbfbf9 | #161618 | 米白 / 深灰画布 |
| --surface | #ffffff | #1f1f22 | 卡片 |
| --surface-2 | #f5f5f0 | #27272b | 分段底、表头、行 hover |
| --surface-3 | #eaeae3 | #323237 | 轨道、占位 |
| --ink-1 | #191917 | #f1f1ee | 标题/主数字 |
| --ink-2 | #4a4a45 | #c0c0b9 | 正文 |
| --ink-3 | #6e6e66 | #94948c | 次级文字 |
| --ink-4 | #9c9c93 | #6f6f68 | 弱化/脚注/坐标轴 |
| --hairline | rgba(25,25,23,.075) | rgba(255,255,255,.07) | 分隔线 |
| --sky | #0284c7 | #38bdf8 | 主按钮/链接/选中/主折线 |
| --up | #dc2626 | #f87171 | 涨（A 股语义：红涨） |
| --down | #16a34a | #4ade80 | 跌（绿跌） |
| --amber | #b45309 | #fbbf24 | warning / TE 预警 |
| brand gradient | #bae6fd → #c7d2fe → #fbcfe8 | 同 | 页面顶部柔光、品牌 mark |

- 涨跌方向严格按 A 股语义（红涨绿跌）；估值分位着色（热力/表内小圆点）是「便宜=绿、贵=红」的独立语义，二者不混用。
- 行业热力/表格小圆点用 color-mix() 混出 8.5%–17% tint，暗色自动换档，无需 JS 重算。

### 2.2 字体与数字

- 字体栈："Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei UI", …（无 CDN；Geist 缺失时回落系统 UI 字体）
- 数字："Geist Mono", ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas + font-variant-numeric: tabular-nums
- 阶梯：11px 脚注/坐标轴 · 12.5px 标签 · 13.5px 表格 · 15.5px 正文 · 19px 卡标题 · 27–33px H1 · 44–58px hero 数字
- 字距：大标题 -0.03em，数字 -0.04~-0.06em；中文标题行高 1.18，正文 1.75

### 2.3 形状 / 层级 / 动效

| Token | 值 |
|---|---|
| --r-control | 10px（按钮/输入） |
| --r-panel | 16px（浮层/popover/modal 内部块） |
| --r-card | 20px（卡片） |
| --r-pill | 999px（pill 导航/chips/badge） |
| --shadow-card | 0 1px 1px rgba(25,25,23,.025), 0 10px 34px -26px rgba(25,25,23,.2) |
| --shadow-hover | 同上 + 1px 抬升 |
| --float-shadow | 右下控制条 / popover / tooltip |
| 时长 | 150 / 200 / 240 / 300ms |
| 缓动 | cubic-bezier(.16,1,.3,1)（expo-out） |

- 入场：reveal-rise（opacity 0→1 + translateY 9px→0），按卡片 stagger 80ms
- hover：卡片 translateY(-1px) + 阴影；按钮 1px 下压；行背景 --surface-2
- 卡片 spotlight：radial-gradient(600px circle at var(--mx/--my))（pointermove 写入），sky 4.5% 极轻
- 全部动画有 prefers-reduced-motion 降级

---

## 3. 布局与响应式

- 顶部 64px glass sticky header：color-mix(bg 76%, transparent) + backdrop-blur(18px)，滚动后加深阴影；左侧品牌 + 中部 pill 屏切换 + 右侧静态原型标记
- 内容容器 max-width 1240px，左右 28px，桌面栅格 12 列；区块间距 26px
- 移动端 ≤820px：header 变两行（品牌 + 可横向滑动的屏切换）；卡片 padding 20/16px；表格隐藏次要列、数字更紧凑；≤520px 边距 14px
- 已验证 1440 / 390 两档 document.scrollWidth === clientWidth（无横向滚动）
- 窄屏表格用 hide-sm 隐藏非关键列而非横滚：估值列表保留「指数 / PE 分位 / 近 1 年」，跟踪基金保留「基金 / 规模 / TE」，持仓保留「资产 / 权重 / 动作」

---

## 4. 局部 Loading 策略（严格无全局 loading）

- 每个可加载卡片独立管理：data-skel="band|mvi|heat|div|table|metric|chart|fund|risk|stack"，JS 生成与真实内容同尺寸的低对比 pulse 骨架（不是 shimmer 高光，符合 Airy 低对比方向）
- 时长：基线 1200ms + 同屏卡片 80ms 内错峰，结束后 aria-busy=false + reveal-rise 300ms 淡入
- 骨架以 position:absolute; inset:0 覆盖在已完成布局的真实内容之上（内容 opacity:0），因此卡片高度从首帧起就是最终高度，零 layout shift；页头、导航、模式条、筛选控件永不出骨架
- 首次进入某屏 / 切换 Dashboard 模式才触发；「演示加载」按钮按当前可见范围强制重播
- 切换估值指标时不触发骨架：只有当前数值与曲线 120ms 交叉淡入（is-swapping），符合「切换零请求」规格

---

## 5. 三个屏幕

### A · /valuation 指数估值首页

1. 页头：H1「指数估值」+ 521 只指数说明 + 右侧数据状态徽标。hover/click 展开 8 类数据明细（A股 / 港股 / ETF / 基金净值 / 股指期货 / 指数行情 / 指数估值 / MVI），基金净值按 T-1 正常口径标灰；底部可「模拟 2 项待更新」——徽标变琥珀、明细变成 11-26 待更新。
2. Valuation Band（核心）：指数 segmented（沪深300/A500/上证50/中证全指）、窗口（近5年/10年/全部）、指标 tabs（PE-TTM/PB/股息率/风险溢价）。大数字 + 中性/低估/高估 badge + 5 年分位；主图为估值曲线 + 20–80 分位带 + 机会/中位/危险三条虚线；下方历史分位带（绿→灰→红，反向指标自动翻转方向与标签）；右侧 4 个指标 mini sparkline + 分位，点击即切 tab。切换只做 120ms 交叉淡入，不整卡 loading。
3. MVI：31.29 / 低估 / 估值分 68.71 / 风险分 66.92；两个 ? 展示真实公式（合计权重 16.86/19.27/28.53/23.47/11.88，MVI = 100 − cheap；风险分 = 0.55×波动分位 + 0.45×回撤分位，含 in-sample 声明）；5 个因子贡献条；周频折线 + 20–80 分位带；「打开图表」→ modal 双轴图（左 MVI 0–100 渐变面积、右指数收盘、4 指数切换、图例、hover 十字线显示日期/MVI/点位/PE 分位）。
4. 行业估值热力：16 个行业 4×4，PE 分位均值 → 绿/灰/红 tint，显示样本数；hover 出公式 tooltip；点击高亮 + toast（列表筛选联动留给开发）。
5. 红利指数吸引力：绝对估值（PB 对数轴 × 股息率，气泡=规模，最小二乘回归线 + R² + 拟合式）⇄ 相对估值（PB 分位 × 股息率分位，四象限底色 + 象限文字标注）；30 只红利/股息指数，气泡 hover 出名称/代码/PB/股息率/分位/规模。
6. 快速变化 · 指数列表：11 行，PE / PE 分位 / PB 分位 / 股息率分位 / 近 1 年；点击表头排序（aria-sort + 箭头），分位小圆点按便宜绿/贵红；恒生指数行可直接跳 B 屏，其余行 toast 提示「详情页未纳入本原型」。
7. 组件基线：按钮 primary/secondary/ghost/禁用、segmented、四种 badge、数据点状态、输入框、表头排序、info tooltip、局部骨架 demo。

### B · /valuation/HSI 恒生指数详情

- 面包屑 + H1 + HSI · 港股 · 82 只成分；右侧点位 24,586.32、+0.82%（红）、日期 2026-11-27
- 4 张 MetricCard：PE 11.2（35%）/ PB 1.05（29%）/ 股息率 3.41%（68%）/ 风险溢价 4.92%（61%），每张带分位条
- 估值与点位双轴图：PE 左轴、HSI 点位右轴；机会/危险值参考线；「分位带」开关（20–80 区间底色可开关）；近10年/近5年切换；hover 显示 PE、分位、点位、区间涨跌
- 跟踪基金：右上规模合计 1,274 亿 / 数据截至 2026-11-23 / 更新于 2026-11-27 21:10；Top10 规模条形图（hover 出基金信息）；12 只基金表格（公司/经理/规模/费率/TE/波动/1Y），TE 修复示例 SH513660 = 4.31%，TE > 5% 琥珀色 + 圆点；表头可排序、默认前 10 行 + 展开全部；行 hover 高亮
- 成分权重空态：统一空态卡「成分股权重数据建设中」+ 说明 + 状态行，不显示空表格/骨架
- 收益风险：1y/3y/5y 年化收益、波动、最大回撤、Sharpe 表格 + 收益/波动分组柱状图（红=收益、灰=波动）
- 页脚口径注脚：累计净值、TE 口径（acc_nav 回退 ETF 后复权）、HSI 全收益 / HSI×HKDCNY 标注、窗口与更新时间

### C · /dashboard 四象限 + 一篮子

- 顶部模式条：整行三段布局——左「演示数据 · 游客只读」，中 pill tabs（四象限组合 / 一篮子资产，白底+阴影 active），右「新建篮子 / 保存」始终固定不随模式跳动；移动端 tabs 独占一行、按钮全宽
- 四象限模式：居中标题「多资产全天候」+ 居中选择器（360px，带最近更新 2026-11-27 09:20，下拉 3 个组合）；KPI 行（9.2% / 7.8% / 1.18 / -12.4% / 1.46，每卡独立骨架）；净值曲线 vs 60/40 基准（全部/近3年/近1年 + hover）；2×2 四象限卡（权重/资产 chips/收益贡献，hover/点击展开配置明细）；当前持仓表（10 只：目标权重 / 风险贡献 / 持有/加仓/减仓动作）
- 一篮子模式：标题「A股核心资产」+「示例 · 只读 · 可复制」；选择器（示例篮子 / 我的篮子——切「我的篮子」显示统一空态）；KPI 行（6.8% / 21.4% / 0.24 / -34.2% / 1.48）；净值 vs 沪深300；风险贡献 12 段堆叠条（SVG，hover 出资产名/权重/风险贡献/近1年）+ 图例 + Top5 风险贡献；12 只持仓明细表（名称/代码/行业/权重条/风险贡献/近1年）；「复制为我的篮子」触发游客登录提示
- 页面内不出现全屏遮罩；图表/表格/KPI 各自独立 skeleton

---

## 6. 与 prologue.dev / 既有偏好原型的借鉴点

借鉴 prologue.dev（只借鉴质感与动效，不抄内容）

- 三级圆角体系 control/card/panel + pill 导航/chips
- glass sticky header（76% 背景 + 18px blur，滚动后抬阴影）
- 品牌柔光渐变（sky/lavender/pink）只做页面顶部环境光与品牌 mark
- 卡片 spotlight hover（鼠标位置 radial-gradient，极低透明度）
- reveal-rise 入场、mono 数字、低对比 Skeleton pulse（从 shimmer 改为更适合本变体的低对比 pulse）
- 直接标注替代重图例的图表排版

继承用户已偏好原型（index2.html）的结构语言

- d1（详情页左图右栏）：A 屏 Valuation Band 左主图/右四指标卡片、B 屏主图 + 竖排 Metric 卡、C 屏风险贡献左堆叠 + 右 Top5
- stockA（行内复权表格）：紧凑但可排序的数据表、行 hover、表头排序箭头、列级 mono 右对齐、把「选择/切换」放在行内 control
- basketA（表格型一篮子）：持仓明细 + 风险贡献 + 目标权重/动作列；KPI 行 + 净值图 + 说明卡的顺序
- cryptoB（三栏合约详情）：B 屏「左侧信息 / 中间主图 / 右侧指标」层级抽象为 Valuation Band 与 MVI 的主图 + 右侧指标列；MVI modal 采用其双轴 + 十字线 + 直接标注做法

不同于 prologue 的地方（刻意保持 V3 方向）：背景更暖（米白）、字号更大、留白更多、表格更松、sky 使用面积更小、图表去图例盒、暗色为深灰。

---

## 7. 数据与 mock 说明

- 规格中的真实快照数字全部落位：沪深300 PE 13.4(42%)/PB 1.38(38%)/股息率 3.20%(61%)/ERP 5.10%(55%)；MVI 31.29 · 低估 · 估值分 68.71 · 风险分 66.92；HSI 24,586.32 +0.82%、PE 11.2(35%)/PB 1.05(29%)/股息率 3.41%(68%)/ERP 4.92%(61%)、SH513660 TE 4.31%；Dashboard 9.2/7.8/1.18/-12.4%/1.46 与 12 只篮子名单；数据状态 8 类 + 基金净值 11-26 T-1 口径
- 其余历史序列（估值曲线、分位带、MVI 周频、HSI 双轴、净值曲线）为确定性 mock：由端点值 + 中位数/波动率参数用 seed 随机数生成并平滑，保证「端点=快照数字、无明显尖刺、每次打开一致」。开发时替换为 /api/v1/valuation/*、/api/v1/market/mvi*、/api/baskets/* 真实数据即可，图表渲染层与数据解耦
- 回归 R²、TE 预警、行业样本数、基金公司/经理等为合理示意（不构成真实数据承诺）

---

## 8. 可访问性 / 工程约束

- 所有交互控件为真实 button / 表格语义 / aria-sort / aria-selected / aria-expanded / aria-busy / role=switch / role=tablist；tooltip 支持 hover/focus/点击，Esc 关闭；modal 有 role=dialog、焦点进入与返回、backdrop 关闭
- 焦点环 2px sky + offset；正文对比 ≥ 7:1；图表均有 role=img + aria-label
- 零外部依赖：无 CDN、无字体文件、无图表库；全部图标与图表均为内联 SVG；离线双击即可打开
- 唯一运行时依赖是浏览器原生能力（CSS custom properties / color-mix / backdrop-filter / Intl）

---

## 9. 文件

| 文件 | 说明 |
|---|---|
| index.html | 单文件原型（A/B/C 三屏 + 明暗 + 演示加载 + modal + tooltip） |
| README.md | 本文档 |
| screenshot-desktop.png | 桌面 1440×2600 · A 屏（默认浅色） |
| screenshot-mobile.png | 移动 390×2600 · A 屏 |
| screenshot-desktop-hsi.png | 桌面 · B 屏 HSI 详情 |
| screenshot-desktop-dashboard.png | 桌面 · C 屏四象限 |
| screenshot-desktop-basket.png | 桌面 · C 屏一篮子（含风险贡献堆叠条） |
| screenshot-desktop-dark.png | 桌面 · A 屏暗色 |
| screenshot-mobile-dashboard.png | 移动 · C 屏 |
| screenshot-mvi-modal.png | MVI 双轴 modal |
| screenshot-chart-hover.png | 估值图 hover 十字线 + tooltip |

---

## 10. 已知限制与建议下轮调整

1. 历史曲线为 mock：曲线形状与真实历史不保证一致；接入真实 API 后需重新校准分位带/MVI 平滑与轴范围。
2. 移动端隐藏次要列：为保证「不横向滚动」隐藏了估值列表 3 列、基金 1Y 收益、持仓类别等；若产品希望移动端保留全列，可改为表格内横向滚动（行 hover/排序逻辑无需变）。
3. 组合下拉/排序/筛选为演示态：切换组合只改标题与 toast、不改数据；行业热力点击仅高亮 + toast（筛选联动已在列表预留行业标签）；除 HSI 外指数行不跳详情。
4. 三个可调取舍：
   - 密度 vs 留白：当前正文 15.5px / 卡片 padding 30px / 区块 26px，若希望一屏看更多，可整体收紧约 10%（字号 14.5、padding 24、间距 20）。
   - sky 的存在感：当前只用主按钮/链接/选中/主折线；若品牌记忆点不够，可把 segmented active 与 tab 下划线之外的 hover 也加 sky wash。
   - loading 时长：1.2s 是演示时长；真实实现建议骨架 300–600ms + 数字 200ms 过渡，且保持「页头/布局不动」。
5. 暗色为深灰而非纯黑（#161618）：若用户更偏强对比黑，把 --bg 调到 #0e0e10、surface 到 #17171a 即可，token 已集中。

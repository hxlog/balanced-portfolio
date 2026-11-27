# V2 · Vercel Mono Grid —— 全站改版静态高保真原型

> 目录：docs/design/2026-11-27-unified-redesign/variants/v2-vercel-mono/
> 单文件原型：**index.html**（内联 CSS / JS，零外部依赖，file:// 直接打开即可）
> 数据快照：**2026-11-27**（取自 content-spec.md 的真实数字；时间序列为确定性 mock，见「数据」一节）

---

## 0. 一句话定位

**黑白高对比、1px 细网格、mono 数字、信息密度最高的仪表盘方向。**
彩色只保留「A 股语义涨跌红绿」以及极少量 sky 说明色；卡片不靠阴影、只靠 1px 边框和分栏线分层；动效近乎为零（120ms 透明度）；loading 一律局部「骨架线 + 细条扫描」，没有全局遮罩。

顶部 A / B / C 三个 tab 切换 #/a、#/b、#/c 三个屏幕；右下角浮动控件：**暗 / 明** 主题切换 + **演示加载**。

---

## 1. 文件

| 文件 | 说明 |
|---|---|
| index.html | 三屏单文件原型（A 指数估值 / B 恒生指数 / C Dashboard 四象限 + 一篮子） |
| README.md | 本文档：设计决策、继承点、已知限制 |
| screenshot-desktop.png | 1440 × 2600 · 屏幕 A（默认暗色） |
| screenshot-mobile.png | 390 × 2600 · 屏幕 A（移动端，真实 390px 视口，非缩放） |
| screenshot-desktop-b-hsi.png | 1440 × 1780 · 屏幕 B 恒生指数 |
| screenshot-desktop-c-dashboard.png | 1440 × 1210 · 屏幕 C 四象限 |
| screenshot-desktop-c-basket.png | 1440 × 1560 · 屏幕 C 一篮子模式 |
| screenshot-light.png | 1440 × 2600 · 屏幕 A 浅色主题（补充证据） |
| screenshot-modal.png | 1440 × 1400 · MVI 展开图表 modal（补充证据） |
| screenshot-loading.png | 1440 × 1400 · 「演示加载」局部 Skeleton 状态（补充证据） |

打开方式：直接双击 index.html（file:// 可用，零网络请求）。也可用 ?theme=light#/a 强制浅色；#/b、#/c 直达屏幕。

---

## 2. 设计 Token

### 2.1 色彩（两套变量）

| Token | 深色（默认） | 浅色 | 用途 |
|---|---|---|---|
| --bg | #000000 | #fafafa | 页面底色（纯黑，最高对比） |
| --surface | #0a0a0a | #ffffff | 卡片底层 |
| --surface-2 | #101010 | #f5f5f5 | 表头 / tooltip / popover / hover 底 |
| --line | #232323 | #e4e4e7 | 1px 网格/分栏线（唯一的分层手段） |
| --line-2/3 | #2e2e2e / #454545 | #d4d4d8 / #a1a1aa | 控件边框 / 强分隔 |
| --text / 2 / 3 / 4 | #ededed / #a3a3a3 / #7c7c7c / #4d4d4d | #09090b / #52525b / #6f6f78 / #a1a1aa | 主 / 次 / 弱 / 极弱 |
| --accent | #38bdf8 | #0284c7 | sky：唯一非涨跌彩色（选中线、当前点、信息点、focus） |
| --up | #f87171 | #dc2626 | **涨**（A 股语义：红涨） |
| --down | #4ade80 | #16a34a | **跌**（绿跌） |
| --warn | #fbbf24 | #b45309 | 仅 TE > 5% 数据质量告警（全站唯一 amber 例外） |
| heat | #4ade80 / #fbbf24 / #f87171 | #15803d / #a16207 / #b91c1c | 行业热力：低分位（便宜）绿 → 高分位（贵）红 |

**色彩纪律**：面板/图表/交互态全部黑白灰；只有方向性数字、涨跌 tag、行业热力、极少量 sky 焦点使用彩色。卡片 **无 box-shadow**，所有层级由 1px 边框 + 分栏线完成（例外：屏幕级 modal / 浮动控件使用极弱的大扩散阴影，以保证浮层可读）。

### 2.2 字体与数字

- 无衬线：系统栈 -apple-system / Segoe UI / PingFang SC / Microsoft YaHei（不引入 CDN 字体）。
- **所有数字/代码/时间/公式用 mono 栈**：Cascadia Mono / SFMono-Regular / Consolas / Liberation Mono / Menlo / ui-monospace，font-variant-numeric: tabular-nums；letter-spacing: -.015em。这样在 Windows/macOS 都能落到等宽数字；**注意不是真正的 Geist Mono**（零外部依赖的代价，见「取舍」）。
- 字号阶梯：标签 8.5–11px（大写 + letter-spacing .08–.18em）· 正文 11.5–12.5px · 卡片标题 12px/600 · 大数字 23–38px/500 mono · H1 22px · 页面 H1 仅一处。
- 行高 1.5；表格行高 40px；面板头 42px；分区间距 12px。

### 2.3 形状与密度

- **无圆角**（卡片 / 面板 / 表格 / heat cell = 0；按钮、segmented、popover = 6px；tag = 2px）。这是与「prologue 三级圆角」最明确的区隔。
- 页面容器 max-width: 1480px；桌面 12 栅格；栅格间距 12px；面板头/脚固定 42px / 32px。
- 无空白策略：所有卡片都有内容或统一空态；表格无数据不渲染空骨架；页脚（口径/来源）常驻。

---

## 3. 三屏信息架构

### A · 指数估值（/valuation）

1. **页头**：标题 + 沪深300 点位/涨跌联动 + 521 只指数口径 + **DATA FRESHNESS 徽标**（sky dot + 2026-11-27 + 8/8）。hover/点击展开 **8 类数据集明细**（A股 / 港股 / ETF / 基金净值 T-1 / 期货 / 指数行情 / 指数估值 / MVI），并注明 update 链路与 T-1 口径。
2. **估值分位带**（核心，8 栅格）：指数 segmented（沪深300 / 中证A500 / 上证50 / 中证全指）+ 近5/10年/全部；PE-TTM / PB / 股息率 / ERP 指标 tab；大数字 + 分位 + 低估/中性/高估 tag；主图 = 估值曲线 + P20–P80 分位带 + 机会/中位/危险三条虚线 + 当前 sky 点；下方 refs 行 + hover 十字线（日期 / 值 / 滚动分位）。右侧 4 个指标 mini 面板（sparkline + 分位 + 点击切 tab）。
3. **市场估值指数 MVI**（12 栅格，5/7 内分栏）：当前值 31.29、低估 tag、估值分 68.71 / 风险分 66.92、5 因子贡献条、近 5 年走势 + 分位带；两个 ? 分别给出**估值分 / 风险分公式**（权重、因子、窗口、in-sample 声明）；「打开图表」→ **双轴 modal**（左轴 MVI 渐变面积 0–100 / 右轴指数收盘，4 指数切换，十字线 tooltip）。
4. **行业估值热力**：16 行业 2 行 × 8 列，名称 + PE 5Y 分位 + 样本数；低分位绿 / 高分位红（与涨跌红绿无关，? 里有公式说明）；逐格 tooltip。
5. **红利指数吸引力**：绝对估值（PB 对数轴 × 股息率散点，气泡=基金规模，OLS 回归 + R² 0.94）/ 相对估值（PB 分位 × 股息率分位四象限）双模式；右侧回归方程 + 股息率 TOP5 + 一行解释。
6. **快速变化**：11 只指数简化表（名称/代码/收盘/PE 分位/PB 分位/股息率分位/近1年），表头排序、行 hover、点击行打开右侧详情抽屉；恒生指数行直接跳 B 页。
7. **组件与状态**：底部组件样张（按钮 / segmented / tags / popover / 空态 / 局部 skeleton），用于评审组件规范。

### B · 恒生指数详情（/valuation/HSI）

1. 页头：HSI · 港股 · 82 只成分 · 港元口径 + 24,586.32 +0.82%（红涨）。
2. 指标条 4 卡：PE 11.20（35%）、PB 1.05（29%）、股息率 3.41%（68%）、ERP 4.92%（61%），每卡带 0–100 分位 bar。
3. 主图卡：PE-TTM 左轴 + 点位右轴（近10/5年切换 + 分位带开关），机会 9.20 / 危险 13.80 参考线，十字线 tooltip 显示 PE / 点位 / PE 滚动分位。
4. 跟踪基金：规模合计 1,274 亿 · 数据截至 2026-11-23 · 更新于 2026-11-27 21:10；全宽 Top10 规模条形图 + 9 列表格（代码/名称/公司/经理/规模/费率/TE 1y/波动/1y收益）；**SH513660 = 4.31%**（已按修复后口径）；**TE > 5% 用 amber 虚线标注**（5.41% 示例，附数据质量 tooltip）；表头排序、展开全部 23 只。
5. 成分/行业：**统一空态**「成分股权重数据建设中」+ 说明 + PENDING tag（不渲染空表格）。
6. 口径说明卡：累计净值 / 指数口径 / 样本窗口 / TE / 更新时间。
7. 页脚：口径脚注。

### C · Dashboard（/dashboard）

- **模式条整行居中**：四象限组合 / 一篮子资产两个 pill tab；右侧操作（新建篮子 / 保存）固定，不随模式跳动。
- **四象限模式**：标题「多资产全天候」+ 居中组合下拉（含最近更新 2026-11-27）；KPI 5 项（+9.2% / 7.8% / 1.18 / −12.4% / 1.46）；NAV vs 60/40 基准（hover 显示组合/基准/超额）；2×2 四象限矩阵（复苏/过热/滞胀/衰退：权重、资产 chips、收益贡献，hover 展开明细）；当前持仓 9 行（资产/类别/权重/风险贡献/再平衡动作）。
- **一篮子模式**：示例「A股核心资产 12 只」+ 示例·只读·可复制 tag；KPI（+11.4% / 19.2% / 0.59 / −28.6% / 1.72）；NAV vs 沪深300；风险贡献堆叠条 + Top8 列表 + 其他 4 只；12 只持仓表（目标权重 / 风险贡献 / 近 1 年 / 数据区间）。复制按钮提示「复制需登录」，标注游客只读、仅管理员可编辑。

---

## 4. 图表（全部内联 SVG，零依赖）

自研轻量图表引擎 drawLineChart()：测量容器实际像素后按真实尺寸绘制（非 viewBox 缩放），支持：

- 单/双 Y 轴、水平网格、x 轴年份刻度、图例（HTML，CSS 变量控制颜色）；
- 面积渐变（modal MVI）、横向分位带、参考虚线、当前值 sky 圆点；
- **十字线 tooltip**：pointermove / pointerdown / ←→ 键盘可取点，tooltip 显示日期 + 多系列值 + 分位；
- 主题切换无需重绘：所有 stroke/fill 都走 CSS class + var(--*)。

图表清单：估值分位带（A）、MVI 走势（A）、MVI 双轴 modal（A）、红利散点/四象限（A）、HSI 双轴（B）、HSI 风险柱（B）、基金规模条形（B）、组合 NAV（C）、篮子 NAV（C）、mini sparkline（A 右侧 4 个）。所有主图都有坐标轴/网格/图例/tooltip；散点图另含对数轴、回归线、R²、四象限标注。

## 5. 动效与 Loading 策略

- **动效近零**：全站只有 120ms 透明度过渡（换指标/窗口、图切换、抽屉/浮层淡入）；无 reveal-rise、无 glow、无 spotlight、无布局位移。prefers-reduced-motion 下动画时长降为 0.01ms。
- **局部 loading（禁止全局）**：每张卡片独立控制 data-busy，skeleton 覆盖本卡；页头 / 导航 / 栅格尺寸完全不动。首次进入各屏时逐卡 1.2s（+45ms 阶梯）后揭开；「演示加载」按钮重回放整屏局部 loading（右下角状态显示 LOCAL LOAD · n CARDS → DONE）。
- skeleton = 与真实内容同尺寸的骨架线（图表块 / 表格行 / KPI 格 / 热力 16 格 / mini 列表）+ 一条 1.2s 细条扫描（--sheen，深色为白色 5% 微光，浅色为黑色 5%）。
- 空态统一：图标 + 一行说明 + 可选行动/tag，不显示空表格骨架（B 成分区块）。

## 6. 响应式

| 断点 | 行为 |
|---|---|
| ≥1200 | 完整 12 栅格、8/4 与 7/5 分栏、双轴图表 |
| 1024–1199 | 部分面板内部分栏堆叠（MVI / 红利 / 基金）；导航仍单行 |
| 768–1023 | 12 栅格收为 6 栅格，KPI 3 列，heat 4 列，Dashboard 头部纵向 |
| <768 | 单列全宽、KPI 2 列、heat 4 列、四象限 2×2（≤420 单列）、表格容器内横向滚动（页面不横滚）、浮动控件紧凑化 |

已用真实 390px 视口验证：document.scrollWidth = clientWidth = 390，页面无横向滚动；长表格只在 overflow-x:auto 容器内部滚动。

## 7. 无障碍与交互完整性

- focus-visible 1px sky ring；按钮/seg/tab/tag 的 hover / active / pressed / disabled 全有态；
- seg 用 aria-pressed，metric tabs 用 role=tab + aria-selected；图表绘制区 tabindex=0 + 方向键取点；
- tooltip role=status；modal aria-modal + ESC 关闭 + overlay 点击关闭；抽屉 ESC/遮罩关闭；
- 主题选择写 localStorage，并支持 ?theme=light|dark 参数（截图/评审用）；
- 键盘可操作所有 tab、排序表头、下拉、modal。

## 8. 与用户偏好（d1 / stockA / basketA / cryptoB）的继承点

- **d1 详情页「左侧主图 + 右侧指标栏」** → A 估值分位带 8/4 分栏、B 主图 + 风险卡 7/5、卡片内「主值 + 右侧 4 mini 指标」；大数字 + 分位 + 参考区间 + 数据点徽标的排版语言保留。
- **stockA 行内复权表格** → B 跟踪基金 9 列表格（代码+名称合并首列、费率/TE/波动/收益数字列右对齐 mono、TE 异常行内标注）、A 快速变化表；表头排序与行 hover 一致。
- **basketA 表格型一篮子** → C 一篮子模式以表格为核心（权重/风险贡献/收益），风险贡献用堆叠条 + Top 列表补充，不做卡片化分组；「示例·只读·可复制」的状态标签同样保留。
- **cryptoB 三栏合约详情** → B「主图 + 右侧指标 + 下方明细表」、C 四象限「主图 + 右侧矩阵 + 下方持仓」的三段式节奏；顶部标题 + 右侧大数字 quote + 日期引用的结构一致。
- 全局：sky 主色、13px 上下信息密度、segmented、mini panel、白/暗卡片、数字 tabular —— 全部继承，只是把圆角/阴影/彩色收掉，换成 1px 网格与 mono 排版。

## 9. 与 prologue.dev 的借鉴（只借质感，不抄内容）

- **借鉴**：三级层级（page / panel / control）→ 用「背景 / 1px 边框 / 线框控件」重写；uppercase eyebrow + mono 数字；克制 hover（颜色/边框变化，不做位移）；skeleton 骨架线 + 扫描带；tooltip / popover 的紧凑排版；sticky 顶栏（本变体改为**实色细线导航**，无 glass、无 blur、无 glow）。
- **刻意不借**：glass header、品牌渐变、spotlight hover、reveal-rise 入场、大圆角、彩色渐变面积 —— 这些与「黑白高对比 + 静默动效」的变体方向冲突，改由 1px 网格、mono 数字、极浅的线框与色阶承担质感。

## 10. 数据与 mock 说明

- 真实快照（来自 content-spec.md，2026-11-27）：A 页固定数字（沪深300 PE 13.40 / 42%，PB 1.38 / 38%，股息率 3.20% / 61%，ERP 5.10% / 55%），MVI 31.29 / 估值分 68.71 / 风险分 66.92，B 页 HSI 24,586.32 +0.82% 与 4 个指标、SH513660 TE 4.31%、跟踪基金更新时点，C 页四象限 KPI 9.2/7.8/1.18/−12.4/1.46。所有 8 类数据日、基金总规模 1,274 亿等均按规格写入。
- mock：其余指数（A500/上证50/中证全指）的估值、时间序列、16 行业分位、30 只红利指数、23 只基金、HSI 历史与组合 NAV 均为**确定性种子生成**（同一份 HTML 打开两次结果完全一致），用于视觉评审，不代表真实历史。时间序列刻意去尖刺、平滑处理（MVI 与分位带均满足该要求）。B/C 的筛选、排序在本地数据上真实生效。
- 零外部依赖：无 CDN、无字体文件、无图表库、无网络请求；所有图标为内联 SVG path，所有图表为运行时内联 SVG。

## 11. 已知限制与建议后续

1. **非 Geist 字体**：零外部依赖下使用系统 mono 栈（Windows = Cascadia Mono / Consolas，macOS = SF Mono），数字宽度与气质接近但非官方 Geist Mono；若允许内嵌 woff2 可 100% 还原。
2. **只有 HSI 有详情页**：A 页其它指数行点击打开的是右侧详情抽屉（代替详情页跳转），抽屉底部「打开详情页」在非 HSI 行禁用；这是与 content-spec「点击行进入详情页」的临时折中。
3. **B/C 数据不联网**：基金 23 只、红利 30 只等为生成数据；仅用于看密度、对齐与状态，不作数据验收。
4. **动效趋零是变体方向**：如果用户想要更强的 prologue 感，建议只把「加载揭开」改为 300ms reveal-rise + 卡片 hover 1px 抬升，其余保持安静。
5. **amber 例外**：全站唯一的非涨跌彩色是 TE > 5% 的 warning；若要求严格黑白，可改为灰底 + ! 边框标记。
6. **C 页两模式切换不换 URL**：仅在页内切换（原型）；实施时建议 /dashboard?mode=quadrant|basket 或子路由。

## 12. 截图复现命令

桌面（A，1440×2600，等待局部 loading 完成）：

    "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,2600 --virtual-time-budget=7000 --screenshot=screenshot-desktop.png "file:///D:/balanced-portfolio/docs/design/2026-11-27-unified-redesign/variants/v2-vercel-mono/index.html"

移动端（390×2600）：Chrome 新版 headless 在 Windows 上对小于 500px 的窗口会强制最小布局宽度，因此改用 CDP Emulation.setDeviceMetricsOverride(width:390, mobile:true) 截取真实 390px 视口（任意 Puppeteer/Playwright 等价实现均可）。

B / C 屏把 URL 换成 …index.html#/b、#/c（C 篮子是页内 tab：可 #/c 后再点「一篮子资产」，或模拟点击 data-dash=basket）。

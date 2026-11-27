# Design System · Balanced Portfolio 2.0（2026-11）

> 基线：用户偏好 d1 / stockA / basketA / cryptoB 的紧凑数据工作台 + prologue.dev 的质感与动效。
> 原则：数据优先、局部 loading、克制动效、红涨绿跌、双主题、响应式、零外部依赖图表。

## 1. 色彩

### 浅色（默认）
| Token | 值 | 用途 |
|---|---|---|
| --bg | #f6f8fb | 页面背景 |
| --surface | #ffffff | 卡片/面板 |
| --surface-2 | #f2f6fa | 次级填充（segmented 底、表头） |
| --border | #e4e9f0 | 1px 分隔/边框 |
| --border-strong | #cbd5e1 | 强调分隔 |
| --text | #0f172a | 主文字 |
| --text-2 | #5b6b82 | 次级文字 |
| --text-3 | #8a99ad | 弱化/占位 |
| --accent | #0284c7 | 主色（sky） |
| --accent-strong | #0369a1 | 按下/深色文字 |
| --accent-wash | #e8f4fd | 选中底色 |
| --up | #dc2626 | 上涨（A股红） |
| --down | #16a34a | 下跌（A股绿） |
| --warning | #f59e0b | 预警/琥珀 |
| --violet | #8b5cf6 | 次要系列/品牌辅助 |
| --brand-gradient | linear-gradient(115deg,#c7d2fe,#bae6fd 45%,#fbcfe8) | 光晕/强调条，低饱和 |

### 暗色
| Token | 值 |
|---|---|
| --bg | #0b1220 |
| --surface | #111a2b |
| --surface-2 | #16213a |
| --border | #22304a |
| --text | #e6edf7；--text-2 #a6b4c9；--text-3 #6d7c93 |
| --accent | #38bdf8；--accent-strong #7dd3fc；--accent-wash #0c2a3d |
| --up | #f87171；--down #4ade80 |
| --warning | #fbbf24；--violet #a78bfa |

> 语义规则：涨跌只用 up/down；warning/destructive 不做涨跌；四象限色沿用：过热 warning / 滞胀 destructive / 复苏 success / 衰退 weak（弱化灰蓝）。

## 2. 字体与数字
- 字体栈：`Geist, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`。
- 数字：`font-variant-numeric: tabular-nums`；关键数字/价格/权重用 Geist Mono（无则 `ui-monospace, SFMono-Regular, Menlo`）。
- 字号阶梯：11px 标签/脚注 · 12px 次级 · 13px 正文 · 14px 强调正文 · 21-24px H1 · 27-32px 大数字（KPI 用 25-30px/650）。
- 行高：正文 1.55；数据表 1.4；中文标题 1.3。
- 字距：大标题 -0.02em，mono 数字 -0.01em。

## 3. 形状与层级
- 圆角三级 + pill：`--radius-control: 8px`（按钮/输入/segmented 内块）、`--radius-card: 14px`（卡片）、`--radius-panel: 18px`（弹层/modal）、`--radius-pill: 999px`（badge/chip/nav pill）。
- 阴影：`--shadow-card: 0 1px 2px rgb(15 23 42/.04), 0 8px 24px -16px rgb(15 23 42/.18)`；hover 抬升 + 柔和光晕；暗色下阴影更弱、靠边框分层。
- 布局：header 60px sticky（glass: backdrop-blur 12px + 76% 背景透明）；左栏 212px（桌面）→ 顶部 tabs（<1200px）；容器 max 1480px，padding 20-28px。
- 栅格：桌面 12 列，卡片间距 14-16px；页面 section 间距 20-24px。

## 4. 组件规范
- **按钮**：primary（sky 渐变或纯 sky，白字）、secondary（白底 1px 边框）、ghost（透明 hover 浅底）、icon（pill）。高度 32px（sm 28 / lg 36），focus-visible 2px accent ring。
- **Segmented / Tabs**：底 `--surface-2`，active 白底 + 阴影 + 600 字重；pill 导航用于页面级切换（prologue 风）。
- **卡片 Panel**：标题（13px/640）+ 副标题（11px 弱化）+ 右侧操作；卡片内部不重复大标题。
- **KPI/MetricCard**：标签 12px 弱化 → 数值 25-30px mono → 辅助行（分位/badge/迷你趋势）。
- **表格**：表头 11px 大写弱化、行 hover 浅底、数字右对齐 mono、首列左对齐；支持排序；移动端可横滚（不撑破布局）。
- **图表**：内联 SVG，坐标轴/网格极浅；色板 sky/amber/violet/rose；面积渐变 6-10%；分位带低透明度；tooltip 跟随鼠标、显示日期+多系列值；图例紧凑；暗色单独配色。禁止饼图表达时间序列。
- **Tooltip / Info**：`?` 圆形 16px，hover/focus 显示 title+公式/口径说明，支持触屏点击。
- **Badge/Pill**：低估/中性/高估（success/warning/destructive）、数据状态（dot + 文本）。
- **空态**：统一图标 + 一句说明 + 可选行动按钮；不显示空表格骨架。
- **Skeleton**：局部、尺寸与真实内容一致；shimmer 1.4s 循环；加载完成 opacity/translateY 150ms 淡入；页头、布局、导航永不 skeleton。

## 5. 动效
| Token | 值 |
|---|---|
| --dur-fast | 150ms |
| --dur-base | 200ms |
| --dur-enter | 300ms |
| --ease-out-expo | cubic-bezier(.16,1,.3,1) |
| --ease-out-soft | cubic-bezier(.22,.61,.36,1) |

- 入场：页面首屏区块 `reveal-rise`（opacity 0→1, translateY 8px→0, 300ms）依次 40ms stagger。
- 交互：按钮/卡片 hover 仅颜色/阴影/translateY(-1px)；segmented active 滑动 180ms；tab 内容切换 150ms 交叉淡入；禁止 layout shift。
- 数据刷新：旧值 → 新值 200ms 数字过渡/淡入；不整块闪烁。
- 尊重 `prefers-reduced-motion`：全部动画降为 0.01ms。
- 局部 loading 标准：卡片内容 skeleton + `aria-busy`；页面级路由切换可保留现有淡入，但**数据请求不允许全屏遮罩**。

## 6. 数据状态与全局更新日
- 组件 `DataFreshnessBadge`：绿点「数据更新至 2026-11-27」；hover/click 弹 panel：8 类数据各自的 as_of + 状态 + 缺口说明；未全量完成时琥珀点。
- 规则：`latest_complete_date = min(last_success_date of required datasets)`；`required = [a_stock, hk_stock, etf, fund_nav, cffex, index_quotes, index_valuation, mvi]`；理论最新交易日以 A 股收盘确认口径（15:10）为基准；fund 夜间更新、估值 21:00 后更新属于正常口径，需在 tooltip 说明“完成时间”。
- 后端：新公共端点 `GET /api/v1/market/data-freshness`（匿名、缓存 30-60s），由各 ETL/估值任务成功后写 `bp_data_freshness`（或复用 bp_etl_dataset_state + 估值/MVI state 记录）；页面 SSR/客户端读取，不实时聚合。

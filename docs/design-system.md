# Balanced Portfolio 设计系统

> 2026-09 全站 UI 现代化定稿。技术栈：Next.js 16 + React 19 + Tailwind CSS v4（CSS-first 配置，全部在 `web/app/globals.css`）+ Radix UI 原语 + ECharts。
> 风格参照：Next.js 官网 / OpenAI / shadcn 的现代扁平金融产品审美。

## 1. 颜色

### 主色（sky 系）

| Token | Light | Dark | 说明 |
|---|---|---|---|
| `--primary` | `#0284C7`（sky-600） | `#38BDF8`（sky-400） | 浅色用深一档保证白字对比度；暗色用亮一档配深色字 |
| `--primary-foreground` | `#FFFFFF` | `#082F49` | |
| `--ring` | sky-500/50 | sky-400/50 | 焦点环 |

### 涨跌色（绿涨红跌，全站唯一口径）

| Token | Light | Dark |
|---|---|---|
| `--up` | `#16A34A` | `#4ADE80` |
| `--down` | `#DC2626` | `#F87171` |

**规则**：`text-up`/`text-down`（及 `bg-`/`border-` 变体）**只用于方向性涨跌**（收益率、日涨跌、归因贡献、基差正负等）。禁止用于状态/象限/告警等非方向语义。

### 语义色

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `--success` | `#16A34A` | `#4ADE80` | 成功、正常状态（与 up 同值） |
| `--warning` | `#D97706` | `#FBBF24` | 警示：数据滞后、待重算、低持仓分位、节假日 |
| `--destructive` | `#E5484D` | 同 | 危险操作、滞胀象限、敲出状态 |

### 经济象限色（四象限统一映射，四处一致：首页/Builder/Dashboard/方法论文档）

| 象限 | 类 | 含义 |
|---|---|---|
| 过热 | `text-warning` | 通胀上行，琥珀 |
| 滞胀 | `text-destructive` | 最差象限，红 |
| 复苏 | `text-success` | 绿 |
| 衰退 | `text-weak` | 灰 |

## 2. 排版

- 根字号 16px；UI 主文本 `text-sm`（14px）；正文/文档 `text-base leading-relaxed`；辅助说明 `text-xs`。
- 行距：正文 1.6（`leading-6`/relaxed），标题 1.2，紧凑控件 1.25。
- 页面标题 `text-2xl font-semibold tracking-tight`；区块标题 `text-base/lg font-medium`。
- 标题紧排：`@layer base` 中 h1/h2 统一 `letter-spacing: -0.02em`（OpenAI/Next.js 风格；对中文视觉影响可忽略——letter-spacing 同样作用于汉字，-0.02em 在 16px 下约 0.3px）。页面标题带显式 `tracking-tight`（-0.025em）时，工具类优先级高于 base 层，实际生效 -0.025em（双层并存的现实口径）。
- 西文字体栈：Geist（`--font-geist-sans`，`next/font/google`，layout.tsx 注入）+ 中文回落 PingFang SC / Microsoft YaHei；等宽 `Geist Mono` + 系统等宽回落（`--font-sans`/`--font-mono` 见 globals.css `@theme inline`）。数字一律 `font-mono tabular-nums`（表格、指标、输入）。
- `@layer base` 不为裸元素设置字号（按钮等继承父级）；显式工具类控制各组件字号。

## 3. 间距与布局

- 间距栅格 4px：卡片内容 `p-5 sm:p-6`；区块间 `space-y-6`；栅格 `gap-4`/`gap-6`。
- 页面容器：全站主容器 `max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8`（navbar/footer/dashboard/列表页/看板页统一）；表单型窄栏 `max-w-4xl`（builder）；首页 hero `max-w-5xl`、cta `max-w-4xl` 为内容宽度例外；文档阅读栏 `max-w-6xl`（/methodology prose+TOC 阅读宽度，刻意不参与 1440 统一）。
- 圆角：卡片 `rounded-xl`、控件 `rounded-md`、徽章/胶囊 `rounded-full`、弹窗 `rounded-lg`。
- 阴影：全站扁平（见 §7 扁平化规范）——卡片零投影靠 border 分隔，弹层保留层级阴影；导航 `bg-background/80 backdrop-blur-md`。
- 按钮高度：默认 `h-9`，紧凑 `h-8`，大 `h-11`；可点目标 ≥32px。

## 4. 图表主题

一切图表颜色经 `web/lib/chart-theme.ts` 的 `getChartTheme(isDark)` 获取，**禁止在组件内写死 hex**：

- 通用：`text`/`subtext`/`axisLine`/`splitLine`/`tooltipBg`/`tooltipBorder`
- 涨跌：`up`/`down`（与 CSS token 同值）
- 分类序列：`palette`（8 色，sky 为首色）
- 专用：`cffex.{IF,IH,IC,IM}`、`crypto.{btc,sp500,nasdaq,gold,dxy}`、`rdBu`（相关性热力图发散色）、`otc.*`（路径示意图语义色）
- 面积填充：`fills.*`；透明度派生用 `withAlpha(hex, alpha)`
- 静态品牌资源（icon.tsx / opengraph-image.tsx）不走运行时主题。

## 5. 组件原语（`web/components/ui/`）

shadcn 风格 17 件：badge, button, calendar, card, checkbox, command, dialog, input, popover, progress, select, sheet, switch, table, tabs, tooltip, **alert-dialog**。反馈用 `sonner`（`<Toaster/>` 在根 layout）；**禁止** `window.alert/confirm/prompt`（已全部清除）。危险确认统一 AlertDialog + destructive Action。

## 6. 响应式断点

- 375（手机）：单列；表格容器横滚；弹窗 `calc(100vw-2rem)` 兜底。
- 768（平板）：双列栅格；弹窗 `sm:` 宽度。
- 1024+：dashboard TOC 显示（`hidden lg:block w-44`）；多列参数网格。
- 1440（桌面）：内容容器上限。
- 验收标准：三视口 × 明暗主题无内容截断、无意外横滚、文字不重叠（审计工具：chrome-devtools 三视口矩阵）。

## 7. 扁平化规范（2026-09 OpenAI/Next.js 风格打磨）

- 卡片**零投影**：`Card` 基类 = `rounded-xl border border-border bg-card text-card-foreground`，靠 border 分隔；业务卡片/统计块上的 `shadow-sm` 一律不放（已全站清理）。
- 弹层保留层级阴影（overlay 需要 elevation）：Dialog / AlertDialog / Sheet 内容 `shadow-lg`，Popover / Select 下拉 `shadow-md`，Toast 走 sonner 默认样式。
- 悬浮控件例外：确实悬浮于页面之上的元素（BackToTop 固定按钮）允许 `shadow-sm`。
- 控件选中态微抬升（tabs 激活页签等小控件内部 affordance）不在卡片扁平化范围内，保持原样。
- 圆角 token：`--radius: 0.625rem`（10px）；派生 `--radius-sm/md/lg/xl` 由 `calc(var(--radius) ±)` 自动跟随，勿单独写死。
- Geist 西文字体栈 + 中文回落（见 §2 排版），由 `next/font/google` 注入、`@theme inline` 的 `--font-sans`/`--font-mono` 接管。
- 标题紧排 `letter-spacing: -0.02em`（base 层 h1/h2）。
- **颜色方案不变**：sky 主色、涨跌/语义/象限色、`chart-theme.ts` 图表色一律未动；本次打磨只改字体/圆角/阴影/标题间距。

## 8. 维护规则

1. 新增颜色先进 `globals.css` token 再到 `@theme inline` 映射，组件只用语义类。
2. 新增图表颜色进 `chart-theme.ts`。
3. 新增原语遵循 shadcn 组合模式（Radix + cva + `cn()`）。
4. 交互反馈：轻提示用 toast，破坏性确认用 AlertDialog。

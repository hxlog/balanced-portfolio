# Next.js 16 性能审计与优化方案

- 审计日期：2026-11-14
- 审计范围：`web/`（Next.js 16 App Router）
- 环境事实：Next.js **16.2.10**（`package.json` 声明 `^16.2.9`）、React 19、`next build --turbopack`、`cacheComponents: true`、Tailwind v4、ECharts 6 + `echarts-for-react`、TanStack Query、`next-mdx-remote` / shiki / KaTeX。
- 约束：只读审计；未修改任何生产代码；本文件是唯一新增文件。

---

## 0. 测量口径与限制（先看这一节）

### 0.1 当前代码的 build 未能实测

`web/node_modules` 存在，已尝试：

```bash
cd web && npm run build
```

但当前会话是非交互子会话，权限系统拒绝执行需要写入/审批的构建命令，返回：

```text
This unattended Claude Code subagent cannot request human approval.
```

因此**当前代码的 First Load JS 无法在本会话实测**。下文所有体积数字来自仓库中遗留的 `.next` 构建产物（生成时间 **2026-07-26 22:43**），仅用于定位结构性问题与排序，不代表 2026-11-14 当前代码的精确值。正式落地前后必须重跑：

```bash
cd web && npm run build
```

并以 Next 构建输出的 `First Load JS` / `.next/server/app/*/page_client-reference-manifest.js` 为准。

### 0.2 遗留构建产物的核算方法

从 `.next/server/app/*/page_client-reference-manifest.js` 的 `entryJSFiles` 取出每个路由入口 chunk，再用文件字节数求和。共享入口由 `app/layout` 的入口 chunk + `build-manifest.json` 的 `rootMainFiles` 组成。关键 chunk：

| chunk | 原始字节 | 内容（已用 grep 确认） |
|---|---:|---|
| `04kkbz8sczl-m.js` | 1,130,938 | **ECharts 全量包**（`echarts` 字符串仅出现在此 chunk） |
| `28vy_joztsphg.js` | 178,304 | **motion/framer-motion** + Dashboard 用到的 API 常量 |
| `3m---puntogw9.js` | 53,965 | **qrcode**（`otpauth` / `QRCode`） |
| `0i6jd7m2f6n9p.js` | 142,210 | **cmdk + react-day-picker**（`cmdk` / `DayPicker`） |
| `0-x0p3jjazy2z.css` | 104,959 | Tailwind 全局 CSS |
| `3c0ats5vdyu15.css` | 24,382 | **KaTeX CSS**（393 个 `.katex` 选择器、20 个 `@font-face`） |

共享入口（每个路由都加载）：

```text
app/layout 入口：033z320odtbcc.js 28,982
              3_tc2vx9ye8cv.js 20,324
              0wa_5ydxn0z-b.js 28,341
              3m---puntogw9.js 53,965   ← qrcode
              0w_b10aecbnat.js 34,791
              = 166,403 bytes

rootMainFiles：310vm2bl3xxpt.js   5,364
              0no6_24z_u82i.js  36,727
              3rxl-jt3pdxgx.js 227,538
              0x1e73x9-szui.js 135,653
              1jy-jh5cq8cvg.js  66,440
              turbopack-*.js    10,613
              = 482,335 bytes

共享合计 ≈ 648,738 bytes（原始，未 gzip）
```

路由额外入口（在共享入口之外）：

| 路由 | 额外 chunk（原始字节） | 额外合计 | 结论 |
|---|---:|---:|---|
| `/` | 无 | 0 | 只付共享成本 |
| `/methodology` | `09tm_zrcxkv6t.js` 1,220 | ~1.2 KB | 服务端 MDX/Shiki/KaTeX 没有泄漏到客户端，**正面案例** |
| `/builder` | `3-rr4tmtc83-s.js` 32 KB + `1b3tg6vr1jaqy.js` 50,287 | ~82 KB | 无 ECharts |
| `/cffex` | `1x7s3_kgkms_x.js` 40,263 + `04kk...` 1,130,938 + `0f0xyb9nscugx.js` 50,287 | ~1.22 MB | ECharts 进入首屏 |
| `/crypto` | `41omne6gjcuus.js` 24,968 + `04kk...` 1,130,938 | ~1.16 MB | ECharts 进入首屏 |
| `/otc-derivatives-pricing` | `280p2n57fho6e.js` 10,453 + `0zkujl94pxgrc.js` 50,287 + `04kk...` 1,130,938 + `0i6j...` 142,210 | ~1.33 MB | ECharts + cmdk/RDP 进入首屏 |
| `/dashboard` | `0marz_56jr3im.js` 10,344 + `1b3tg6vr1jaqy.js` 50,287 + `04kk...` 1,130,938 + `28vy...` 178,304 | ~1.37 MB | ECharts + motion 进入首屏 |

> 原始字节不是 Next 的 `First Load JS` 口径（Next 通常以 gzip 报告）。这里只用于回答“谁在首屏、谁最大”。粗略按 3:1 gzip 估算，共享入口约 200–230 KB gzip，图表路由额外 350–450 KB gzip。正式目标见第 5 节。

### 0.3 审计方法

- 路由/客户端边界：逐个读 `web/app/**/page.tsx` 与对应 `*Client.tsx`。
- 重依赖：`package.json` + 全仓 import grep + 遗留构建 chunk 内容 grep。
- Cache Components：`web/lib/cached-data.ts`、`revalidateTag` 路由、Next 16 随包文档。
- 图表：`components/EChart.tsx`、四个图表页的 EChart 数量/option 依赖。
- 长列表：资产池、CFFEX、OTC 簿记表的渲染路径。
- 字体/静态资源：根 layout、`public/`、`next/image`/`<img>`。

---

## 1. 现状

### 1.1 路由级：Server / Client 边界

先澄清一个关键事实：**除两个 admin 页面外，所有 `page.tsx` 本身都是 Server Component**，没有因为顶层 import 客户端库而被迫整体 `"use client"`。问题在于：多数路由把**整页内容**委托给一个大 Client Component，导致“页面是 Server，但首屏实际是纯客户端渲染”。

| 路由 | `page.tsx` | 主内容 | 客户端重依赖 | 数据来源 | 评价 |
|---|---|---|---|---|---|
| `/` | Server | 静态 JSX + `HomeCryptoSection`（Server，`connection()`） | `lucide-react` | 无 | 结构正确；被根 layout 的 `fallback={null}` 拖累，见 P0-1 |
| `/dashboard` | Server | `DashboardClient`（3,140 行，Client） | ECharts、motion、TanStack Query、Radix | `initialDemo` prop + 客户端 fetch | 整页单一巨型客户端岛；SSR 数据被 effect 延迟使用 |
| `/builder` | Server | `BuilderClient`（1,316 行，Client） | Radix、lucide | `initialAssets`（Server 预取） | 结构基本正确；static shell 只有“加载中” |
| `/cffex` | Server | `CffexClient`（770 行，Client） | ECharts | 客户端 3 个 fetch | 无 SSR 数据；首屏空壳 |
| `/crypto` | Server | `CryptoClient`（479 行，Client） | ECharts | Server 预取后整包传 prop | 有大对象 prop + 顶层 `connection()` |
| `/otc-derivatives-pricing` | Server | `OtcPricingClient`（1,612 行，Client） | ECharts、cmdk、react-day-picker、MiniTradingCalendar | 客户端多请求 | 首屏最重；可拆分/懒加载空间最大 |
| `/methodology` | Server | `DocsLayout` + `DocsToc`（Client） | 仅 DocsToc | `renderDoc` + `compileMDX`（Server） | **最佳案例**：shiki/KaTeX/MDX 全在服务端，路由额外 JS 仅 1.2 KB |
| `/admin/assets` | **Client** | 整页 Client | Radix | 客户端 fetch | 278 行资产表一次渲染 |
| `/admin/users` | **Client** | 整页 Client | Radix | 客户端 fetch | 用户数少，影响低 |
| `/otc-pricing` | Server | `redirect()` | 无 | 无 | 正确 |

可以做 Server Component + 小客户端岛的地方：

- `/crypto`：标题、数据截至、6 资产价格卡、4 个相关性卡都可以在 Server 渲染；只有两个 ECharts + 窗口/方法 Tabs 需要 Client。
- `/cffex`：指数概览卡、合约表、统计表都可以 Server 渲染；只有品种筛选、Tooltip、图表需要 Client。
- `/dashboard`：指标卡、持仓表、调仓表、年度收益表可以 Server 渲染；只有图表、方法/基准切换、对话框需要 Client。
- `/builder`：页头/步骤条可以留在静态 shell；表单和资产选择器保持 Client。
- `/admin/assets`：可以改成 Server page + Client 表格岛；优先级低于公开页。

### 1.2 包体积：重依赖逐个判定

| 依赖 | 引入位置 | 是否首屏 | 现状 | 建议 |
|---|---|---|---|---|
| `echarts` | `components/EChart.tsx:3` `import * as echarts from "echarts"` | **是**：`/dashboard` `/cffex` `/crypto` `/otc` | 全量包 1.13 MB 原始字节进入 4 个路由首屏 | ① 改 `echarts/core` 按需注册；② `next/dynamic` + IntersectionObserver 懒加载。**收益最大** |
| `motion` | `app/dashboard/DashboardClient.tsx:8` | 仅 `/dashboard` | 178 KB chunk，只用于 1 个 pill + 1 个整页过渡 | 用 `tw-animate-css`/CSS 替代；同时去掉整页 `AnimatePresence` 重挂载 |
| `qrcode` | `components/Navbar.tsx:16` | **全站**（根 layout） | 54 KB chunk 进入每个路由 | 改为 2FA 对话框打开时 `await import("qrcode")`，或后端直接返回二维码 data URL |
| `cmdk` | `components/ui/command.tsx:4` → `OtcPricingClient.tsx:30-32` | 仅 `/otc` | 与 RDP 合计 142 KB chunk | 用简单过滤列表替代，或懒加载 `UnderlyingCombobox` |
| `react-day-picker` | `components/ui/calendar.tsx:5` → `OtcPricingClient.tsx:25` | 仅 `/otc` | 同上 | 用原生 `<input type="date">`（admin 已用）或懒加载 `DateField` |
| `next-mdx-remote` / `shiki` / `katex` | `app/methodology/page.tsx:4,7,10`、`components/mdx.tsx` | 否 | 服务端依赖，未进客户端 chunk | 保持；加 `server-only` 防误引 |
| `echarts-for-react` | 全仓无 import | 否 | 未使用依赖（651 KB 安装体积） | 删除 |
| `date-fns` | 全仓无 import | 否 | 未使用依赖（31 MB 安装体积） | 删除 |
| `lucide-react` | 多组件 | 是 | 按图标 tree-shake，正常 | 保持 |
| `@tanstack/react-query` | `app/providers.tsx:4` | **全站** | 只有 `/dashboard` 使用，却挂在根 Provider | 下沉到 dashboard，见 P1-4 |
| Radix UI | Navbar/表格/对话框 | 是 | 必要交互组件 | 2FA/登录对话框可进一步懒加载 |

### 1.3 Cache Components 现状

`next.config.mjs:5` 已开 `cacheComponents: true`。逐项核对：

| 函数/路由 | `use cache` | `cacheLife` | `cacheTag` | 失效方式 | 结论 |
|---|---|---|---|---|---|
| `getCachedAssets` | 是 | `hours` | `assets` | `POST /api/revalidate` → `revalidateTag("assets","hours")` | 用法基本正确；错误时缓存 `[]`，见 P1-3 |
| `getCachedDemoResult` | 是 | `minutes` | `demo-result` | **没有任何 revalidate 调用**；通用路由若传该 tag 会用 `"hours"` | profile 不匹配 + 错误时缓存 `null`，见 P1-3 |
| `getCachedCryptoCorrelation` | 是 | `hours` | `crypto` | `POST /api/revalidate/crypto` → `revalidateTag("crypto","hours")` | **正确**；失败 throw、不缓存 null |
| `methodology/page.tsx` | 是（页面级） | `max` | 无 | 无（内容随部署更新） | 可接受；若运营改 MDX 需重新部署 |
| `resolveDefaultPortfolioId` | 否 | — | — | — | 读 cookie，正确不加缓存；但被放在 page 顶层，见 P1-2 |

阻塞首屏的 Suspense 边界：

- **P0：根 layout 的 `<Suspense fallback={null}>` 包住了整个 `children`**（`web/app/layout.tsx:119-126`）。Next 16 官方文档明确写道：在根 layout 的 body 之上放一个空 fallback 的 Suspense，会让**整个应用退化为请求时渲染，没有静态 shell**（`node_modules/next/dist/docs/01-app/01-getting-started/08-caching.md:296-316`）。这比“缺少 Suspense”更严重：它把所有路由的 PPR 都关掉了。
- `/dashboard` 在 page 顶层 `await searchParams` 并读 cookie（`web/app/dashboard/page.tsx:27-38`），按 Cache Components 规则应放进局部 Suspense；目前被根 layout 的空 fallback“接住”，所以不报错，但整页阻塞。
- `/crypto` 在 page 顶层 `await connection()` 再 fetch（`web/app/crypto/page.tsx:25-35`），Suspense 在 fetch 之后才出现，fallback 实际上永远不会先出现；after removing root Suspense，这里会触发 “Uncached data or `connection()` was accessed outside of `<Suspense>`”。

关于 `instant = false`：Next 16.2.10 的导出名是 **`unstable_instant`**，不是 `instant`（`node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/02-route-segment-config/instant.md:15,58-62`）。`unstable_instant = false` 只是**豁免 instant navigation 校验**，不能替代局部 Suspense；不要把它当作修复 P0-1 的手段。唯一可能需要显式豁免的是 `/dashboard` 那种“为了 307 必须顶层阻塞”的 auth 重定向；推荐先用 `proxy.ts` 或登录时写入默认组合 cookie 来消除这个阻塞（见 3.2）。

### 1.4 数据获取现状

| 页面 | 请求模式 | 问题 |
|---|---|---|
| `/dashboard` | `initialDemo` Server 预取 → Client 后 effect 应用；结果/组合/资产由客户端 fetch | SSR 数据未进入首屏 HTML；首屏 `loading`；组合列表重复请求；资产 category 额外请求 |
| `/builder` | Server `getCachedAssets()` → Client `initialAssets` | 基本正确；编辑模式有 `getAssets` → `getPortfolio` 顺序 await 的可优化点 |
| `/cffex` | 客户端 `useEffect` 并行 3 个 fetch（spot/history/statistics） | 无 SSR 数据；LCP 依赖 hydration 后的网络 |
| `/crypto` | Server `getCachedCryptoCorrelation()` → 整包 prop | 大对象 RSC prop；`connection()` 在 Suspense 外 |
| `/otc` | 客户端 underlyings/spot/vol/calendar/deals 多请求 | 首屏依赖 hydration；可 Server 预取公开示例 |
| `/` | Server `HomeCryptoSection`（Suspense + `connection()` + `"use cache"`） | **正确范例** |
| `/methodology` | Server 文件读取 + MDX 编译 + `"use cache"` | **正确范例** |

Server→Client 大对象：

- `web/app/crypto/page.tsx:44` 把整个 `CryptoCorrelationResponse` 传给 `CryptoClient`。后端 `bp_api/crypto.py:114-146` 一次组装 27k 行相关系数：4 窗口 × 4 方法 × 4 资产对，约 10.8 万个数值，外加约 1.7k 日期、BTC 价格和 4 组滞后序列。原始 JSON 约 1 MB 量级，RSC/HTML 序列化后还会重复转义。
- `web/app/dashboard/page.tsx:40-47` 把完整 `BacktestResult` 传给 `DashboardClient`。`BacktestResult`（`web/lib/api.ts:466-494`）包含逐日 `nav`、全部 `rebalances` 的 target/prev/delta 权重、`corr` 矩阵、`attribution` 等，数百 KB 量级。
- `web/app/builder/page.tsx:27-29` 把完整 `Asset[]`（约 278 个键）传给 `BuilderClient`，约几十 KB；可接受，但可进一步瘦身。

### 1.5 图表现状

| 页面 | ECharts 数量 | 懒加载 | option memo | 备注 |
|---|---:|---|---|---|
| `/dashboard` | **最多 8 个**（`DashboardClient.tsx:1343,1467,1880,2955,2962,2977` + `RiskMatrixSection.tsx:460,489`；归因调仓图按数据条件渲染） | 无 | 部分：`pieOption`/`distOption` 有；`navOption`、`waterfallOption`、`assetBarOption`、`rebalanceBarOption` 无 | 全部挂载即 `echarts.init`；方法切换时整页 `AnimatePresence` 重挂载 |
| `/cffex` | 1 个（`CffexClient.tsx:644`） | 无 | 有 | 历史数据全量 `days=0` |
| `/crypto` | 2 个（`CryptoClient.tsx:432,468`） | 无 | 有，但 `corrColors` 每次渲染新建，导致 `chart1Option` 依赖失效 | 数据大 |
| `/otc` | 2 个（`OtcPricingClient.tsx:1112,1347`） | 无 | 有 | 下方波动率图在首屏外 |

`components/EChart.tsx` 本身：

- `useLayoutEffect` 内 `init` + `ResizeObserver` + `dispose`，cleanup 正确（`:21-36`），**没有 ResizeObserver 泄漏**，这是正面项。
- 每次 `option` 引用变化都会 `setOption`（`:39-43`）。如果上游 option 每次渲染新建，就会在无关状态变化时重复 `setOption`。
- 没有 `IntersectionObserver`，没有 `next/dynamic`，没有按需注册 ECharts 模块；全仓 `next/dynamic` 使用数为 **0**。
- `ResizeObserver` 回调直接 `chart.resize()`，没有 rAF 节流（P2）。
- `setOption(..., { notMerge: false })`：当 series 数量减少时可能残留旧 series，建议 `replaceMerge: ["series"]`（P2，正确性/性能都有益）。

### 1.6 长列表现状

| 页面/组件 | 一次渲染行数 | 是否虚拟化 | 结论 |
|---|---:|---|---|
| `/admin/assets` 资产表 | 最多约 278（`admin/assets/page.tsx:791`） | 否 | P1/P2：每行含 Checkbox + Switch + AlertDialog，DOM/事件成本高 |
| `/builder` 资产选择器 | 最多约 278（`builder/BuilderClient.tsx:1093`） | 否 | P1/P2：对话框打开时一次性挂载全部行 |
| `/otc` 簿记表 | `filteredDeals` 全量（`OtcPricingClient.tsx:1190`） | 否 | P2：随簿记数量增长 |
| `/cffex` 合约表 | ≤ 16（4 品种 × 4 合约类型，`CffexClient.tsx:560`） | 不需要 | 行数固定且小 |
| `/cffex` 统计表 | ≤ 4 品种 | 不需要 | 同上 |
| `/crypto` | 无长 DOM 列表；成本在 chart series 数组 | 不需要 | 真正的问题是 RSC payload 与图表数据量 |
| `/dashboard` 调仓/归因表 | 约几十到一百行 | 否 | 暂不紧急；若回测区间拉长可考虑 `content-visibility` |

### 1.7 字体与静态资源

- 字体：`web/app/layout.tsx:13-14` 使用 `next/font/google` 的 `Geist` / `Geist_Mono`，`subsets: ["latin"]`、`display: "swap"`、CSS 变量接入 `globals.css:101-102`；中文回落到 PingFang SC / Microsoft YaHei。**用法正确**。
- 图片：`web/public/` 只有 `robots.txt`，没有大图；没有 `next/image` 使用。唯一的 `<img>` 是 2FA 二维码 data URL（`Navbar.tsx:379,542`），已带 `width`/`height`，不适用 `next/image`。**没有图片优化问题**。
- `app/opengraph-image.tsx` / `app/icon.tsx` 用 `next/og` 生成，正常。
- 全局 CSS：根 layout 引入 `katex/dist/katex.min.css`（`layout.tsx:5`），但 KaTeX 只在 `/methodology` 使用。遗留构建中 KaTeX CSS 为 24,382 字节、393 个 `.katex` 规则、20 个 `@font-face`，每个路由都下载。P2。
- Umami：`layout.tsx:29-38,103-113` 的 recorder.js 注释标注约 190 KB，生产环境启用时每个页面加载；建议按需/延迟加载。P2。

---

## 2. 问题清单（按收益/成本排序）

> 排序原则：先修“影响所有路由且改动小”的，再修“单路由但收益大”的，最后修“局部体验/清洁度”的。每条的“预期收益”是估算区间，最终以重新 build 与 Lighthouse 为准。

### P0（不修会持续抵消所有优化）

#### P0-1 根 layout 用空 fallback Suspense 包住整个应用，PPR 全站失效

- 证据：`web/app/layout.tsx:119-126`
  ```tsx
  <Suspense fallback={null}>
    <AuthProvider>
      <Navbar />
      <main className="flex-1 flex flex-col min-w-0">{children}</main>
      <BackToTop />
      <Toaster />
    </AuthProvider>
  </Suspense>
  ```
- 依据：Next 16 随包文档 `.../08-caching.md:296-316` 明确说，根 layout body 之上的空 fallback Suspense 会让整个应用 defer 到 request time，没有静态 shell。
- 影响：所有路由 TTFB/FCP/LCP 都按动态渲染计；`/methodology` 本可全静态，也被拖成请求时渲染；首页 `HomeCryptoSection` 的局部 Suspense 也失去意义。
- 改法：删除根 layout 的 Suspense；改为每个动态路由自己的局部 Suspense（见 3.1/3.2/3.3）。Navbar 只用了 `usePathname`，不需要 Suspense。
- 预期：所有静态路由恢复 PPR；`/`、`/methodology`、`/builder` 的 TTFB 显著下降；为后续所有优化创造前提。
- 成本：低（删除 8 行 + 调整 2 个页面边界）。

#### P0-2 ECharts 全量包进入 4 个路由首屏

- 证据：`web/components/EChart.tsx:3` `import * as echarts from "echarts";`；遗留构建 chunk `04kkbz8sczl-m.js` = 1,130,938 字节，出现在 `/dashboard`、`/cffex`、`/crypto`、`/otc` 的 `entryJSFiles`。
- 影响：4 个核心页面的首屏 JS 增加约 1.13 MB 原始（约 330–380 KB gzip）；ECharts 初始化阻塞主线程。
- 改法：`echarts/core` + 按需注册 line/bar/pie/heatmap + CanvasRenderer；`EChart` 改为 IntersectionObserver 懒初始化；路由级 `next/dynamic` 包装。
- 预期：首屏移除约 1.1 MB 原始 / 约 330 KB gzip；TBT 显著下降；图表仍按需加载。
- 成本：中（一个共享组件 + 全局注册文件；4 个页面无需改业务代码）。

#### P0-3 qrcode 被根 Navbar 静态引入，每个路由都付 54 KB

- 证据：`web/components/Navbar.tsx:16` `import QRCode from "qrcode";`；使用点 `:330`、`:448`。遗留构建 `3m---puntogw9.js` = 53,965 字节，且位于 `app/layout` 入口。
- 影响：所有页面（包括首页、方法论）首屏都加载二维码库，只为了用户点开 2FA 对话框时生成图片。
- 改法：删除顶层 import；在两个 `useEffect` 内 `const QRCode = (await import("qrcode")).default;`。更彻底：让 FastAPI 的 `setup2fa` 直接返回二维码 data URL，前端零依赖。
- 预期：全站每路由减少约 54 KB 原始 / 约 18 KB gzip；根共享 chunk 变小。
- 成本：低（两处 import + 两处 await）。

#### P0-4 motion 只为 2 个动画引入 178 KB，并导致方法切换重挂载 8 个图表

- 证据：`web/app/dashboard/DashboardClient.tsx:8` `import { motion, AnimatePresence } from "motion/react";`；`:1132-1140` 方法 pill；`:1163-1171` `AnimatePresence` + `motion.div key={current}` 包住整个结果区，直到 `:1976`。遗留构建 `28vy_joztsphg.js` = 178,304 字节。
- 影响：
  1. `/dashboard` 首屏多 178 KB 原始 / 约 55 KB gzip；
  2. 切换优化方法时 `key={current}` 让整个结果子树卸载/重挂载，**最多 8 个 ECharts 全部 dispose + init**，且 `mode="wait"` 先等退出动画 0.25s；
  3. 用户交互（INP）明显变差。
- 改法：用已安装的 `tw-animate-css`（`globals.css:2`）或普通 CSS transition 替代；去掉整页 `key={current}`，只让数据原地更新；方法 pill 用 `bg-primary/10` 类即可。删除 `motion` 依赖。
- 预期：`/dashboard` 首屏减少约 178 KB 原始 / 约 55 KB gzip；方法切换不再重建 8 个图表；INP 改善。
- 成本：低（两处 JSX + 删依赖）。

#### P0-5 Dashboard 的 Server 预取数据没有进入首屏 HTML，首屏仍是“正在加载”

- 证据：`web/app/dashboard/DashboardClient.tsx:209` `const [loading, setLoading] = useState(true);`；`:233-291` 的 `useEffect` 才在 `:241-251` 使用 `initialDemo`；`:331-336` 在 loading 时返回“正在加载回测结果...”。page 在 `web/app/dashboard/page.tsx:40-47` 已经 Server 预取了 `initialDemo`。
- 影响：SSR 阶段 effect 不执行，所以即使 `initialDemo` 已就绪，首屏 HTML 仍是 loading 占位；用户要等 hydration + effect 后才看到内容。Server 预取的价值被完全浪费，LCP 变差。
- 改法：用 props 初始化 state（见 3.4），或在 React Query 中用 `initialData`；只在没有 initial data 时才走 effect。
- 预期：Demo/访客首屏直接输出净值、指标、持仓等真实内容；LCP 提升数百毫秒到 1 秒级（取决于网络）。
- 成本：低（改 4 个 `useState` 初始值 + 一个 early return）。

### P1（高收益，建议紧随 P0 落地）

#### P1-1 `/crypto` 顶层 `connection()` + 整包 RSC prop，首屏又慢又大

- 证据：`web/app/crypto/page.tsx:25` `await connection();`、`:30-35` fetch、`:36-45` 才进入 `<Suspense>`、`:44` 把整个 `data` 传给 `CryptoClient`；后端 `bp_api/crypto.py:114-146` 组装 27k 行相关系数。
- 影响：页面在返回任何 HTML 前等待后端；Suspense fallback 永远不会先出现；RSC/HTML 里携带约 10.8 万个相关系数 + 1.7k 日期 + 滞后序列，原始 JSON 约 1 MB 量级。
- 改法：① page 只返回静态标题/骨架，`connection()` + fetch 放进 Suspense 内的 async 子组件；② API 支持 `window`/`method` 参数，首屏只传 `3M/pearson`，Tab 切换时客户端按需请求并缓存；③ 6 资产价格卡/相关性卡改为 Server 渲染。
- 预期：`/crypto` TTFB/LCP 明显改善；RSC payload 从 MB 级降到百 KB 级；Tab 切换仍即时（React Query 缓存）。
- 成本：中（page 拆分 + API 参数 + CryptoClient 改数据源）。

#### P1-2 `/dashboard` 顶层 `searchParams`/cookie 阻塞，且与局部 Suspense 语义冲突

- 证据：`web/app/dashboard/page.tsx:27` `const { id } = await searchParams;`；`:33-38` `resolveDefaultPortfolioId()` + `redirect()`；`:46-49` 的 Suspense 只包住 Client，不包住上面的 await。
- 影响：违反 Cache Components “runtime data 应在 Suspense 内”的规则；目前靠根 layout 的空 fallback 兜底，导致整页动态。删除根 Suspense 后这里会直接报错。
- 改法：
  - 首选：把 `searchParams`/cookie 解析移进 Suspense 内的 `DashboardLoader`，接受“先静态 shell，再客户端 307/替换”的语义；或
  - 用 Next 16 的 `proxy.ts`（原 middleware）在请求入口按 cookie 做重定向，页面本身保持静态；或
  - 登录时写入 `bp_default_portfolio` cookie，页面只读 cookie，不请求 `/api/portfolios`。
  - 如果暂时必须保留顶层 307，则把它作为**唯一**显式豁免：`export const unstable_instant = false`（注意不是 `instant`），并在文档里注明原因；不要再用根 layout 空 Suspense 兜底。
- 预期：`/dashboard` 恢复静态 shell；避免“二次请求 + 闪烁”；为 P0-5 的 initial data 流打好基础。
- 成本：中（重排 page 结构或加 proxy）。

#### P1-3 缓存错误语义：assets 缓存空数组、demo 缓存 null、demo-result 失效 profile 不匹配

- 证据：
  - `web/lib/cached-data.ts:22-28` `getCachedAssets` 用 `safeServerFetch`，失败返回 `[]`，随后被 `"use cache"` + `cacheLife("hours")` 缓存 1 小时。
  - `web/lib/cached-data.ts:31-51` `getCachedDemoResult` 捕获所有错误返回 `null`，同样被 `cacheLife("minutes")` 缓存。
  - `web/lib/cached-data.ts:37` `cacheTag("demo-result")` + `cacheLife("minutes")`；`web/app/api/revalidate/route.ts:42` 对任意 tag 都调用 `revalidateTag(tag, "hours")`；`web/lib/revalidate-guard.ts:26` 允许超管传任意 tag。
- 影响：FastAPI 短暂不可用时，builder 会空一小时；dashboard demo 会显示失败数分钟；超管传 `demo-result` 时因 profile 不匹配而失效不到。
- 改法：① assets/demo 失败时 throw（或区分 404 与网络错误），不要把失败结果放进缓存；② 建立 `tag → profile` 映射，按 tag 选择 `"hours"` / `"minutes"`；③ 给 `demo-result` 增加明确的失效入口或缩短 TTL。
- 预期：消除“空资产库/假失败”缓存；缓存失效可预测；减少支持成本。
- 成本：低（3 个函数 + 1 个映射表）。

#### P1-4 TanStack Query Provider 挂在根 layout，只有 dashboard 使用

- 证据：`web/app/providers.tsx:4,8-22` 在根 Provider 创建 `QueryClient`；全仓只有 `web/app/dashboard/DashboardClient.tsx:95-96` 和 `web/lib/queries.ts` 使用 React Query。
- 影响：首页、方法论、CFFEX、Crypto、OTC 都白白加载 React Query 运行时。
- 改法：`providers.tsx` 只保留 `ThemeProvider`；新增 `web/app/dashboard/query-provider.tsx`（`"use client"`），只包 dashboard；或直接在 `DashboardClient` 外层用 `QueryClientProvider`。
- 预期：非 dashboard 路由共享 JS 减少约 20–40 KB 原始；根 chunk 更小。
- 成本：低。

#### P1-5 Dashboard 首屏挂载 8 个 ECharts，且多个 option 每次渲染新建

- 证据：8 个 EChart 位置见 1.5；`web/app/dashboard/DashboardClient.tsx:847-905` `navOption` 不是 `useMemo`；`:2762-2825` `waterfallOption`、`:2831-2874` `assetBarOption`、`:2878+` `rebalanceBarOption` 都在 `AttributionSection` 内直接新建；`web/app/crypto/CryptoClient.tsx:104-109` `corrColors` 每次渲染新建，且被 `chart1Option` 的依赖引用（`:237`）。
- 影响：首屏同时 init 8 个 canvas；任何无关状态变化（勾选“实际持仓”、打开计算器、切主题）都会让多个 EChart `setOption` 大数组。
- 改法：① `navOption` / 归因 option 全部 `useMemo`；② `corrColors` `useMemo`；③ 低于首屏的图表用 IntersectionObserver 延迟 init；④ 在 `EChart` 内加 option 引用/浅比较保护。
- 预期：首屏主线程时间下降；交互时不再重复 `setOption`；INP 改善。
- 成本：低-中（mostly memo + 懒加载包装）。

#### P1-6 OTC 首屏静态引入 cmdk + react-day-picker（142 KB chunk）

- 证据：`web/app/otc-derivatives-pricing/OtcPricingClient.tsx:25` 静态 import `Calendar`；`:30-32` 静态 import `Command*`；遗留构建 `0i6jd7m2f6n9p.js` = 142,210 字节，包含 `cmdk` 与 `DayPicker`。
- 影响：OTC 首屏多 142 KB 原始 / 约 45 KB gzip，但这两个库只在用户打开日期选择器/标的搜索框时才需要。
- 改法：把 `DateField`（Calendar + Popover）和 `UnderlyingCombobox`（Command + Popover）拆成独立 Client 组件，用 `next/dynamic` + `ssr:false` 懒加载；或直接用原生 `<input type="date">` + 简单过滤列表。
- 预期：OTC 首屏减少约 142 KB 原始 / 约 45 KB gzip；首次交互时再加载。
- 成本：中（拆两个组件）。

#### P1-7 278 行资产表/选择器一次性渲染

- 证据：`web/app/admin/assets/page.tsx:791` `filteredAssets.map(...)` 全量；`web/app/builder/BuilderClient.tsx:1093` `filtered.map(...)` 全量。
- 影响：管理端首屏和 builder 资产对话框有数百个 DOM 节点 + Radix 控件/AlertDialog，打开慢、滚动卡。
- 改法：管理端分页（50/页）或 `@tanstack/react-virtual`；builder picker 用虚拟列表或 `content-visibility: auto` + 分批渲染；OTC 簿记表同样分页。
- 预期：管理端/对话框首次渲染时间下降；DOM 节点数下降一个数量级。
- 成本：中（管理端可先分页，最低成本）。

#### P1-8 每次页面加载的 Auth 恢复请求 + dashboard 重复请求

- 证据：`web/lib/auth.tsx:106-130` 首屏无 token 时调用 `api.restoreSession()`（`/api/session` → FastAPI `/api/auth/me`）；`web/app/dashboard/DashboardClient.tsx:249,289,295` 在挂载时多次调用 `reloadPortfolios()`；`:617` `useAssets()` 额外拉 `/api/assets` 只为 category 映射。
- 影响：每个页面首屏多一个 auth 往返；dashboard 首屏多 2 个 `/api/portfolios` 和 1 个 `/api/assets`。
- 改法：① 在根 layout 读取 cookie claims，把初始 auth 状态作为 props 传给 `AuthProvider`，避免首屏 `/api/session`；② dashboard 用 `usePortfolios()` 去重，或只保留一个 effect；③ 从 Server 传入 `Record<symbol@source, category>` 的轻量映射，替代 `useAssets()`。
- 预期：首屏请求数减少 2–4 个；dashboard 首屏网络瀑布变短。
- 成本：中（auth 初始状态需要设计）。

### P2（清洁度/局部体验）

#### P2-1 全局加载 KaTeX CSS

- 证据：`web/app/layout.tsx:5` `import "katex/dist/katex.min.css";`；只有 `/methodology` 使用 KaTeX。
- 改法：移到 `web/app/methodology/layout.tsx`（新建）：
  ```tsx
  import "katex/dist/katex.min.css";
  export default function MethodologyLayout({ children }: { children: React.ReactNode }) {
    return children;
  }
  ```
  并从根 layout 删除。
- 预期：非方法论路由少 24 KB CSS + 20 个 `@font-face` 声明；首屏 CSS 更小。

#### P2-2 `lib/api.ts` 整个 `api` 对象进入根 bundle

- 证据：`web/lib/api.ts:726` `export const api = { ... }`；`web/components/Navbar.tsx:18` 和 `web/lib/auth.tsx:4` 从根布局链引入；遗留构建根 chunk `033z320odtbcc.js` 中可 grep 到 `OTC_PRODUCTS` / `METHOD_OPTIONS` 等常量。
- 影响：所有路由都携带全部 endpoint 方法与常量，tree shaking 无法裁剪对象属性。
- 改法：拆成 `lib/api-core.ts`（`req`、token、auth、portfolio 列表/详情）与领域模块（`api-otc.ts`、`api-admin.ts` 等）；Navbar/AuthProvider 只 import core。
- 预期：根共享 chunk 减少约 10–20 KB 原始；后续新页面不会继续膨胀根 bundle。

#### P2-3 CFFEX 无 Server 预取，三个客户端请求都在 hydration 后

- 证据：`web/app/cffex/page.tsx:18-29` 只包了一个同步 Client；`web/app/cffex/CffexClient.tsx:171,176,183` 三个 `useEffect` fetch。
- 改法：在 `cached-data.ts` 增加 `getCachedCffexSpot/History/Statistics`（`cacheLife("hours")` + `cacheTag("cffex")`），page 用 Suspense + async 子组件预取，把 initial data 传给 Client；统计周期切换再客户端 fetch。
- 预期：首屏直接输出指数卡/合约表；LCP 不再依赖 hydration 后网络。
- 成本：中。

#### P2-4 EChart 的 resize/setOption 细节

- 证据：`web/components/EChart.tsx:26` ResizeObserver 直接 `chart.resize()`；`:41` `notMerge: false`。
- 改法：用 rAF 合并 resize；option 变化时用 `replaceMerge: ["series"]` 防止旧 series 残留；在 option 为空时使用模块级 `EMPTY_OPTION` 常量，避免每次渲染新 `{}`。
- 预期：滚动/窗口缩放更顺滑；减少无意义 `setOption`。

#### P2-5 Builder / admin 的 static shell 不足

- 证据：`web/app/builder/page.tsx:19-29` 整个页面内容都在 Suspense fallback 里；`web/app/admin/assets/page.tsx:1`、`web/app/admin/users/page.tsx:1` 是整页 `"use client"`。
- 改法：builder 页头/步骤条放到 Suspense 外；admin 改 Server page + Client 表格岛（可与 P1-7 一起做）。
- 预期：首屏有意义的静态内容；导航感知更快。

#### P2-6 未使用依赖与构建清洁度

- 证据：`web/package.json:42` `echarts-for-react` 全仓无 import；`:40` `date-fns` 全仓无 import。
- 改法：从 `dependencies` 移除；`npm install --legacy-peer-deps` 后重新 build。
- 预期：安装体积/CI 时间下降；避免未来误引。

#### P2-7 其他小项

- `web/app/sitemap.ts:7` `lastModified: new Date()` 每次构建变化；可改为内容日期或固定日期，避免无意义的构建差异。
- `web/app/layout.tsx:29-38,103-113` Umami recorder 约 190 KB；生产环境仅在需要的路由/用户同意后加载。
- `web/components/ui/use-mobile.ts` SSR 返回 `false`，移动端 hydration 后切换，图表会重建一次；可接受，若追求极致可用 CSS 断点替代 JS 判断。
- `web/components/mdx.tsx`、`web/lib/cached-data.ts`、`web/lib/session-server.ts` 建议加 `import "server-only";`，防止未来被 Client 误引导致大包泄漏。
- `web/lib/auth.tsx:171-180` context value 每次渲染新建，可用 `useMemo` 包一下，减少消费者重渲染（低优先级）。

---

## 3. 逐条改法（含代码片段）

### 3.1 删除根 layout 的空 fallback Suspense

`web/app/layout.tsx`：

```tsx
// 删除：import { Suspense } from "react";
// 删除 119-126 行的 <Suspense fallback={null}> ... </Suspense>

<Providers>
  <AuthProvider>
    <Navbar />
    <main className="flex-1 flex flex-col min-w-0">{children}</main>
    <BackToTop />
    <Toaster />
  </AuthProvider>
  <footer>{/* ...保持原样... */}</footer>
</Providers>
```

删除后，所有依赖 runtime API 的路由必须自己提供局部 Suspense（3.2、3.3）。不要用 `fallback={null}` 再包回去；如果某个区块确实需要占位，给一个有尺寸的 skeleton，避免 CLS。

### 3.2 `/dashboard`：把动态解析放进局部 Suspense（或改用 proxy）

方案 A（推荐，恢复静态 shell）：

```tsx
// web/app/dashboard/page.tsx
import { Suspense } from "react";
import { redirect } from "next/navigation";
import { getCachedDemoResult, resolveDefaultPortfolioId } from "@/lib/cached-data";
import DashboardClient from "./DashboardClient";

type SearchParams = Promise<{ id?: string }>;

export default function DashboardPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardLoader searchParams={searchParams} />
    </Suspense>
  );
}

async function DashboardLoader({ searchParams }: { searchParams: SearchParams }) {
  const { id } = await searchParams;
  const portfolioId = id ? Number(id) : null;

  if (portfolioId == null || Number.isNaN(portfolioId)) {
    const defaultId = await resolveDefaultPortfolioId();
    if (defaultId != null) redirect(`/dashboard?id=${defaultId}`);
  }

  const initialDemo =
    portfolioId == null || Number.isNaN(portfolioId)
      ? await getCachedDemoResult()
      : null;

  return <DashboardClient initialDemo={initialDemo} />;
}
```

说明：`redirect()` 在 Suspense 内变成客户端重定向，不再保证 307。若 307 是硬需求，用 `proxy.ts`（Next 16 已把 middleware 重命名为 proxy）在请求入口根据 cookie 重定向，或登录时写入 `bp_default_portfolio` cookie；这样 page 本身无需读取 cookie/searchParams 之外的 runtime 数据。只有在无法迁移且明确接受整页动态时，才在 route 上写：

```tsx
// Next 16.2.10 的实际导出名是 unstable_instant，不是 instant
export const unstable_instant = false;
```

### 3.3 `/crypto`：静态 shell + 局部 Suspense + 瘦身 payload

页面拆成“静态外壳 + 动态数据”：

```tsx
// web/app/crypto/page.tsx
import { Suspense } from "react";
import { connection } from "next/server";
import { getCachedCryptoCorrelation } from "@/lib/cached-data";
import { CryptoClient } from "./CryptoClient";

export default function CryptoPage() {
  return (
    <div className="min-h-screen bg-background text-foreground pb-24">
      <CryptoHeader />{/* Server：标题、说明、数据截至占位 */}
      <Suspense fallback={<CryptoChartsSkeleton />}>
        <CryptoData />
      </Suspense>
    </div>
  );
}

async function CryptoData() {
  await connection(); // 放在 Suspense 内，避免 build 时访问 FastAPI
  const data = await getCachedCryptoCorrelation();
  return <CryptoClient data={data} />;
}
```

进一步瘦身（建议同一 PR 做）：

1. 后端 `GET /api/crypto/correlation` 增加 `window`（3M/6M/9M/12M）与 `method`（pearson/spearman/kendall/hoeffding）参数；默认 `3M/pearson`。
2. Server 首屏只取默认组合，传给 Client 的 `data` 只含：
   - `snapshot`、`meta`、`dates`、`btc_prices`；
   - `rolling["3M"]["pearson"]`；
   - `lagged_shifted["3M"]`。
3. Client 切 Tab 时用 React Query 请求新组合：

```tsx
const { data: rolling } = useQuery({
  queryKey: ["crypto", windowMonths, corrMethod],
  queryFn: () => api.getCryptoCorrelation({ window: windowMonths, method: corrMethod }),
  staleTime: 5 * 60_000,
  placeholderData: keepPreviousData,
});
```

预期 RSC payload 从 MB 级降到百 KB 级；首屏不再等全量数据。

### 3.4 Dashboard：用 props 初始化 state，消除首屏 loading

`web/app/dashboard/DashboardClient.tsx` 的 `DashboardInner`：

```tsx
const initial =
  initialDemo && pidNum == null && reloadToken === 0
    ? {
        m: initialDemo.method || "default",
        b: initialDemo.benchmark || DEFAULT_BENCHMARK_KEY,
      }
    : null;

const [cache, setCache] = useState<Record<string, BacktestResult>>(
  initial ? { [`${initial.m}::${initial.b}`]: initialDemo! } : {},
);
const [method, setMethod] = useState<string | null>(initial?.m ?? null);
const [benchmark, setBenchmark] = useState<string | null>(initial?.b ?? null);
const [loading, setLoading] = useState(!initial);

useEffect(() => {
  if (initial) {
    // 把 Server 数据同步进 React Query，供后续缓存/失效使用；不要在这里再 setLoading(true)
    queryClient.setQueryData(qk.result(null, initial.m, initial.b), initialDemo);
    reloadPortfolios();
    return;
  }
  // 原有 fetch 流程...
}, [idParam, reloadToken]);
```

更彻底的做法是改用 `useQuery` + `initialData`，让 React Query 统一管理：

```tsx
const { data, isPending } = useQuery({
  queryKey: qk.result(pidNum, method ?? undefined, benchmark ?? undefined),
  queryFn: () => fetcher(method ?? undefined, benchmark ?? undefined),
  initialData: pidNum == null && reloadToken === 0 ? initialDemo ?? undefined : undefined,
  placeholderData: keepPreviousData,
  staleTime: 60_000,
});
```

这样首屏 HTML 直接输出真实内容，方法切换也保留旧数据（`placeholderData`），不会闪回 loading。

### 3.5 ECharts 按需注册 + 懒加载

新增 `web/components/echarts-core.ts`：

```ts
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart, BarChart, PieChart, HeatmapChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, VisualMapComponent, MarkLineComponent,
  CanvasRenderer,
]);

export { echarts };
export type { EChartsType } from "echarts/core";
```

`web/components/EChart.tsx`：

```tsx
"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { echarts, type EChartsType } from "./echarts-core";

export function EChart({ option, style, priority = false }: {
  option: Record<string, unknown>;
  style?: CSSProperties;
  /** 首屏图表传 true：跳过 IntersectionObserver，立即 init */
  priority?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const [visible, setVisible] = useState(priority);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (priority || !ref.current) return;
    const el = ref.current;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [priority]);

  useLayoutEffect(() => {
    if (!visible || !ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => chart.resize());
    });
    ro.observe(ref.current);
    chart.resize();

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [visible]);

  useLayoutEffect(() => {
    chartRef.current?.setOption(option, {
      notMerge: false,
      lazyUpdate: true,
      replaceMerge: ["series"],
    });
  }, [option]);

  return <div ref={ref} style={style || { height: 300, width: "100%" }} />;
}
```

路由内包装（可选，确保 ECharts 运行时完全不进首屏）：

```tsx
// web/components/LazyEChart.tsx
"use client";
import dynamic from "next/dynamic";

export const LazyEChart = dynamic(
  () => import("./EChart").then((m) => m.EChart),
  {
    ssr: false,
    loading: () => <div className="h-[300px] w-full animate-pulse rounded-lg bg-bg-subtle" />,
  },
);
```

注意：`ssr: false` 只能出现在 Client Component 中；不要在 Server Component 里调用 `dynamic(..., { ssr:false })`。Turbopack 会把 `import()` 自动切成 async chunk。

迁移顺序：先改 `EChart` 内部按需注册（收益最大、业务无感），再给首屏外图表加 `priority={false}` / `LazyEChart`，首屏图表加 `priority` 并保留同步加载。

### 3.6 qrcode 动态 import

`web/components/Navbar.tsx`：

```tsx
// 删除第 16 行 import QRCode from "qrcode";

// Setup2faDialog 的 effect 内：
setSecret(res.secret);
try {
  const QRCode = (await import("qrcode")).default;
  setQr(await QRCode.toDataURL(res.otpauth_url, { margin: 1, width: 200 }));
} catch {
  /* 二维码生成失败时仍可手动输入密钥 */
}

// TwoFaManageDialog.startRebind 内同理。
```

如果后端愿意扩展，最彻底的是 `POST /api/auth/2fa/setup` 返回 `qr_data_url`，前端连动态 import 都省掉。

### 3.7 用 CSS 替代 motion，并避免图表重挂载

`web/app/dashboard/DashboardClient.tsx`：

```tsx
// 删除：import { motion, AnimatePresence } from "motion/react";

// 方法 pill：
{active && <span className="absolute inset-0 rounded-lg bg-primary/10 transition-all" />}

// 结果区：去掉 AnimatePresence 和 key={current}
<div className="space-y-6">
  {/* 只给头部/方法切换区做轻量动画，不要包住图表 */}
  <div className="animate-in fade-in slide-in-from-top-2 duration-200">
    {/* 头部、方法切换、参数卡 */}
  </div>
  {/* 图表和表格保持挂载，数据原地更新 */}
</div>
```

`tw-animate-css` 已在 `web/app/globals.css:2` 引入，`animate-in` / `fade-in` / `slide-in-from-top-2` 可直接用。删除 `package.json` 的 `motion` 依赖。

关键点：**不要给包含 ECharts 的整棵子树加 `key={current}`**。否则方法切换会 dispose + init 8 个图表，性能比动画本身更贵。

### 3.8 归因/图表 option memo 化

```tsx
// DashboardClient.tsx 的 navOption
const navOption = useMemo(() => ({
  tooltip: { /* ... */ },
  legend: { /* ... */ },
  xAxis: { /* ... */ },
  yAxis: { /* ... */ },
  series: [/* ... */],
}), [navDisplay, benchName, cardBg, fg, textCol, axisLineCol, splitLineCol, primary]);

// AttributionSection.tsx（当前在 DashboardClient 内）
const waterfallOption = useMemo(() => ({ /* ... */ }), [attribution, theme, benchName]);
const assetBarOption = useMemo(() => ({ /* ... */ }), [attribution, theme, isMobile]);
const rebalanceBarOption = useMemo(() => (rbs.length ? { /* ... */ } : null), [rbs, theme]);
```

`web/app/crypto/CryptoClient.tsx:104-109`：

```tsx
const corrColors = useMemo<Record<string, string>>(() => ({
  comex_gold: theme.crypto.gold,
  au0_gold: theme.crypto.btc,
  sp500: theme.crypto.sp500,
  nasdaq: theme.crypto.nasdaq,
}), [theme]);
```

`theme` 在 `getChartTheme` 中返回模块级单例 `light`/`dark`，身份稳定；上述 memo 依赖是有效的。

### 3.9 缓存错误语义与 tag/profile 映射

`web/lib/cached-data.ts`：

```ts
/** 资产清单：失败必须 throw，不能把 [] 缓存 1 小时。 */
export async function getCachedAssets(): Promise<Asset[]> {
  "use cache";
  cacheLife("hours");
  cacheTag("assets");
  const data = await serverFetch<{ assets: Asset[] }>("/api/assets");
  return data.assets;
}

/** Demo 结果：仅 404 视为“没有 demo”，网络/5xx 必须 throw。 */
export async function getCachedDemoResult(...): Promise<BacktestResult | null> {
  "use cache";
  cacheLife("minutes");
  cacheTag("demo-result");
  // ...
  const res = await fetch(`${apiBase()}/api/portfolios/demo${qs ? `?${qs}` : ""}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API /api/portfolios/demo: ${res.status}`);
  return res.json() as Promise<BacktestResult>;
}
```

`web/lib/revalidate-profiles.ts`（新增）：

```ts
export const TAG_PROFILE = {
  assets: "hours",
  crypto: "hours",
  "demo-result": "minutes",
} as const;

export function profileForTag(tag: string): string {
  return TAG_PROFILE[tag as keyof typeof TAG_PROFILE] ?? "hours";
}
```

`web/app/api/revalidate/route.ts:42`：

```ts
revalidateTag(tag, profileForTag(tag));
```

如果 `demo-result` 不打算提供手动失效，直接在 `revalidate-guard.ts` 里把超管可传 tag 收窄为 `assets`/`crypto`，避免 profile 不匹配的入口。

### 3.10 QueryClientProvider 下沉到 dashboard

`web/app/providers.tsx`：

```tsx
"use client";
import { ThemeProvider } from "next-themes";
import { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
      {children}
    </ThemeProvider>
  );
}
```

`web/app/dashboard/query-provider.tsx`：

```tsx
"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";

export function DashboardQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false } },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

在 `DashboardClient` 外层包一层即可。`lib/queries.ts` 只被 dashboard 使用，无需移动。

### 3.11 OTC 懒加载日期选择器与标的搜索

拆出 `web/app/otc-derivatives-pricing/DateField.tsx` 和 `UnderlyingCombobox.tsx`（都是 `"use client"`），在 `OtcPricingClient` 中：

```tsx
import dynamic from "next/dynamic";

const DateField = dynamic(() => import("./DateField").then((m) => m.DateField), {
  ssr: false,
  loading: () => <div className="h-9 w-full animate-pulse rounded-md bg-muted" />,
});
const UnderlyingCombobox = dynamic(
  () => import("./UnderlyingCombobox").then((m) => m.UnderlyingCombobox),
  { ssr: false, loading: () => <div className="h-9 w-full animate-pulse rounded-md bg-muted" /> },
);
```

如果不想拆文件，最低成本替代：

- 日期：`<input type="date" value={...} onChange={...} />`，admin 已有同样用法；
- 标的：受控 `<Input>` + 过滤后的 `<div role="listbox">`，去掉 cmdk。

预期：OTC 首屏不再包含 142 KB 的 `cmdk + react-day-picker`。

### 3.12 长列表分页/虚拟化

管理端最低成本做法（分页 50）：

```tsx
const PAGE_SIZE = 50;
const [page, setPage] = useState(0);
const pageRows = filteredAssets.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

// 表格只渲染 pageRows；筛选变化时 setPage(0)
```

如果希望保留全量滚动体验，再引入 `@tanstack/react-virtual`：

```tsx
const virtualizer = useVirtualizer({
  count: filteredAssets.length,
  getScrollElement: () => scrollRef.current,
  estimateSize: () => 48,
  overscan: 8,
});
```

最低成本的“视觉外延迟”方案（不引入依赖）：

```tsx
<TableRow className="[content-visibility:auto] [contain-intrinsic-size:48px]">
```

注意：`content-visibility` 只减少渲染成本，DOM 节点仍存在；278 行可接受，若未来上千行必须虚拟化/分页。

### 3.13 KaTeX CSS 按路由加载

新增 `web/app/methodology/layout.tsx`：

```tsx
import "katex/dist/katex.min.css";

export default function MethodologyLayout({ children }: { children: React.ReactNode }) {
  return children;
}
```

从 `web/app/layout.tsx:5` 删除 `import "katex/dist/katex.min.css";`。验证：`/methodology` 的公式样式不变，其他路由 CSS 请求少一个 chunk。

### 3.14 拆分 `lib/api.ts`，减少根 bundle

最小改动：

```ts
// web/lib/api-core.ts
export { getToken, setToken, shouldRefreshToken } from "./api";
export { api as coreApi } from "./api"; // 仅保留 auth/portfolio 列表等根布局需要的子集
```

更彻底：把 `api` 对象拆成命名导出，Navbar/AuthProvider 只 import：

```ts
import { login, logout, me, restoreSession, refreshSession, setup2fa, verify2fa, disable2fa } from "@/lib/api-auth";
```

并把 `OTC_PRODUCTS`、`METHOD_OPTIONS`、`BENCHMARK_OPTIONS` 等常量移到按路由 import 的模块。目标不是“消灭 api.ts”，而是让根布局链不再拉入全部 endpoint 字符串与 OTC 常量。

### 3.15 CFFEX Server 预取（可选但推荐）

`web/lib/cached-data.ts` 增加：

```ts
export async function getCachedCffexSpot() {
  "use cache";
  cacheLife("hours");
  cacheTag("cffex");
  return serverFetch<CffexSpotResponse>("/api/cffex/spot");
}

export async function getCachedCffexHistory() {
  "use cache";
  cacheLife("hours");
  cacheTag("cffex");
  return serverFetch<CffexHistoryResponse>("/api/cffex/history?days=0");
}
```

`web/app/cffex/page.tsx`：

```tsx
export default function CffexPage() {
  return (
    <Suspense fallback={<CffexSkeleton />}>
      <CffexLoader />
    </Suspense>
  );
}

async function CffexLoader() {
  const [spot, history] = await Promise.all([getCachedCffexSpot(), getCachedCffexHistory()]);
  return <CffexClient initialSpot={spot} initialHistory={history} />;
}
```

`CffexClient` 里用 `initialSpot`/`initialHistory` 作为 state 初始值，只在统计周期变化时请求 statistics。注意 `Promise.all` 并行，不要顺序 await。

---

## 4. 新增页面（估值详情 / 加密合约）接入时的性能规范

### 4.1 路由结构模板

```text
app/valuation/[symbol]/page.tsx          Server Component（默认导出同步，不 "use client"）
app/valuation/[symbol]/loading.tsx       与最终布局同尺寸的 skeleton（避免 CLS）
app/valuation/[symbol]/ValuationView.tsx Client island（仅图表/交互）
app/valuation/[symbol]/ValuationShell.tsx Server（标题、静态说明、SEO 文本）
```

```tsx
// page.tsx
import { Suspense } from "react";
import { ValuationShell } from "./ValuationShell";
import { ValuationContent } from "./ValuationContent";

export default function Page({ params }: { params: Promise<{ symbol: string }> }) {
  return (
    <ValuationShell>
      <Suspense fallback={<ValuationSkeleton />}>
        <ValuationContent params={params} />
      </Suspense>
    </ValuationShell>
  );
}

async function ValuationContent({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params; // runtime data 在 Suspense 内
  const data = await getCachedValuation(symbol); // 'use cache' + cacheLife + cacheTag
  return <ValuationView data={data} />;
}
```

### 4.2 五条强制规范（新增页面必须遵守）

1. **Server-first，禁止整页 `"use client"`**
   - `page.tsx` / `layout.tsx` 默认 Server；只有图表、表单、筛选器做成 Client island。
   - 根布局链（layout → Navbar/Auth）禁止新增任何 >20 KB 的静态 import。

2. **缓存必须声明生命周期与 tag，失效 profile 必须一致**
   - 参考数据：`'use cache'` + `cacheLife("hours"|"days")` + `cacheTag("valuation:<symbol>")`。
   - 用户私有数据：用参数传入 `use cache`，或 `use cache: private`，不要缓存跨用户响应。
   - 后端失效入口必须调用 `revalidateTag(tag, profileForTag(tag))`，并与 `cacheLife` 的 profile 完全一致。

3. **每个动态区块都有自己的 Suspense，禁止 `fallback={null}` 包全页**
   - `params` / `searchParams` / `cookies()` / `connection()` 必须在 Suspense 内。
   - 根 layout 不再放空 fallback Suspense；需要静态壳的页面自带 skeleton。
   - 若页面确实需要顶层 auth 重定向（307），单独评估 `proxy.ts` 或 `unstable_instant = false`，并在代码注释中说明。

4. **RSC prop 预算：首屏 ≤ 100 KB gzip，禁止传完整时间序列**
   - 首屏只传“可视区域需要”的切片：最新快照 + 默认窗口 + 前 N 个点（N ≤ 750）。
   - 全量序列按 `window`/`range`/`cursor` 由 Client 在 Tab/缩放时按需 fetch，React Query `staleTime` ≥ 5 分钟。
   - 表格数据必须分页（默认 50 行/页）；对象数组 > 500 条不得直接进 RSC props。

5. **图表/长列表必须懒加载并设预算**
   - ECharts 只允许 `echarts/core` + 按需注册；禁止 `import * as echarts from "echarts"`。
   - 首屏最多 2 个图表；其余用 IntersectionObserver + `next/dynamic`。
   - 所有 chart option `useMemo`；切换筛选/区间时保持图表实例，不卸载重挂载。
   - 客户端列表 > 100 行必须分页或虚拟化；> 500 行必须虚拟化。

### 4.3 新页面推荐的数据契约

以“估值详情”为例：

```ts
// 首屏只传这些
type ValuationInitial = {
  symbol: string;
  name: string;
  asOf: string;
  snapshot: { pe: number | null; pb: number | null; dividendYield: number | null };
  percentile: { pe: number | null; pb: number | null };
  series: { dates: string[]; pe: (number | null)[] }; // 默认 1Y，约 250 点
};
```

```ts
// 缩放/切区间时再取
GET /api/valuation/{symbol}/series?range=5Y&freq=weekly
```

“加密合约”页面同理：列表页 Server 分页渲染合约摘要；详情页只传当前合约的最近 N 个结算价 + 指标；历史全量序列走客户端按需请求。不要把 `bp_crypto_corr_daily` 那种“4 窗口 × 4 方法 × 4 资产对”的笛卡尔积一次性塞进 RSC prop。

### 4.4 新页面接入检查表

- [ ] `page.tsx` 没有 `"use client"`。
- [ ] 根 layout 链没有新增重依赖。
- [ ] 每个 runtime API 都在 Suspense 内。
- [ ] `use cache` 都有 `cacheLife` + `cacheTag`；失效 profile 有映射。
- [ ] 首屏 RSC props ≤ 100 KB gzip（用 `curl -H 'RSC: 1'` 或 Next DevTools 检查）。
- [ ] 首屏图表 ≤ 2 个；ECharts 按需注册。
- [ ] option `useMemo`；切换参数不卸载图表。
- [ ] 列表 > 100 行有分页/虚拟化。
- [ ] `web/app/<route>/loading.tsx` 的 skeleton 与最终布局同尺寸。
- [ ] `npm run build` 路由表没有超过预算；Lighthouse CI 通过。

---

## 5. 验收指标

### 5.1 First Load JS 预算（gzip）

> 当前精确值未能实测；以下为改造后的目标值。Next 构建输出中的 `First Load JS` 以 gzip 计，建议在 CI 里直接解析构建输出并设阈值。

| 路由 | 目标（gzip） | 说明 |
|---|---:|---|
| 共享 First Load JS | **≤ 170 KB** | 删除 qrcode / React Query / api 常量后的目标 |
| `/` | ≤ 180 KB | 静态首页 |
| `/methodology` | ≤ 190 KB | 仅 DocsToc 客户端岛 |
| `/builder` | ≤ 210 KB | 无 ECharts |
| `/dashboard` | ≤ 250 KB 初始；ECharts async chunk ≤ 150 KB | 8 图懒加载；motion 移除 |
| `/crypto` | ≤ 240 KB 初始；ECharts async chunk ≤ 150 KB | 首屏只 2 图 |
| `/cffex` | ≤ 240 KB 初始；ECharts async chunk ≤ 150 KB | 首屏 1 图 |
| `/otc-derivatives-pricing` | ≤ 280 KB 初始；ECharts async chunk ≤ 150 KB | cmdk/RDP 懒加载 |
| `/admin/*` | ≤ 220 KB | 管理端不追求极致 |

### 5.2 Core Web Vitals / Lighthouse

以移动端 p75、Slow 4G / 4× CPU 降速为准：

| 指标 | 目标 | 说明 |
|---|---:|---|
| LCP | ≤ 2.0s（首页/方法论 ≤ 1.5s） | 首屏主内容 |
| INP | ≤ 200ms（目标 ≤ 150ms） | 方法切换、图表交互、表格筛选 |
| CLS | ≤ 0.05 | skeleton 与最终布局同尺寸 |
| TTFB | ≤ 0.8s | 静态 shell 应从 CDN/Node 立即返回 |
| FCP | ≤ 1.5s | 首屏有意义的静态内容 |
| Lighthouse Performance | 移动端 ≥ 85；首页/方法论/桌面 ≥ 95 | |
| Lighthouse Best Practices | ≥ 95 | |
| Lighthouse SEO | ≥ 95 | |
| Lighthouse Accessibility | ≥ 90 | |

### 5.3 专项验收

- [ ] ECharts 运行时不在任何路由的初始 `entryJSFiles` 中；只有 `IntersectionObserver` 触发后才加载。
- [ ] `qrcode` 不在 `app/layout` 入口 chunk 中。
- [ ] `motion` 不在任何初始 chunk 中（或依赖已删除）。
- [ ] `cmdk` / `react-day-picker` 不在 `/otc` 初始 chunk 中。
- [ ] `/crypto` 的 RSC payload ≤ 200 KB gzip；Tab 切换不重新请求已缓存组合。
- [ ] Dashboard 方法切换：8 个 ECharts 不 dispose/init；只更新 option。
- [ ] `/dashboard` 首屏 HTML 直接包含净值/指标/持仓文本（不是“正在加载”）。
- [ ] `/methodology` 的 TTFB 接近静态资源；KaTeX CSS 只在该路由加载。
- [ ] 278 行资产表：首屏 DOM 行数 ≤ 50（分页）或虚拟列表实际渲染 ≤ 30。
- [ ] `npm run build` 通过；路由表与预算表对照无超限。

### 5.4 CI 建议

```bash
# 必须保留
cd web && npm run typecheck
cd web && npm test
cd web && npm run build

# 新增：构建产物预算检查（示例思路）
# 1) 解析 .next/server/app/*/page_client-reference-manifest.js 的 entryJSFiles
# 2) 对 chunk 文件 gzip 后求和
# 3) 与 5.1 的阈值比较，超限失败
```

Next 16 内置 bundle analyzer（Turbopack 兼容）：

```js
// next.config.mjs（仅分析时开启，不要常驻）
experimental: {
  bundleAnalyzer: process.env.ANALYZE === "true",
},
```

Lighthouse CI 至少覆盖：`/`、`/dashboard?id=<demo>`、`/crypto`、`/cffex`、`/otc-derivatives-pricing`、`/methodology`。

---

## 6. 已知 Next 16 注意事项（与本次审计直接相关）

1. **rewrites 与文件路由优先级**
   - `web/next.config.mjs:7-14` 的 `/api/:path*` 是 `afterFiles` rewrite；`web/app/api/session/**`、`web/app/api/revalidate/**` 是文件系统路由，会优先命中，不会转给 FastAPI。新增 `/api/*` Route Handler 时务必知道这一点，避免“以为会转给 FastAPI，实际被 Next 接管”。

2. **`cacheLife` profile 与 `revalidateTag` 第二参数必须一致**
   - `getCachedAssets`/`getCachedCryptoCorrelation` 用 `"hours"`，对应 `revalidateTag(..., "hours")`，正确。
   - `getCachedDemoResult` 用 `"minutes"`，但通用 revalidate 路由对所有 tag 用 `"hours"`，不一致；见 P1-3。
   - 推荐 `TAG_PROFILE` 映射，禁止在调用点硬编码 profile。

3. **Turbopack 下 dynamic import 的行为**
   - `import()` 会生成 async chunk；`next/dynamic` 在 Client Component 中可用，`ssr:false` 只能用于 Client Component。
   - Turbopack 的 tree shaking 不会裁剪 `import * as echarts` / `export const api = { ... }` 这种“运行时对象”的未使用属性；必须改 import 形态或拆模块。
   - 构建输出以 Turbopack 为准；不要再加 `webpack()` 配置（会被忽略）。

4. **`cacheComponents` 的静态 shell 规则**
   - 空 fallback Suspense 放在根 layout body 之上 = 全站放弃静态 shell（P0-1）。
   - runtime API（`searchParams`、`cookies()`、`headers()`、`connection()`）必须在 Suspense 内；否则 dev/build 会报 “Uncached data … outside of `<Suspense>`”。
   - `"use cache"` 内不能直接读 `cookies()`/`headers()`/`searchParams`；要在外层读取后作为参数传入（`resolveDefaultPortfolioId` 目前正确地没有加 `use cache`）。

5. **`instant` 命名**
   - Next 16.2.10 是 `unstable_instant`（draft API），不是 `instant`。如果团队要开启校验：
     ```tsx
     export const unstable_instant = { prefetch: "static" };
     ```
     如果某个路由确实要豁免：
     ```tsx
     export const unstable_instant = false;
     ```
     但不要把 `false` 当作 `fallback={null}` 的替代品；根因仍是动态数据没有局部 Suspense。

6. **`<Activity>` 与状态保留**
   - Next 16 Cache Components 默认用 React `<Activity>` 保留最近访问路由的状态（`.../cacheComponents.md:36-50`）。这意味着图表/表单在客户端导航返回时可能保持挂载；不要假设“离开页面就会卸载”，定时器/订阅要在 effect cleanup 中清理。

---

## 7. 建议实施顺序（按 ROI）

1. **PR 1（半天）**：删除根 layout 空 Suspense；qrcode 动态 import；移除 motion 并去掉整页 `key={current}`；KaTeX CSS 移到 methodology。
   - 预期：全站静态 shell 恢复；每路由 -54 KB；dashboard -178 KB；避免 8 图重挂载。
2. **PR 2（1–2 天）**：ECharts 按需注册 + EChart IntersectionObserver + 首屏外懒加载。
   - 预期：四个图表路由首屏 -1.1 MB 原始；TBT 显著下降。
3. **PR 3（1 天）**：Dashboard props 初始化 + useQuery/initialData + QueryClient 下沉 + 归因 option memo。
   - 预期：首屏真实内容；dashboard 共享 JS 下降；INP 改善。
4. **PR 4（1–2 天）**：`/crypto` 拆 Suspense + API window/method 参数 + 瘦身 RSC；`/dashboard` 动态解析迁 Suspense/proxy。
   - 预期：两个最重页面的 TTFB/RSC payload 大幅下降。
5. **PR 5（1 天）**：缓存错误语义 + TAG_PROFILE + CFFEX Server 预取。
6. **PR 6（按需）**：OTC 懒加载 cmdk/RDP；admin/builder 分页/虚拟化；api.ts 拆分；清理未使用依赖。

---

## 8. 附：本次未做的事项

- 没有修改任何生产代码；没有新增/删除依赖。
- 没有成功执行当前代码的 `npm run build`（非交互权限限制），因此没有当前 First Load JS 的精确值。
- 没有连数据库/后端实测 `/api/crypto/correlation` 的实际 JSON 字节数；payload 估算基于 `bp_api/crypto.py` 的 27k 行查询与数组结构。
- 没有实测 Lighthouse/Core Web Vitals；目标值需在部署预览环境用 Lighthouse CI / WebPageTest 校准。

建议在下一次可交互会话中先跑：

```bash
cd web && npm run build
```

把真实 `First Load JS` 填回 5.1 表格，再开始 PR 1。

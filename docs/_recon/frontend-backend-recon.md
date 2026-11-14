# Balanced Portfolio 前后端只读侦察报告

> 侦察日期：2026-11-14。仓库：`C:\Users\Xingyu Liu\Desktop\Balanced Portfolio`。
> 本报告只做只读分析，未修改任何生产代码。所有行号均基于当前工作树。
> 结论先行：本项目新增「预计算看板」的标准形态是 **ingest 预计算落表 → Redis/Next cache 失效 → API 只读表组装 → Next Server Component 预取 → Client Component 交互**，`/cffex` 与 `/crypto` 是两套可照抄的完整样例。

---

## A. 前端（`web/`）

### A1. 路由清单：Server / Client 与数据获取方式

Next.js 16 App Router。`web/next.config.mjs:5` 开启 `cacheComponents: true`；`web/next.config.mjs:7-14` 把 `/api/:path*` rewrite 到 FastAPI（默认 `http://localhost:8000`）。注意：**文件系统 Route Handler 优先于 rewrite**，所以 `web/app/api/**/route.ts` 不会转给 FastAPI（`web/app/api/revalidate/route.ts:10-13` 有注释）。

| 路由 | 页面文件 | Server/Client | 数据获取方式（代表证据） |
|---|---|---|---|
| `/` | `web/app/page.tsx` | Server（async） | 静态 JSX + PPR 动态洞；`HomeCryptoSection` 是 async Server Component，内部 `await connection()` + `getCachedCryptoCorrelation()`（`web/app/page.tsx:29-33,367-378`；`web/components/HomeCryptoSection.tsx:95-102`） |
| `/dashboard` | `web/app/dashboard/page.tsx` | Server（async）→ `DashboardClient` Client | 无 id 时服务端 `resolveDefaultPortfolioId()` + `redirect`，并预取 demo：`getCachedDemoResult()`（`web/app/dashboard/page.tsx:22-49`）。客户端结果走 TanStack Query `fetchResult()`（`web/app/dashboard/DashboardClient.tsx:202,229-231,233-291`；`web/lib/queries.ts:7-29`） |
| `/builder` | `web/app/builder/page.tsx` | Server → `BuilderClient` Client | `getCachedAssets()` 预取资产清单（`web/app/builder/page.tsx:19-30`）；编辑/复制时客户端 `api.getPortfolio()` / `api.getAssets()`（`web/app/builder/BuilderClient.tsx:182-193`） |
| `/cffex` | `web/app/cffex/page.tsx` | Server（sync）→ `CffexClient` Client | 页面不取数；Client 挂载后直接内联 `fetchJSON()` 调 `/api/cffex/spot`、`/history?days=0`、`/statistics?period=`（`web/app/cffex/CffexClient.tsx:129-187`） |
| `/crypto` | `web/app/crypto/page.tsx` | Server（async）→ `CryptoClient` Client | `await connection()` 后 `getCachedCryptoCorrelation()`（cacheTag `crypto`），失败 catch 为 null；Client 不再 fetch（`web/app/crypto/page.tsx:21-46`；`web/app/crypto/CryptoClient.tsx:87-90`） |
| `/methodology` | `web/app/methodology/page.tsx` | Server（async，`"use cache"`） | `cacheLife("max")` + next-mdx-remote 编译（`web/app/methodology/page.tsx:44-58`） |
| `/otc-derivatives-pricing` | `web/app/otc-derivatives-pricing/page.tsx` | Server（sync）→ `OtcPricingClient` Client | Client 通过 `api.*` 拉 underlyings/spot/vol/deals/tasks（`web/app/otc-derivatives-pricing/OtcPricingClient.tsx:181-222,313-319,385-387`） |
| `/otc-pricing` | `web/app/otc-pricing/page.tsx` | Server（sync） | 永久 `redirect("/otc-derivatives-pricing")`（第 1-6 行） |
| `/admin/assets` | `web/app/admin/assets/page.tsx` | Client（第 1 行 `"use client"`） | `useEffect` + `api.listAdminAssets()`/`api.listDataSources()`（第 148-160 行）；操作后 `api.revalidateAssets()`（第 310/323/400/423/452 行） |
| `/admin/users` | `web/app/admin/users/page.tsx` | Client（第 1 行） | `api.listUsers()`/`createUser`/`deleteUser`/`updateUser`（第 49-154 行） |
| `/admin/*` 布局 | `web/app/admin/layout.tsx` | Server | 仅包一层容器（第 9-11 行） |
| `web/app/api/session` | Route Handler | Server | POST 登录并写 httpOnly `bp_session`；GET 用 cookie 转 Bearer 调 `/api/auth/me`；DELETE 清 cookie（`web/app/api/session/route.ts:15-55`） |
| `web/app/api/session/refresh` | Route Handler | Server | 见 `web/app/api/session/refresh/route.ts`（文件存在；前端 `api.refreshSession` 调它，`web/lib/api.ts:928-934`） |
| `web/app/api/revalidate` | Route Handler | Server | admin 失效 `assets` tag（`web/app/api/revalidate/route.ts:17-43`） |
| `web/app/api/revalidate/crypto` | Route Handler | Server | 内部令牌失效 `crypto` tag（`web/app/api/revalidate/crypto/route.ts:14-29`） |
| `icon.tsx` / `opengraph-image.tsx` | 特殊 Metadata Route | Server | 静态品牌资源，不走运行时主题（`docs/design-system.md:68`） |
| `sitemap.ts` | 特殊 Route | Server | 路由数组在 `web/app/sitemap.ts:4` |

数据获取三种形态归纳：
1. **SSR + `use cache`**：`web/lib/cached-data.ts` 的 `serverFetch`/`safeServerFetch`（5-19），`getCachedAssets`（21-28）、`getCachedDemoResult`（30-51）、`getCachedCryptoCorrelation`（53-66）；`resolveDefaultPortfolioId` 不用 `"use cache"`，读 httpOnly cookie 并带 Bearer（68-97）。
2. **TanStack Query 客户端缓存**：全局 `QueryClient` 在 `web/app/providers.tsx:7-24`（staleTime 60s）；queryKey 工厂与 `fetchResult` 在 `web/lib/queries.ts:7-43`。
3. **Client 内联 fetch**：`/cffex` 的 `fetchJSON`（`CffexClient.tsx:132-139`）与 OTC 页的 `api.*`（`web/lib/api.ts` 封装）。

### A2. 组件复用清单

- **`web/components/EChart.tsx`**：`"use client"`；直接 `echarts.init()`，`useLayoutEffect` 内 init + `ResizeObserver.resize()` + dispose（21-36）；`option` 变化 `setOption(option,{notMerge:false,lazyUpdate:true})`（39-43）；默认 `height:300,width:100%`（45）。全站图表统一用它，不直接引 echarts-for-react。
- **`web/lib/chart-theme.ts`**：`ChartTheme` 接口（2-23）；`light`/`dark` 两套（25-65）；`getChartTheme(isDark: boolean): ChartTheme`（67-69）；`withAlpha(hex: string, alpha: number): string`（72-78）。图表颜色禁止在组件内写死 hex（`docs/design-system.md:61`）。
- **`web/components/Navbar.tsx`**：
  - `NAV_LINKS` 是 `as const` 的 `{ href, label }[]`，顺序：`/dashboard`、`/cffex`、`/crypto`、`/otc-derivatives-pricing`、`/methodology`（20-26）。
  - 条件追加：`canManageAssets` → `/admin/assets`；`isSuperAdmin` → `/admin/users`（54-62）。
  - 激活态 `navLinkClass`（28-36）；移动端 Sheet（72-100）+ 桌面横向 nav（107-117）；登录/注册/主题/账号菜单（120-159）；管理员未绑 TOTP 时强制弹窗（66-68）。
- **`web/components/ui/` 全部基础组件文件名**（18 个 `.tsx` + 2 个工具 `.ts`）：
  `alert-dialog.tsx`、`badge.tsx`、`button.tsx`、`calendar.tsx`、`card.tsx`、`checkbox.tsx`、`command.tsx`、`dialog.tsx`、`input.tsx`、`popover.tsx`、`progress.tsx`、`select.tsx`、`sheet.tsx`、`sonner.tsx`、`switch.tsx`、`table.tsx`、`tabs.tsx`、`tooltip.tsx`、`use-mobile.ts`、`utils.ts`。
  设计文档口径是「17 件 + sonner」（`docs/design-system.md:70-72`）；实际 `sonner.tsx` 也在 `ui/` 下。
- **`RiskMatrixSection`**（`web/components/RiskMatrixSection.tsx`）职责：展示相关性/年化协方差两张热力图；接收 `corr={labels,matrix,cov}`、组合资产、持仓权重、lookback、theme（227-241）。默认按「每类最高权重一只 + 全局权重降序」选最多 15 个资产（44-81,225,268-277）；支持全选/全不选/恢复默认（402-412）；用 `buildHeatmapOption` 生成 ECharts heatmap（130-223）；相关色 `[theme.up, theme.rdBu[4], theme.down]`（300-311）；协方差用 0 中心 RdBu 5 阶色（119-123,313-327）；全量矩阵通过 `ChartLightbox` 放大（329-369,442-449,470-477）。
- **`MiniTradingCalendar`**（`web/components/MiniTradingCalendar.tsx`）职责：紧凑 A 股月历；展示交易日/节假日/周末、今日 ring、期初「起」/到期「到」pin、存续期底色；年/月切换；数据来自 `api.otcCalendar(from,to)`（38-89）；日历网格渲染（91-177）；图例（178-185）。用于 OTC 定价页观察日选择，不是回测通用组件。

### A3. 设计系统要点

来源：`docs/design-system.md`（2026-09 定稿；技术栈 Next.js 16 + React 19 + Tailwind v4）。

- **主色（sky）**：`--primary` light `#0284C7`（sky-600）/ dark `#38BDF8`（sky-400）；`--primary-foreground` light `#FFFFFF` / dark `#082F49`（`docs/design-system.md:8-14`；token 在 `web/app/globals.css:16-17,50-51`）。
- **涨跌色（绿涨红跌，唯一口径）**：`--up` light `#16A34A` / dark `#4ADE80`；`--down` light `#DC2626` / dark `#F87171`（`docs/design-system.md:16-23`；`globals.css:35-36,65-66`）。`text-up`/`text-down` **只用于方向性涨跌**，禁止用于状态/象限/告警（`docs/design-system.md:23`）。
- **语义色**：`--success` 同 up；`--warning` light `#D97706` / dark `#FBBF24`；`--destructive` `#E5484D`（`docs/design-system.md:25-31`；`globals.css:37-38,67-68`）。
- **四象限色**：过热=`text-warning`；滞胀=`text-destructive`；复苏=`text-success`；衰退=`text-weak`（`docs/design-system.md:33-40`；`globals.css:22,85,96-99`）。
- **图表配色函数签名**：`getChartTheme(isDark: boolean): ChartTheme`；`withAlpha(hex: string, alpha: number): string`（`web/lib/chart-theme.ts:67-78`）。`ChartTheme` 含 `text/subtext/axisLine/splitLine/tooltipBg/tooltipBorder/up/down/palette/cffex/crypto/rdBu/otc/fills`（2-23）；light palette 8 色 sky 为首（30），dark palette（51）；`rdBu` 9 阶（33,54）。
- **Tailwind v4 配置位置**：CSS-first，全部在 `web/app/globals.css`（`@import "tailwindcss"` 1-3；`:root` token 7-40；`.dark` 42-69；`@theme inline` 映射 71-108）；`web/postcss.config.mjs` 只注册 `@tailwindcss/postcss`。
- **字体**：`next/font/google` 的 `Geist` + `Geist_Mono`，变量 `--font-geist-sans`/`--font-geist-mono`（`web/app/layout.tsx:13-14`）；`--font-sans` 中文回落 PingFang SC / Microsoft YaHei，`--font-mono` 等宽（`globals.css:101-102`）。根字号 16px（`globals.css:8`）；数字用 `font-mono tabular-nums`（`docs/design-system.md:48`）。
- **布局/扁平化**：主容器 `max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8`；卡片 `rounded-xl border` 零投影；圆角 token `--radius:0.625rem`（`docs/design-system.md:51-57,82-91`）。
- **交互规范**：toast 用 sonner；危险确认用 AlertDialog；禁止 `window.alert/confirm/prompt`（`docs/design-system.md:70-72,98`）。

### A4. `/crypto` 与 `/cffex` 页面结构、图表与交互（新看板照抄模板）

#### `/crypto`
文件：`web/app/crypto/page.tsx`（Server） + `web/app/crypto/CryptoClient.tsx`（Client）。SSR 数据来自 `getCachedCryptoCorrelation()`，Client 用 `initialData`，无客户端 fetch（`CryptoClient.tsx:83-90`）。

区块（从上到下）：
1. **页头**：标题/副标题 + 数据截至 Badge（ET/北京时间双时区）+「数据待齐 · 展示至 effective_td」琥珀 Badge（`CryptoClient.tsx:333-374`）。
2. **快照卡 5 张**：BTC/USD、DXY、COMEX 黄金、沪金 AU0、`{窗口} × {方法}` 窗口说明；`grid-cols-2 md:grid-cols-5`（383-401）。
3. **相关性摘要卡 4 张**：`BTC vs {label}`，显示当前窗口/方法下最后一个非空 R 值，颜色按 pair 从 `corrColors` 取；`grid-cols-2 md:grid-cols-4`（403-416）。
4. **Chart 1：BTC 滚动相关性**：line 多序列（左轴，`yAxis min=-1,max=1`）+ BTC 价格面积图（右轴）；`dataZoom` slider+inside；legend `type:"scroll"` 底部、默认只选 `COMEX黄金/纳斯达克100/BTC 价格 (USD)`；tooltip axis 自定义 HTML；高度 440（`CHART1_DEFAULT_ACTIVE` 44；chart option 131-237；卡片 418-439）。
5. **Chart 2：BTC vs DXY 远期走势**：BTC 左轴面积 + DXY 右轴 line，DXY 按 `lagHorizon` 向后平移；独立 4 个 Lag Tab；`dataZoom` slider+inside；高度 440（239-319；卡片 441-475）。

交互：
- 顶部 **滚动窗口 Tabs**：3M/6M/9M/12M（`WINDOWS` 23-28；state `windowMonths` 91；Tabs 355-363）。
- **相关方法 Tabs**：Pearson / Spearman / Kendall τ / Hoeffding D（`METHODS` 30-35；Tabs 364-371）。
- **滞后窗口 Tabs**：3M/6M/9M/12M（`LAG_OPTIONS` 37-42；Tabs 449-455）。
- 图例可点选隐藏/显示；`dataZoom` 可缩放/平移；图表主题随 `next-themes` 明暗切换（96-109）。
- 新看板可直接复用：`EChart`、`Card`、`Badge`、`Tabs`、`getChartTheme/withAlpha`、`ChartLightbox`。

#### `/cffex`
文件：`web/app/cffex/page.tsx`（Server，无数据） + `web/app/cffex/CffexClient.tsx`（Client，内联 fetch）。

区块：
1. **页头 + 状态 Badge**：已收盘 / 待现货对齐 / 数据时间（`CffexClient.tsx:353-383,416-435`）。
2. **指数概览 4 卡**：IF/IH/IC/IM 点位 + 涨跌幅；涨跌用 `text-up`/`text-down` + 箭头（445-480）。
3. **合约监控表**：品种过滤按钮（All 4 varieties，490-503）；表格列：品种/合约名/最新点位/持仓量/结算价/距交割/基差/升贴水率/年化升贴水率；带 Tooltip 解释基差/升贴水；条件着色（507-609；Tooltip 517-545；着色 591-603）。
4. **历史年化升贴水率走势**：4 条 line（IF/IH/IC/IM），可选右轴叠加某个指数价格（Select `indexSeries`，626-639）；`dataZoom` slider+inside，首次历史数据默认 `start:60`，后续保持用户 zoom（312-320）；legend scroll 底部；高度 440（244-351,614-651）。
5. **历史升贴水统计分位表**：周期 Tabs 3M/6M/1Y/3Y/5Y（120-126,658-666）；列：品种/综合年化升贴水率/当前分位值/10/30/50/70/90 分位/均值/±1σ/±2σ；分位值用「数值 + 横向进度条」展示，低分位用 `text-warning`（700-725）；表格 `overflow-x-auto` + sticky 首列（669-693）。

交互：
- 品种多选过滤（`toggleIndex` 190-194；`selectedIndices` 153）。
- 指数叠加 Select（`indexSeries` 156；628-638）。
- 统计周期 Tabs（`statPeriod` 154；658-666）。
- 图表 `dataZoom`、legend 点选、tooltip axis。
- 每个品种「主力合约」按持仓量最大识别并加粗（214-225,570）。
- 当前综合年化升贴水率 = `0.6 * 次月 + 0.4 * 当季`（386-400,623）。

**照抄模式给新看板的要点**：
1. 页面 = Server 壳 + Client 交互；数据要么 SSR `use cache`（crypto 模式，适合大 payload/首屏），要么 Client 挂载 fetch（cffex 模式，适合小 payload/需要 dataZoom 全量）。
2. 固定「页头 + 快照卡 + 图表卡 + 统计表」四段式；图表统一 440px 高 + `dataZoom` + legend scroll + 自定义 tooltip。
3. 筛选状态（窗口/方法/周期/品种）放 Client `useState`，数据切片用 `useMemo`，不要每次筛选重新请求（crypto 是全量预计算一次返回）。
4. `effective_td` / `is_synced` 在页头用 Badge 明示「数据待齐」。
5. 统计分位表若后端只给 mean/std 而没有原始值，CFFEX 当前是近似 `0.5 + z/6`（700-725）；新看板建议后端直接返回真实分位值，避免近似。

### A5. `web/lib/api.ts` 结构

| 区块 | 行号 | 内容 |
|---|---|---|
| 类型与常量 | 4-102 | `Quadrant`（4）、`QUADRANT_LABELS`（6-11）、`METHOD_OPTIONS`（13-34）、`METHOD_LABELS`（37-42）、`methodLabel`（44-46）、`BENCHMARK_OPTIONS`（49-58）、`BENCHMARK_COMPOSITION`（61-97）、默认值（99-102） |
| OTC 类型/常量 | 104-256 | `OtcProductType`、`OTC_PRODUCTS`（109-114）、`OTC_ENGINES`（116-129）、`OTC_VOL_QUICK`（131-137）、`OTC_DAYCOUNTS`（139-143）、`OTC_VOL_WINDOWS`（145）、`Otc*` 接口（151-256） |
| 资产/组合类型 | 258-537 | `ASSET_CATEGORY_OPTIONS`（258-264）、`ASSET_CATEGORY_LABELS`（266-268）、`ASSET_ADJUST_OPTIONS`（270-275）、`ADJUST_LABEL`（277-279）、`Asset`（281-299）、`NavPoint`（301-307）、`AssetCoverage`（313-324）、`Rebalance`（335-343）、`Holding`（345-353）、`Metrics`（364-393）、`PortfolioInfo`（395-422）、`Attribution`（424-455）、`BacktestResult`（466-494）、`CreatePortfolioInput`（496-511）、`CreatePortfolioResponse`（513-517）、`TaskStatus`（527-537） |
| 鉴权/管理类型 | 539-605 | `AuthProfile`（539-553）、`AdminUser`（555-564）、`DataSource`（566-577）、`AdminAsset`（579-605） |
| token 存取 | 607-633 | `TOKEN_KEY="bp_token"`（607）；`getToken`/`setToken` 用 localStorage（609-617）；`tokenExpiresInHours`（619-627）；`shouldRefreshToken`（629-633） |
| fetch 封装 | 635-724 | `sessionFetch`（635-654，无 Authorization）；`refreshSessionToken`（656-679）；`req`（681-712，自动加 Bearer + 401 刷新重试）；`q` 查询串（714-720）；`sleep`（722-724） |
| API 方法对象 | 726-999 | `api.getAssets`（727）… `api.revalidateAssets`（997-998）；组合/任务/OTC/admin/2FA 全部方法 |
| crypto 类型 | 1001-1049 | `CryptoPairData`（1004-1007）、`CryptoShiftedPrice`（1009-1013）、`CryptoSnapshot`（1015-1023）、`CryptoMeta`（1025-1039）、`CryptoCorrelationResponse`（1041-1049） |

**认证 header 怎么带**：
- 浏览器端 API 客户端 `req()` 从 `localStorage["bp_token"]` 取 token，加 `Authorization: Bearer <jwt>`（`web/lib/api.ts:681-690`）；401 时调 `/api/session/refresh` 换新 token 后重试一次（691-694; 656-679）。
- 登录走 Next Route Handler `POST /api/session`，由它写 httpOnly `bp_session` cookie（`web/app/api/session/route.ts:15-34`；`web/lib/session-server.ts:3,16-25,51-54`）。FastAPI **没有** `/api/session` 路由。
- 服务端 `resolveDefaultPortfolioId()` 从 cookie 读 token 并加 Bearer（`web/lib/cached-data.ts:75-82`）；`/api/revalidate` 同样从 cookie 读 token 转发 FastAPI 验身份（`web/app/api/revalidate/route.ts:18-37`）。
- 结论：**FastAPI 的鉴权只认 `Authorization: Bearer <JWT>`**（`bp_api/auth.py:426-469`）。Cookie 只是 Next 侧保存 JWT 的容器，不直接传给 FastAPI（除非服务端代码手动转发）。

### A6. 性能/缓存相关

- **rewrite**：`web/next.config.mjs:7-14` 仅一条 `/api/:path* → ${BP_API_BASE}/api/:path*`；`cacheComponents: true`（第 5 行）；`reactStrictMode: true`（第 6 行）。文件系统 Route Handler 优先，`/api/session*`、`/api/revalidate*` 不转 FastAPI。
- **`web/lib/cached-data.ts` 全部 cacheTag**：
  - `getCachedAssets`：`cacheLife("hours")` + `cacheTag("assets")`（21-28）。
  - `getCachedDemoResult`：`cacheLife("minutes")` + `cacheTag("demo-result")`（30-51）。
  - `getCachedCryptoCorrelation`：`cacheLife("hours")` + `cacheTag("crypto")`（53-66）；失败时 throw，不缓存 null（63-65）。
  - `resolveDefaultPortfolioId`：不加 `"use cache"`，`cache:"no-store"`（68-97）。
  - `methodology/page.tsx`：`cacheLife("max")`，无 cacheTag（44-46）。
- **revalidate Route Handler 的 token 校验方式**：
  - `POST /api/revalidate`（admin 资产）：读 httpOnly cookie `bp_session`（`route.ts:18-21`）→ 带 Bearer 调 FastAPI `/api/auth/me`（30-37）→ `canRevalidateTag(profile, tag)`（38-40；`web/lib/revalidate-guard.ts:20-28`：`role==="admin"` 任意 tag；`can_manage_assets` 只能 `assets`）→ `revalidateTag(tag, "hours")`（41-43）。第二参数必须与 `cacheLife("hours")` 一致。
  - `POST /api/revalidate/crypto`：`process.env.BP_INTERNAL_REVALIDATE_TOKEN` 必须存在（15-21）；`x-internal-token` 必须严格相等（22-25）；`revalidateTag("crypto","hours")`（26-28）。
  - 后端调用链：`bp_ingest/crypto_corr.py:306-318` 的 `_ping_crypto_revalidate()` 用 `BP_WEB_BASE` + `X-Internal-Token` POST；调用点 `bp_ingest/ingest.py:423-428`、`bp_ingest/scheduler.py:67-75`、`bp_api/workers/jobs.py:153-159`。
- **后端 Redis 缓存**：`bp_api/cache.py` 全降级（Redis 不可用即 miss，1-82）；crypto API key `crypto:correlation:v{version}`，TTL 3600（`bp_api/crypto.py:36-37,76-77,258-275`）；CFFEX spot 30min、history/stats 1h（`bp_api/cffex.py:53-61,392-401,482,541`）。

---

## B. 后端（`bp_api/`）

### B7. 路由注册模式与全部端点/鉴权

**注册模式**：
- `main.py:142` 创建 `app = FastAPI(...)`。
- `main.py:138-145` 在 `app` 创建后 import 三个自注册模块并调用 `register_routes(app)`：`cffex`（143）、`crypto`（144）、`otc_api`（145）。
- `main.py` 自身路由用 `@app.get/post/...` 直接装饰（156 起）。
- 自注册模块的 `register_routes(app)` 内部再写 `@app.get(...)`：`bp_api/cffex.py:549-588`、`bp_api/crypto.py:258-275`、`bp_api/otc_api.py:45-360`。
- 为避免 uvicorn reload loop，`bp_ingest` 的 import 放在函数内（`bp_api/crypto.py:15`、`bp_api/cffex.py:25,64-69`）。

**鉴权依赖**：`require_user`、`require_admin`（= `require_user`）、`require_super_admin`、`require_asset_editor`、`optional_user`，定义在 `bp_api/auth.py:426-469`。

#### 主 API（`bp_api/main.py`）

| Method | Path | 鉴权 | 行号 |
|---|---|---|---|
| GET | `/api/health` | 公开 | 156-158 |
| POST | `/api/auth/login` | 公开（内部限流+TOTP） | 164-168 |
| GET | `/api/auth/me` | `require_user` | 171-173 |
| POST | `/api/auth/refresh` | 手工 Bearer + `decode_token_with_grace` | 176-189 |
| POST | `/api/auth/2fa/setup` | `require_user` | 192-194 |
| POST | `/api/auth/2fa/verify` | `require_user` | 197-200 |
| POST | `/api/auth/2fa/disable` | `require_user` | 203-206 |
| GET | `/api/admin/users` | `require_super_admin` | 209-211 |
| POST | `/api/admin/users` | `require_super_admin` | 214-222 |
| DELETE | `/api/admin/users/{email}` | `require_super_admin` | 225-228 |
| PATCH | `/api/admin/users/{email}` | `require_super_admin` | 231-242 |
| POST | `/api/auth/change-password` | `require_admin`（= `require_user`） | 245-248 |
| GET | `/api/assets` | 公开 | 251-255 |
| POST | `/api/coverage/preview` | `require_user` | 258-283 |
| GET | `/api/portfolios` | `optional_user` | 286-289 |
| PATCH | `/api/portfolios/order` | `require_user`（demo 排序额外仅超管） | 292-313 |
| POST | `/api/portfolios` | `require_user` | 316-332 |
| PUT | `/api/portfolios/{portfolio_id}` | `require_user` | 335-359 |
| PATCH | `/api/portfolios/{portfolio_id}/meta` | `require_user` | 362-394 |
| GET | `/api/portfolios/demo` | 公开 | 397-416 |
| PATCH | `/api/portfolios/{portfolio_id}/demo` | `require_super_admin` | 419-431 |
| GET | `/api/portfolios/{portfolio_id}` | `optional_user` | 434-445 |
| GET | `/api/portfolios/{portfolio_id}/status` | **公开**（无依赖） | 448-456 |
| GET | `/api/portfolios/{portfolio_id}/result` | `optional_user` | 459-487 |
| POST | `/api/portfolios/{portfolio_id}/recompute` | `require_user` | 490-511 |
| POST | `/api/portfolios/{portfolio_id}/copy` | `require_user` | 514-535 |
| GET | `/api/tasks/{task_id}` | `require_user`（非 admin 校验 owner） | 538-547 |
| GET | `/api/admin/data-sources` | `require_asset_editor` | 550-553 |
| GET | `/api/admin/assets` | `require_asset_editor` | 556-559 |
| GET | `/api/admin/assets/portfolio-refs` | `require_asset_editor` | 562-569 |
| POST | `/api/admin/assets/refresh-status` | `require_super_admin` | 572-580 |
| POST | `/api/admin/assets/sync-all` | `require_super_admin` | 613-634 |
| POST | `/api/admin/portfolios/enqueue-ready` | `require_super_admin` | 637-648 |
| POST | `/api/admin/portfolios/recompute-all` | `require_super_admin` | 651-680 |
| POST | `/api/admin/assets` | `require_asset_editor` | 683-708 |
| PATCH | `/api/admin/assets/{source}/{symbol}` | `require_asset_editor` | 711-737 |
| DELETE | `/api/admin/assets/{source}/{symbol}` | `require_super_admin` | 740-745 |
| PATCH | `/api/admin/assets/{source}/{symbol}/selectable` | `require_super_admin` | 748-760 |
| POST | `/api/admin/assets/{source}/{symbol}/probe` | `require_asset_editor` | 763-831 |
| POST | `/api/admin/assets/{source}/{symbol}/sync` | `require_asset_editor` | 834-859 |
| DELETE | `/api/portfolios/{portfolio_id}` | `require_user` | 862-868 |

#### CFFEX（`bp_api/cffex.py`，全部公开）

| Method | Path | 鉴权 | 行号 |
|---|---|---|---|
| GET | `/api/cffex/spot` | 公开 | 551-557 |
| GET | `/api/cffex/history` | 公开 | 559-573 |
| GET | `/api/cffex/statistics` | 公开 | 575-588 |

#### Crypto（`bp_api/crypto.py`，公开）

| Method | Path | 鉴权 | 行号 |
|---|---|---|---|
| GET | `/api/crypto/correlation` | 公开 | 260-275 |

#### OTC（`bp_api/otc_api.py`）

| Method | Path | 鉴权 | 行号 |
|---|---|---|---|
| GET | `/api/otc/underlyings` | 公开 | 50-60 |
| GET | `/api/otc/calendar` | 公开 | 65-86 |
| POST | `/api/otc/calendar/refresh` | `require_super_admin` | 88-94 |
| POST | `/api/otc/observation-dates` | 公开 | 99-109 |
| GET | `/api/otc/volatility` | 公开 | 114-136 |
| GET | `/api/otc/vol-suggest` | 公开 | 138-147 |
| GET | `/api/otc/spot` | 公开 | 149-165 |
| GET | `/api/quotes/latest` | 公开 | 170-204 |
| POST | `/api/otc/price` | `require_user` | 209-228 |
| GET | `/api/otc/tasks/{task_id}` | `optional_user` | 230-239 |
| GET | `/api/otc/deals` | `optional_user` | 244-250 |
| PATCH | `/api/otc/deals/order` | `require_user` | 252-260 |
| GET | `/api/otc/deals/{deal_id}` | `optional_user` | 262-270 |
| POST | `/api/otc/deals` | `require_user` | 272-301 |
| PUT | `/api/otc/deals/{deal_id}` | `require_user` | 303-322 |
| DELETE | `/api/otc/deals/{deal_id}` | `require_user` | 324-331 |
| PATCH | `/api/otc/deals/{deal_id}/example` | `require_super_admin` | 333-340 |
| POST | `/api/otc/deals/{deal_id}/reprice` | `require_user` | 342-360 |

### B8. `auth.py`：JWT、TOTP、角色、密码哈希、API Token 插入点

- **密码哈希**：bcrypt `hashpw`/`checkpw`（`bp_api/auth.py:33-41`）。
- **JWT**：HS256；payload `sub`(email)、`uid`、`role`、`iat`、`exp`；`settings.jwt_expire_hours` 默认 168h（`auth.py:47-57`；`settings.py:50`）。校验 `decode_token`（60-65）；过期后 24h grace 内可换新 token，用于滑动续期（68-91,94-95）。`BP_JWT_SECRET` 必填且 ≥32 字符（`settings.py:36-40`）。
- **登录/TOTP 强制流程**：
  1. `authenticate_login` 先验密码；失败按 IP/email 用 Redis `incr_with_ttl` 限流（15 分钟窗口，IP>20 或 email>10 → 429）（`auth.py:222-239`）。
  2. 若 `bp_user.totp_enabled` 为真且没传 `otp_code`，返回 `{"requires_2fa": True, "email": ...}`（249-251）；传了则 `pyotp.TOTP(secret).verify(code, valid_window=1)`（252-253）；通过后 `create_token`（255）。
  3. 管理员未绑 TOTP：`auth_profile()` 返回 `must_setup_2fa = user.is_admin and not has_2fa`（`auth.py:472-489`）；前端 Navbar 检测到 `email && mustSetup2fa` 即强制弹 `Setup2faDialog` 且不可关闭（`web/components/Navbar.tsx:66-68,306-405`）。
  4. 绑定：`setup_totp` 生成新 secret，写 `totp_secret` 且 `totp_enabled=FALSE`（496-522）；`enable_totp` 校验 6 位码后置 TRUE（525-534）；管理员不可关闭（`disable_totp` 542-543）。
- **角色模型**：
  - 表：`bp_user`（`user_id/email/password_hash/role/status/portfolio_limit/totp_enabled/totp_secret/can_manage_assets`，`role IN ('user','admin')`，`status IN ('active','disabled')`）（`ddl/schema.sql:226-240`）；旧表 `bp_admin_user` 仍保留兼容（`schema.sql:213-219`）。
  - 超级管理员由 email 判定：`is_super_admin(email) == settings.admin_email`（`auth.py:98-99`；`settings.py:41`）。
  - `get_user_by_email`：优先 `bp_user`，active 才返回；`role = "admin" if is_super_admin(email) else row.role`；`is_admin = role=="admin"`；`can_manage_assets` 由 `bp_user.can_manage_assets` 或 admin（`auth.py:108-142`）。
  - 依赖：`optional_user`（436-440）、`require_user`（443-449）、`require_admin`（452-453，实际只是 require_user）、`require_super_admin`（456-461）、`require_asset_editor`（464-469，admin 或 can_manage_assets）。
- **有没有现成 API Token / API Key 机制？**：**没有**。全仓 grep `api_key|api_token|token_hash|X-API-Key` 零命中；现有只有 JWT Bearer（浏览器/Next 服务端）和内部 `BP_INTERNAL_REVALIDATE_TOKEN`（仅用于 Next revalidate，不是对外 API 鉴权，`web/app/api/revalidate/crypto/route.ts:14-28`）。
- **最自然的插入点**（对外 REST API）：
  1. **表**：`ddl/51_api_tokens.sql` 新建 `bp_api_token`：`token_id BIGINT PK`、`user_id BIGINT REFERENCES bp_user(user_id)`、`name TEXT`、`token_prefix TEXT UNIQUE`（前 8-12 字符，用于定位）、`token_hash TEXT`（`sha256(pepper + token)` 或 HMAC）、`scopes TEXT[]`、`expires_at TIMESTAMPTZ`、`revoked_at TIMESTAMPTZ`、`last_used_at TIMESTAMPTZ`、`created_at TIMESTAMPTZ`。只在创建时返回明文，库中存 hash。基线同步进 `ddl/schema.sql`（放在 `bp_user` 之后，约 245 行后）。
  2. **依赖函数**：在 `bp_api/auth.py:426-469` 附近新增 `require_api_token(authorization: str = Header(default=""), x_api_key: str = Header(default="")) -> UserContext`；解析 `Authorization: Bearer bp_...` 或 `X-API-Key`，按 prefix 查表、校验 hash/过期/撤销/scopes，更新 `last_used_at`，返回复用 `UserContext`（21-27）。**不要直接改 `require_user`**，否则会改变所有浏览器端点的 Bearer 语义。
  3. **路由**：新建 `bp_api/public_api.py`，`register_routes(app)` 下挂 `/api/v1/*`（如 `/api/v1/assets`、`/api/v1/portfolios/{id}/result`、`/api/v1/crypto/correlation`、`/api/v1/cffex/spot`），复用 `repositories` 只读函数；在 `bp_api/main.py:138-145` 注册。Token 管理端点 `/api/admin/api-tokens`（GET/POST/DELETE）用 `require_super_admin`，可放同一模块。
  4. **限流**：复用 `cache.incr_with_ttl`（`bp_api/cache.py:70-81`），按 token_id/IP 计数；参考登录限流 `auth.py:235-238`。
  5. **安全**：scope 最小化（如 `read:portfolio`、`read:market`）；可选 `BP_API_TOKEN_PEPPER` 进 `.env.example`；审计可写 `bp_audit_log`（`ddl/schema.sql:469-480`）。

### B9. `crypto.py` + `crypto_corr.py`：预计算表、响应结构、effective_td、失效链

#### 表 schema
- `bp_crypto_corr_daily`：`trade_date, pair_key, asset_a, asset_b, method, corr_3m, corr_6m, corr_9m, corr_12m, as_of_ts`；PK `(trade_date, pair_key, method)`；method check 4 种（`ddl/schema.sql:565-580`）。
- `bp_crypto_price_daily`：`trade_date, symbol, source, close, as_of_ts`；PK `(trade_date, symbol)`（583-592）。
- `bp_crypto_meta`：`key, value TEXT, updated_at`；PK `key`（594-599）。关键 key：`effective_td`、`latest_as_of`、`computed_at`、`btc_data_end`、`is_synced`、`version`（`bp_ingest/crypto_corr.py:488-521`）。
- 常量：`WINDOWS={"3M":63,"6M":126,"9M":189,"12M":252}`、`METHODS=["pearson","spearman","kendall","hoeffding"]`、`ASSET_PAIRS` 4 对、`ALL_PANEL_SYMBOLS` 6 资产（`crypto_corr.py:47-64`）。

#### 端点响应 JSON 样例结构
`GET /api/crypto/correlation` 返回（字段由 `bp_api/crypto.py:205-255` 组装；前端类型 `web/lib/api.ts:1041-1049`）：

```json
{
  "is_ready": true,
  "dates": ["2024-01-02", "2024-01-03", "..."],
  "btc_prices": [44100.2, 44320.5, null],
  "snapshot": {
    "btc": 97000.0,
    "dxy": 108.12,
    "comex_gold": 2650.3,
    "au0_gold": 620.5,
    "sp500": 5900.1,
    "nasdaq": 19500.2,
    "as_of": "2026-11-13T21:00:00+00:00"
  },
  "rolling": {
    "3M": {
      "pearson": {
        "comex_gold": {"label": "COMEX黄金", "correlation": [null, null, 0.1234]},
        "au0_gold":   {"label": "沪金AU0",   "correlation": [null, null, 0.2345]},
        "sp500":      {"label": "标普500",   "correlation": [null, null, 0.3456]},
        "nasdaq":     {"label": "纳斯达克100","correlation": [null, null, 0.4567]}
      },
      "spearman": {"comex_gold": {"label": "COMEX黄金", "correlation": []}, "...": "..."},
      "kendall":  {"...": "..."},
      "hoeffding":{"...": "..."}
    },
    "6M": {"pearson": {"...": "..."}},
    "9M": {"...": "..."},
    "12M": {"...": "..."}
  },
  "lagged_shifted": {
    "3M": {
      "dates": ["2024-01-02", "..."],
      "btc": [44100.2, "..."],
      "dxy": [101.2, "..."]
    },
    "6M": {"dates": [], "btc": [], "dxy": []},
    "9M": {"dates": [], "btc": [], "dxy": []},
    "12M": {"dates": [], "btc": [], "dxy": []}
  },
  "meta": {
    "is_ready": true,
    "is_synced": true,
    "computed_at": "2026-11-14T05:30:00+00:00",
    "btc_data_end": "2026-11-13",
    "effective_td": "2026-11-13",
    "as_of": "2026-11-13T21:00:00+00:00",
    "as_of_et": "2026-11-13 16:00 ET",
    "as_of_cn": "2026-11-14 05:00 北京时间",
    "window_sizes": {"3M": 63, "6M": 126, "9M": 189, "12M": 252},
    "methods": ["pearson", "spearman", "kendall", "hoeffding"],
    "assets": {
      "comex_gold": "COMEX黄金",
      "au0_gold": "沪金AU0",
      "sp500": "标普500",
      "nasdaq": "纳斯达克100"
    },
    "calendar": "NYSE (标普500 交易日)",
    "version": 42
  }
}
```

注意：`rolling[win][method][pair_key]` 的 `correlation` 数组与顶层 `dates` **一一对齐**（`bp_api/crypto.py:113-146`；前端直接用 `data.dates`，`CryptoClient.tsx:136-158`）。`lagged_shifted` 是 BTC[t] vs DXY[t+N] 的切片，每档独立 dates（`crypto.py:164-194`）。`snapshot` 额外补 `as_of`（`crypto.py:226`）。

#### effective_td 逻辑
- 计算入口 `compute_and_store_crypto_corr`（`crypto_corr.py:325-526`）：每次调用**全量重算** 7 年序列（`trade_dates`/`full` 只是预留，不改变语义，333-336）。
- 6 资产收盘加载（`_load_close`，71-111）；S&P500/纳斯达克用 `usd_native=True` 把 CNY 折算价按 `fx_rate` 还原成美元（77-107）——`/crypto` 与组合回测的 CNY 口径是两条链路。
- NYSE 日历 = 标普500 交易日（362-367）。
- `symbols_by_date` 只统计**非 NaN** 收盘日（373-377），避免 interp/ffill 假日被误判齐全。
- `max_confirmed`：今天 NYSE 收盘确认则今天，否则昨天（379-380）；`pick_effective_trade_date` 找最近「6 资产齐全且 ≤ max_confirmed」的 NYSE 日（207-225,385-388）。
- `is_synced = effective_td == max_candidate`（390-399）；无完整日则返回 `stats` 不落库（400-405）。
- 截断输出到 `effective_td`，并 DELETE 旧 tail（407-418）。
- CFFEX 镜像逻辑：`bp_api/cffex.py:81-105` 的 `pick_effective_trade_date` 要求 4 期货品种 + 4 挂钩指数同日齐全；`_index_closes_post_confirmed` 112-151 再用原始表 `updated_at >= close_confirm_deadline` 防止盘中脏价；snapshot 构建 154-385。

#### 缓存失效链
1. **写库**：`bp_ingest/crypto_corr.py:compute_and_store_crypto_corr` → `bp_crypto_corr_daily` / `bp_crypto_price_daily` / `bp_crypto_meta`（444-521）。
2. **Redis**：`bp_api/crypto.py:70-73 invalidate_crypto_cache()` → `cache.delete_pattern("crypto:correlation:*")`（36-37,70-73）。
3. **Next SSR**：`_ping_crypto_revalidate()`（`crypto_corr.py:306-318`）POST `${BP_WEB_BASE}/api/revalidate/crypto`，header `X-Internal-Token: BP_INTERNAL_REVALIDATE_TOKEN`。
4. **Next Route**：`web/app/api/revalidate/crypto/route.ts:14-29` 校验内部令牌 → `revalidateTag("crypto","hours")`；必须与 `getCachedCryptoCorrelation` 的 `cacheLife("hours")`/`cacheTag("crypto")` 一致（`web/lib/cached-data.ts:59-65`）。
5. **API 读缓存**：`bp_api/crypto.py:258-275` 读 `bp_crypto_meta.version` → `crypto:correlation:v{version}` Redis（TTL 3600）→ miss 才 `_build_payload()` 只读三张表；请求路径永不计算。
6. **触发点**：ingest 钩子 `bp_ingest/ingest.py:407-434`；APScheduler `bp_ingest/scheduler.py:58-80,126-143`；Celery `bp_api/workers/jobs.py:144-164` + `workers/celery_app.py:60-65`。
7. **CFFEX 对照**：`invalidate_cffex_spot_cache()` 删 `cffex:spot*`、`cffex:history:*`、`cffex:stats:*`（`cffex.py:72-78`）；调用点 `bp_ingest/cffex.py:760-795`、`bp_ingest/ingest.py:377-378`；CFFEX 无 Next cacheTag（Client 直接 fetch），所以只需 Redis 失效。

### B10. `quant/optimizer.py` + `backtest.py`：方法、象限、payload、加入「一篮子」

#### 四种优化方法入口/签名
- 回测总入口：`run_backtest(prices, benchmark, quadrant_assets, method="quadrant_inner_sharpe_outer_rp", ratio="sharpe", lookback=156, min_window=60, max_weight=None, rebalance_band=0.05, risk_free=0.0, fee_rate=0.0, slippage_rate=0.0, stamp_duty_rate=0.0, trading_days=244, user_start=None, progress_cb=None) -> BacktestResult`（`bp_api/quant/backtest.py:79-96`）。
- 优化分派：`optimize(returns, quadrant_assets=None, method="quadrant_inner_sharpe_outer_rp", ratio="sharpe", max_weight=None, risk_free=0.0, trading_days=244, *, cov=None, mean=None, x0=None) -> tuple[pd.Series, Optional[dict[str,float]]]`（`optimizer.py:348-360`）。
  - `all_risk_parity` → `risk_parity_weights(cov_m, max_weight)`（380-381）。
  - `all_max_sharpe` → `max_ratio_weights(returns, ratio, rf_daily, max_weight, cov=cov_m, mean=mean_v, x0=...)`（383-390）。
  - `sharpe_sq_risk_budget` → `_asset_ratio(returns, ratio, rf_daily)` 后 `risk_budget_ccd(cov_m, budgets, max_weight)`（392-397）。
  - `quadrant_inner_sharpe_outer_rp` → 每个象限内 `max_ratio_weights` 得 `v_q`，象限收益序列再做 `risk_parity_weights` 得 `u_q`，最终 `w_i = u_q * v_q,i`（399-439）。
- 底层函数：
  - `risk_budget_ccd(cov, budgets, max_weight=None, max_iter=500, tol=1e-10) -> np.ndarray`（168-208，Spinu CCD）。
  - `risk_parity_weights(cov, max_weight=None) -> np.ndarray`（211-216）。
  - `risk_budget_weights(cov, budgets, max_weight=None)`（219-223，兼容封装）。
  - `max_ratio_weights(returns, ratio, rf_daily, max_weight=None, *, cov=None, mean=None, x0=None) -> np.ndarray`（229-281，SLSQP + 热启动；失败回退逆波动率）。
  - `_regularize_cov`（39-71）、`_regularize_mean`（77-93）、`_apply_max_weight`（294-314）。
- 四种方法清单在后端注册表：`repositories.BACKTEST_METHODS`（`bp_api/repositories.py:67-72`）；进度标签 `METHOD_LABELS_CN`（75-80）；`TASK_TOTAL_STEPS = 4*100+2`（82-83，新增第 5 种方法必须改这里）。

#### 四象限怎么表达
- **不是 `category`**。象限在 `bp_portfolio_asset.quadrant`：`TEXT NOT NULL`，check `('overheat','stagflation','recovery','recession')`，且 PK 是 `(portfolio_id,symbol,source,quadrant)`（`ddl/schema.sql:298-308`）——所以同一资产可同时放入多个象限（`optimizer.build_quadrant_assets` 文档 335-345）。
- API 请求体：`AssetIn.quadrant` 必填（`bp_api/schemas.py:30-34`；`assets: list[AssetIn]` 在 54）。
- 前端：`Quadrant = "overheat"|"stagflation"|"recovery"|"recession"`（`web/lib/api.ts:4`）；`QUADRANT_LABELS`（6-11）；`PortfolioInfo.assets[].quadrant`（421）；Builder 的 `QUADRANT_ORDER`/颜色/短名（`web/app/builder/BuilderClient.tsx:36-58`），payload 组装在 283-341，编辑回填 211-214。
- `category` 是资产类别（index/etf/commodity/bond），来自 `bp_index_config.category`（`ddl/schema.sql:110-129`）与 `web/lib/api.ts:258-268`；**不参与象限分组**。

#### 组合参数 payload 完整字段（`schemas.py`）
`PortfolioPayloadBase`（`bp_api/schemas.py:37-54`）：

| 字段 | 类型/默认 | 行号 |
|---|---|---|
| `name` | str，默认「我的组合」 | 38 |
| `description` | str，默认「组合描述」 | 39 |
| `method` | str，默认 `quadrant_inner_sharpe_outer_rp` | 40 |
| `ratio` | str，默认 `sharpe`（可选 `sortino`） | 41 |
| `lookback_days` | int，默认 156 | 42 |
| `start_date` | `date`，必填 | 43 |
| `benchmark_key` | str，默认 `bond6040` | 44 |
| `max_weight` | float，默认 1/3，gt 0、le 1 | 45 |
| `rebalance_band` | float，默认 0.05（绝对值 5pp） | 46 |
| `risk_free_rate` | Optional[float] | 47 |
| `fee_rate` | float，默认 0.00015，[0,0.1] | 49 |
| `slippage_rate` | float，默认 0.00015，[0,0.1] | 51 |
| `stamp_duty_rate` | float，默认 0.0005，[0,0.01] | 53 |
| `assets` | `list[AssetIn]` | 54 |

`AssetIn`（30-34）：`symbol`、`source`、`quadrant`（必填）、`display_name`（可选）。
校验：`max_weight` 范围（56-61）；数值 round4（63-74，与 `repositories._r4` 同口径）；`ratio=="sharpe"` 时 `risk_free_rate` 必填（81-87）。
`CreatePortfolioIn` / `UpdatePortfolioIn` 只是继承（90-95）。
前端 `CreatePortfolioInput` 同字段（`web/lib/api.ts:496-511`）；`PortfolioInfo` 返回字段见 395-422。

#### 加入「一篮子资产（不分象限）」要改哪些函数

**最低风险方案（推荐先做）**：新增一个**伪象限 `basket`**，只允许 `method="all_risk_parity"`（它本来就是篮子风险平价），不新增优化算法。这样 `optimize()` 的 `all_risk_parity` 分支（380-381）直接可用，`run_backtest` 的 `quadrant_assets` 本来就是 Optional（79-96），传 `None` 即可。

必须改：

1. `bp_api/schemas.py:30-34`：`AssetIn.quadrant` 目前必填，需允许 `basket`（或改为 `Optional[Quadrant]` + 组合级 `mode`）。
2. `bp_api/main.py:44-64`：`_validate_portfolio_payload` 的「资产需指定象限」判断（49-51）与重复键 `(symbol,source,quadrant)`（52-57）要按 basket 模式放宽/改键；`max_weight` 可行性校验（58-64）仍保留。
3. `bp_api/repositories.py:184-199` `canonical_params`：资产三元组含 `quadrant`，basket 快照会与普通组合不同；若新增 `mode` 字段要纳入快照。
4. `bp_api/repositories.py:227-235` `_asset_quadrants`：basket 资产返回空列表；`_build_holdings_list`（1181-1197）、`_save_attribution`（1107-1115）、`compute_attribution`（`bp_api/quant/attribution.py:45-54,137`）会得到 `quadrants: []`，前端需容忍。
5. `bp_api/repositories.py:478-487` `_insert_portfolio_assets`：直接插入 `a.quadrant`；若 DB 允许 `basket` 则无需改代码，只需改 check。
6. `bp_api/repositories.py:540-565` `diff_payload`：资产排序键含 `quadrant`（557 行），basket 编辑逻辑要一致。
7. `bp_api/repositories.py:947-950` `_compute`：`quadrant_assets = build_quadrant_assets(pdef.assets)` 恒执行；basket 模式应传 `None`（或让 `build_quadrant_assets` 对 `basket` 返回 `None`）。
8. `bp_api/quant/optimizer.py:335-345` `build_quadrant_assets`：只认 4 个 `QUADRANTS`（33 行）；`basket` 会被忽略，返回 4 个空列表。`optimize` 的象限分支在 399-401 会因 `not quadrant_assets` 抛错，所以 basket 不能走默认方法。
9. `bp_api/quant/optimizer.py:348-447` `optimize`：若只想复用 `all_risk_parity`，无需改；若想要独立方法名 `basket_risk_parity`，在 380 附近加分支 → `risk_parity_weights(cov_m, max_weight)`，并同步方法注册表。
10. `bp_api/repositories.py:67-72` `BACKTEST_METHODS`（若新增方法）、75-80 `METHOD_LABELS_CN`、82-83 `TASK_TOTAL_STEPS`、86-88 `_step_label`、940-1043 `_compute`（并行 job 参数）、773-852 `run_and_save`、1118-1175 `_save_results`。
11. `ddl/schema.sql:278-281` `bp_portfolio.method` check（若新增方法）；`ddl/schema.sql:302-308` `bp_portfolio_asset.quadrant` check（加 `'basket'`）。`bp_portfolio_asset` 的 PK 含 `quadrant`（305），伪象限方案不用改 PK；若真要把 quadrant 设为 NULL，PK 需重设计，代价大。
12. 前端：`web/lib/api.ts:4` `Quadrant` 类型、13-34 `METHOD_OPTIONS`、37-42 `METHOD_LABELS`、496-511 `CreatePortfolioInput.assets[].quadrant`、345-353 `Holding`、395-422 `PortfolioInfo.assets`。
13. `web/app/builder/BuilderClient.tsx:36-42` `QUADRANT_ORDER/COLOR/SHORT`；211-214 编辑回填会丢弃非四象限行；283-341 payload 组装；590-635 四象限 UI。basket 需要单独「篮子」区块/模式开关。
14. `web/components/ChangeDiffDialog.tsx:19-20,116,136` 的 `quadrant` 展示要兼容 `basket`。
15. 测试：`bp_api/tests/test_optimizer.py`（方法行为）、`test_backtest.py`（无未来函数）、`test_repositories.py`（参数快照/diff）、`test_api_routes.py`（路由）、前端 `web/lib/*.test.ts`（如有 payload 逻辑）。

**若要做成真正的「无象限」数据模型**：不要改 `bp_portfolio_asset` 的 nullable quadrant（PK 含 quadrant，PG 不允许 NULL 主键列）；更干净的是新建 `bp_portfolio_basket_asset(portfolio_id,symbol,source,display_name,sort_order)`，或者保留 `bp_portfolio_asset` 但用 `basket` 伪值。前者要改 `_read_def`（429-466）、`_insert_portfolio_assets`、`diff_payload`、`canonical_params`、`get_result`、归因、前端 payload；后者改动小得多。

### B11. `repositories.py` 的代码组织与新增 domain 放置

- **模块结构**：顶部 import/registry（1-33）；`_json_safe`（36-52）、`_in_daemon_process`（55-64）；`BACKTEST_METHODS`/`METHOD_LABELS_CN`/`TASK_TOTAL_STEPS`（67-88）；基准注册表 `BENCHMARKS`（137-166）；工具 `asset_key`/`_r4`/`canonical_params`/`is_params_stale`（170-212）；资产清单（238-325）；价格面板（328-398）；组合定义 CRUD（401-767）；回测编排（770-1175）；结果读取（1178-1617）；demo/排序/数据源/管理资产/状态（1620-1946）；删除（1949-1953）。
- **函数命名**：动词开头、无前缀公开（`list_assets`、`load_price_panel`、`create_portfolio`、`get_result`、`run_and_save`），内部辅助 `_` 前缀（`_read_def`、`_save_results`、`_json_safe`、`_r4`）。section 用 `# ---------------------------------------------------------------------` 分隔。
- **事务写法**：`with db.get_conn() as conn:`（`bp_api/db.py:36-41`，pool `autocommit=False`）；**大多数 repository 函数只执行 SQL，不 commit，由调用方 commit**（如 `create_portfolio` 494-510、`update_portfolio` 513-534）；少数函数自带 commit（`delete_portfolio` 1949-1953）。API 层显式 `conn.commit()`（如 `main.py:330,357,391`）。
- **JSON/数值工具**：所有 `Json()` 实参走 `_json_safe`（36-52）防 NaN/Infinity；权重/参数 round4 用 `_r4`（174-181，Decimal HALF_UP，避免 Python 银行家舍入）；`psycopg.types.json.Json` 在文件顶部 import（20）。
- **性能/并发**：`_compute` 采用 `ProcessPoolExecutor`（非 Windows、非 daemon）或 `ThreadPoolExecutor`（Celery prefork daemon 回退），`BP_BACKTEST_METHOD_WORKERS`/`BP_MAX_CPU_FRACTION` 控制（997-1043）。`run_and_save` 依次落 4 方法结果、覆盖判定、全部基准净值、归因（773-852）。
- **新增 domain 放哪**：
  - **只读预计算看板**（如指数估值、加密多空比）：**不要塞进 `repositories.py`**。照 `bp_api/cffex.py` / `bp_api/crypto.py` 新建 `bp_api/<domain>.py`，内含 SQL 读取 + `register_routes(app)`；预计算写库放 `bp_ingest/<domain>.py`。这与 `/crypto` 的「请求路径永不计算」一致。
  - **需要事务 CRUD 的 domain**：新建 `bp_api/repositories_<domain>.py`，照 `repositories_otc.py` 的组织方式；公共工具 `_json_safe`/`_r4` 可从 `repositories` import（当前是私有名，跨模块 import 可用但不优雅；若要复用，建议先抽 `bp_api/db_utils.py`）。
  - **只加几个只读查询**：可以放 `repositories.py` 的对应 section，但 1953 行的文件已很大，建议新文件。

---

## C. 结论：五个新需求的落地清单

> 通用前提：当前最新迁移编号是 **50**（`ddl/50_asset_date_coverage.sql`），新迁移从 **51** 开始；全新环境仍只跑 `ddl/schema.sql`，已部署环境只跑未应用编号。`deploy/deploy.sh` 不跑迁移。新增预计算看板必须遵守 `pick_effective_trade_date` 的 hold-back 语义与 `revalidateTag(tag, profile)` 的 profile 一致规则。

### (a) 指数估值页面 + 数据

**必须新建**
- `ddl/51_index_valuation.sql`：`bp_index_valuation_daily(trade_date, symbol, source, pe_ttm, pb, dividend_yield, ...)`、`bp_index_valuation_meta(key,value)`（或统计表）；索引 `(symbol, trade_date)`。
- `bp_ingest/valuation.py`：`compute_and_store_valuation(conn)`（全量/增量、`effective_td`、`version`、`_ping_valuation_revalidate`），照 `bp_ingest/crypto_corr.py:325-526` 的批量 upsert + meta + version 模式。
- `bp_api/valuation.py`：`register_routes(app)`，`GET /api/valuation/overview`、`GET /api/valuation/history`、`GET /api/valuation/statistics`；只读预计算表 + Redis 缓存 + version key，照 `bp_api/crypto.py:205-275`。
- `web/app/valuation/page.tsx`（Server 壳）+ `web/app/valuation/ValuationClient.tsx`（Client，照 `CryptoClient.tsx` 的区块/Tabs/EChart）。
- `web/app/api/revalidate/valuation/route.ts`（内部令牌 `X-Internal-Token`，照 `revalidate/crypto/route.ts`）。
- `bp_api/tests/test_valuation.py`；可选 `web/lib/valuation-format.ts` + vitest。

**必须修改**
- `ddl/schema.sql`：在 crypto 表之后（约 599 行后）追加估值表；若用 `sources.py` 适配器，在 `bp_data_source` seed（74-108）加源；`bp_index_config` 无需新增列（估值按 symbol/source 关联）。
- `bp_api/main.py:138-145`：import + `register_routes(app)`。
- `bp_ingest/sources.py:756-815`：新增 `_fetch_index_valuation` 与 `SOURCES` 条目（接口按 akshare 实际可用函数确认；若走独立 HTTP，则放 `valuation.py` 内，不注册为资产源）。
- `bp_ingest/scheduler.py:58-90,126-143`：新增 job；`bp_ingest/config.py:56-101` 加同步间隔环境变量（可选）。
- `bp_ingest/ingest.py:407-434`：若估值依赖指数收盘更新，加钩子（仿 crypto 钩子）。
- `web/lib/cached-data.ts:53-66`：新增 `getCachedValuation()`，`cacheLife("hours")` + `cacheTag("valuation")`（失败 throw，不缓存 null）。
- `web/lib/api.ts:1001-1049` 附近：新增估值类型；`web/components/Navbar.tsx:20-26` 加导航；`web/app/sitemap.ts:4` 加路由；`web/app/page.tsx:367-378` 可选首页区块。
- `web/app/api/revalidate/route.ts`/`web/lib/revalidate-guard.ts:20-27`：若走 admin 路径需把 `valuation` 加入白名单；更推荐独立内部令牌路由。
- `bp_api/tests/test_api_routes.py`：加路由 smoke。
- `docs/data-sources.md`、`CLAUDE.md`：记录新表/新任务/口径。

### (b) 股票资产类别（含三种复权）

**必须新建**
- `ddl/51_stock_sources.sql`（或顺延）：向 `bp_data_source` 插入 `stock_em`（东财 `stock_zh_a_hist`，支持 `adjust=qfq/hfq/空`）与 `stock_tx`（腾讯 `tencent_fqkline`，备源）；可选 `stock_sina`。`is_addable=TRUE`，`logical_source='stock'`，`is_backup` 按主/备设置。
- `bp_api/tests/test_stock_sources.py`（复权口径/降级链/收益率对齐）。

**必须修改**
- `bp_ingest/sources.py`：
  - 新增 `_fetch_stock_em`（模板：`_fetch_etf_em` 454-463，把 `ak.fund_etf_hist_em` 换成 `ak.stock_zh_a_hist`，`adjust` 从 `extra` 取，`_rename(_CN_OHLCV_MAP)`）。
  - 新增 `_fetch_stock_tx`（复用 `_fetch_tx_kline` 505-556；`_tx_market_prefix` 493-502 已覆盖 60/00/30/68 等，北交所 8/4 开头需补 `bj`）。
  - `SOURCES` 注册（756-815）；`AGGREGATE_CHAINS`（836-843）只把**同复权口径**的 `stock_em → stock_tx` 串起来，绝不要跨 qfq/hfq 聚合（参考 ETF 注释 824-830）。
- `bp_ingest/ingest.py:227-230`：`fetch_with_fallback(..., cfg.extra_params)` 已透传 `adjust`，无需改。
- `bp_ingest/db.py:74-100`：配置查询已取 `category`/`extra_params`，无需改。
- `bp_api/quant/cleaning.py`：只按 `currency/fx` 处理（94-111,330-360），**没有 category/adjust 逻辑**；股票 adapter 输出的 close 已是目标复权口径，无需清洗层改。若股票为 CNY，`currency='CNY'` 默认不折算（`schema.sql:123`）。
- `web/lib/api.ts:258-264`：`ASSET_CATEGORY_OPTIONS` 加 `{value:"stock",label:"股票"}`；`ASSET_ADJUST_OPTIONS` 已有 bfq/qfq/hfq（270-275）。
- `web/lib/asset-form.ts:33-41`：`buildExtraParams` 目前仅 `category==="etf"` 才带 `adjust`，改为 `category==="etf" || category==="stock"`（或按 source 判断）。
- `web/components/CreateAssetDialog.tsx:205-228`：分类下拉（205-216）与复权下拉 `disabled={form.category !== "etf"}`（219）改为允许 stock；提示文案 228 同步。
- `web/app/admin/assets/page.tsx:547-580`：同样的分类/复权 gating（567 行 disabled；579-580 文案）。
- `web/components/RiskMatrixSection.tsx:15-21`：`CATEGORY_LABEL` 加 `stock:"股票"`；`inferCategory`（31-36）可加股票识别（若希望矩阵标签显示股票类别）。
- `web/app/builder/BuilderClient.tsx:920,941,958,1082-1086,1143-1152`：资产筛选/排序/徽章逻辑要识别 stock；`ETF · 复权` 徽章（1143）目前写死 ETF，需按 `category` 泛化。
- `ddl/schema.sql:74-108`：同步 seed 新源；`ddl/47` 的 `category='etf'` 判 adjust 逻辑（47 号迁移注释）在股票上要用 `category='stock'`，不要只按 source。
- `docs/data-sources.md`、`CLAUDE.md`、`bp_api/tests/test_source_aggregation.py`/`test_asset_create_flow.py`。

### (c) 对外 REST API 带 token 鉴权

**必须新建**
- `ddl/51_api_tokens.sql`：`bp_api_token`（字段见 B8）。
- `bp_api/api_tokens.py`：`create_token`（返回明文一次）、`verify_token`（prefix+hash+scope+expiry+revoked）、`revoke_token`、`list_tokens`；hash 用 `hashlib.sha256`/HMAC + pepper。
- `bp_api/public_api.py`：`register_routes(app)`，`/api/v1/*` 只读端点（资产、组合结果、crypto/cffex/valuation），全部 `Depends(require_api_token)`。
- `bp_api/tests/test_api_tokens.py`：签发/校验/撤销/过期/scope/限流。
- 可选 `web/app/admin/api-tokens/page.tsx` + `web/components/CreateApiTokenDialog.tsx`（超管签发/撤销）。

**必须修改**
- `bp_api/auth.py:426-469`：新增 `require_api_token` 依赖（复用 `UserContext` 21-27）；不要改 `require_user` 的 JWT 语义。
- `bp_api/main.py:17`（imports）与 `138-145`（注册 `public_api`）；新增 `/api/admin/api-tokens` 路由（建议放 `public_api.py` 或 main 的 admin 区 209-243 附近）。
- `bp_api/schemas.py`：在 145 行后加 `ApiTokenCreateIn`/`ApiTokenOut`。
- `ddl/schema.sql`：在 `bp_user`（226-245）后加表定义（基线）。
- `web/lib/api.ts`：在 `AuthProfile`（539-553）后加 token 类型，在 `api` 对象（726-999）加 `listApiTokens/createApiToken/revokeApiToken`；管理页入口放 `Navbar.tsx:54-62` 或 `/admin/users`。
- `bp_api/cache.py:70-81`：复用 `incr_with_ttl` 做 token 限流。
- `.env.example`/`deploy/OPS.md`：新增 `BP_API_TOKEN_PEPPER`（可选）与内部调用说明。
- `docs`/`CLAUDE.md`：记录 `/api/v1` 契约、过期/撤销策略。
- 注意：反向代理路由顺序必须保持 `/api/session* → Next`、`/api/* → FastAPI`；`/api/v1/*` 会走 `/api/*` 到 FastAPI，符合预期。

### (d) 一篮子风险平价

**必须新建**
- `ddl/51_basket_mode.sql`（或顺延）：给 `bp_portfolio_asset.quadrant` check 加 `'basket'`；若新增独立方法，再给 `bp_portfolio.method` check 加 `basket_risk_parity`。伪象限方案不需要改 PK。
- `bp_api/tests/test_basket_portfolio.py`：basket payload → 回测 → 结果/持仓/归因。
- 可选 `web/components/BasketAssetPicker.tsx`：如果 Builder 的篮子模式需要独立 UI；否则直接在 `BuilderClient` 加 Tab/区块。

**必须修改（最小方案：伪象限 + 复用 `all_risk_parity`）**
- `bp_api/schemas.py:30-34`（`AssetIn.quadrant` 允许 `basket`）；37-54（payload 可加 `mode`）；`main.py:44-64`（校验放宽）。
- `bp_api/repositories.py:184-199`（快照）、227-235（quad_map）、478-487（插入）、540-565（diff）、947-950（basket 传 `None`）、1181-1197（holdings）、1407-1617（get_result 输出）、773-852（run_and_save 归因）。
- `bp_api/quant/optimizer.py:33`（4 象限常量）、335-345（build_quadrant_assets 忽略 basket）、348-447（basket 必须走非象限分支；若新增方法在此加分支）。
- `bp_api/quant/backtest.py:79-96`（`quadrant_assets` 已 Optional，传 `None` 即可）、66-76（`_filter_quadrants` 对 None 返回 None）。
- `ddl/schema.sql:302-308`（quadrant check）；278-281（若新增方法）。
- 前端：`web/lib/api.ts:4,13-42,345-353,395-422,496-511`；`BuilderClient.tsx:36-42,211-214,283-341,590-635`；`ChangeDiffDialog.tsx:19-20,116,136`；`DashboardClient.tsx` 方法/象限展示（379,429,926,1143,2645 附近）。
- 测试：`bp_api/tests/test_optimizer.py`、`test_backtest.py`、`test_repositories.py`、`test_api_routes.py`。

**若新增独立方法 `basket_risk_parity`**：额外改 `repositories.py:67-72,75-80,82-83,86-88,940-1043`；`web/lib/api.ts:13-42`；`ddl/schema.sql:278-281`；`optimizer.py:380` 分支。

### (e) 加密多空人数比看板

**必须新建**
- `ddl/52_crypto_longshort.sql`：`bp_crypto_longshort_daily(trade_date, symbol, exchange, metric, ratio, ...)`（PK `(trade_date, symbol, exchange, metric)`）、`bp_crypto_longshort_meta(key,value)`；若多空比按账户/持仓/大户分列，可一行多列（镜像 `bp_crypto_corr_daily` 的 Option A）。
- `bp_ingest/crypto_longshort.py`：抓取（Binance Futures public data `/futures/data/globalLongShortAccountRatio`、`/futures/data/topLongShortPositionRatio`，或 OKX 对应接口；用 `bp_ingest/http_session.py` 的硬化 session）→ 按 NYSE/UTC 日对齐 → 全量 upsert → meta/version → `_ping_crypto_longshort_revalidate`。
- `bp_api/crypto_longshort.py`：`register_routes(app)`，`GET /api/crypto/long-short`（只读预计算表 + Redis version 缓存）。
- `web/app/crypto/long-short/page.tsx` + `CryptoLongShortClient.tsx`（或独立 `/crypto-longshort`；推荐嵌套 `/crypto/long-short`，复用 `/crypto` 视觉）。
- `web/app/api/revalidate/crypto-longshort/route.ts`（内部令牌；或把 tag 加进现有内部 revalidate 路由）。
- `bp_api/tests/test_crypto_longshort.py`；可选 `web/lib/crypto-longshort-format.ts` + vitest。

**必须修改**
- `ddl/schema.sql`：在 crypto 表区（556-599）追加两张表。
- `bp_api/main.py:138-145`：注册新模块。
- `bp_ingest/scheduler.py:58-90,126-143`：新增 job（如每小时/每日）；`bp_ingest/config.py:56-101` 加间隔 env；`bp_ingest/ingest.py:407-434` 可选钩子；`bp_api/workers/jobs.py:144-164` 加 Celery 任务、`workers/celery_app.py:60-65` 加 beat。
- `web/lib/cached-data.ts:53-66`：新增 `getCachedCryptoLongShort()`，`cacheLife("hours")` + `cacheTag("crypto-longshort")`；失败 throw。
- `web/lib/api.ts:1001-1049`：新增响应类型；`web/components/Navbar.tsx:20-26`：加导航；`web/app/sitemap.ts:4`：加路由。
- `web/lib/chart-theme.ts:2-23,25-65`：若需要多空专用色，扩展 `crypto` 或新增 `longShort` 槽（不要在组件写死 hex）。
- `web/app/api/revalidate/crypto/route.ts` 或新建内部路由：确保 tag/profile 一致（`revalidateTag("crypto-longshort","hours")`）。
- `docs/data-sources.md`、`CLAUDE.md`：记录数据源、口径（原生 USD，不做 CNY 折算，参考 `docs/data-sources.md:54-55`）、刷新频率。
- 若要把多空比资产加入回测/组合，才需要在 `bp_data_source`/`bp_index_config` 注册；**纯看板不需要**（像 crypto_corr 一样用专用预计算表，不进入 `bp_quote_clean` 回测口径）。

---

## 附：跨需求通用检查清单

1. **迁移编号**：最新 50；新迁移 51+；`ddl/schema.sql` 是合并基线，全新环境只跑它；已部署环境只跑未应用编号；不要改已应用脚本。
2. **预计算看板**：ingest 任务写表 → 失效 Redis → 失效 Next cacheTag；API 请求路径只读表，绝不现场计算（`/crypto` 的原 27s 计算已移走，`bp_api/crypto.py:1-14`）。
3. **effective_td**：必须等「所需标的当日齐全 + 收盘确认」才推进；否则 hold-back 到上一个完整日（crypto: `crypto_corr.py:369-405`；cffex: `cffex.py:81-105,112-151`）。
4. **缓存 profile**：`revalidateTag(tag, "hours")` 必须与 `cacheLife("hours")` 一致；否则失效不到（`web/app/api/revalidate/route.ts:41-43`；`web/app/api/revalidate/crypto/route.ts:26-28`）。
5. **价格口径**：组合回测只读 `bp_quote_clean`；非 CNY 先按 `fx_rate` 折算；`/crypto`、`/cffex`、新加密看板用原生 USD（`CLAUDE.md` 数据流章节；`docs/data-sources.md:54-55`）。
6. **鉴权**：现有只有 JWT Bearer + TOTP；新增对外 API 必须另建 token 表/依赖，不要复用内部 `BP_INTERNAL_REVALIDATE_TOKEN`。
7. **前端设计**：图表色一律 `getChartTheme`，涨跌色只做方向语义，危险确认用 AlertDialog，反馈用 sonner；新增基础组件放 `web/components/ui/`。
8. **CI 必跑**：`python -m pytest bp_api/tests -q`、`cd web && npm test`、`cd web && npm run build`、`npm run typecheck`（CI 口径见 `.github/workflows/ci.yml`）。

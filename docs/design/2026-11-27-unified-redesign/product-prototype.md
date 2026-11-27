# 产品原型说明（逐页）

## A. /valuation 指数估值首页
### A1 页头与全局数据更新徽标（需求 1、10）
- 替换写死的「Valuation Band · 市场估值指数 · 多窗口分位」为 `<DataFreshnessBadge>`：`数据更新至 2026-11-27`（绿点/琥珀点），点击展开 8 类数据明细（A股、港股、ETF、基金、CFFEX、指数行情、指数估值、MVI）的 as_of、完成时间、缺口原因。
- 数据来源：新增 `GET /api/v1/market/data-freshness`（匿名）；由 bp_etl/估值/MVI/CFFEX 任务成功写状态；定义 `latest_complete_date = min(last_success_date)`；理论最新交易日用 A 股收盘确认 15:10 口径；fund 20:00+、估值 21:00+ 作为正常完成时间写入 tooltip。
- 验收：任一数据集落后时徽标变琥珀并显示落后项；API 60s 缓存；页面无额外慢请求（SSR 内联）。

### A2 Valuation Band（需求 2、3）
- 指数器：segmented 4 项（沪深300 / 中证A500 / 上证50 / 中证全指），后续「更多…」搜索 521 只；默认沪深300。指数切换只替换主图与右栏数值，不重载页面。
- 指标 tabs：PE-TTM / PB / 股息率 / 风险溢价。**切换指标不发新请求**：`/indices` 一次返回 4 指标当前值+分位+历史数据包；仅首次加载/指数切换取数。
- 主图：分位带（当前值、分位、低估/中性/高估 badge、机会/中位/危险线、近5年/近10年/全部窗口）。
- 性能方案（需求 2）：新增预计算表 `bp_index_valuation_latest`（每指数 4 指标当前值/分位/1y sparkline/更新日，由估值任务收尾刷新）；`/api/v1/valuation/indices?metric=` 读该表（<50ms）；恢复 Redis 60-180s 缓存 + gzip；前端用 SWR/Query 预取，metric 切换纯本地；移除 metric 切换时的 RSC 导航（useState 而非 router.replace）；去掉未渲染的 boards 字段。
- 验收：首屏 TTFB < 600ms、切换 < 16ms 帧内完成、payload < 150KB gzip；LCP < 1.8s。

### A3 MVI 卡（需求 6）
- 标题 + 两个 `?`：估值分、风险分。tooltip 内容：估值分=PE/PB（反向）、股息率、ERP、ROE 的 104 周滚动分位加权（权重 16.86/19.27/28.53/23.47/11.88，v1 固定权重、in-sample 声明）；风险分=波动率分位 55% + 最大回撤分位 45%。
- 当前值 31.29、低估、估值分 68.71、风险分 66.92、因子贡献条（贡献值来自 `bp_market_valuation_index`）。
- 近5年走势：周频、平滑；去掉「(0 便宜 / 100 贵)」文字；分位带背景；hover 显示日期/MVI/zone。
- 展开：modal 双轴图（MVI 左轴、指数右轴），指数切换 4 只，默认中证全指；颜色：MVI sky / 指数 amber；自适应宽度；tooltip 十字线；右侧可显示当前 MVI 与指数点位。
- 数据修正：compute_mvi.py 按交易日历重采样周频（去掉周末点）、rolling 窗口=104 周真正 2 年、NaN 处理；全量重算历史；测试锁死“周末不产生 MVI 点族”“无 NaN 导致 0 分位”。
- API：`/api/v1/market/mvi?range=5y` 返回周频序列 + 因子贡献；`/api/v1/market/mvi/overlay?index=000985` 返回指数收盘序列（来源修复后的指数行情/估值）。

### A4 行业估值热力（需求 4）
- 标题右侧 `?` tooltip：「行业估值热力 = 该行业下所有跟踪指数的 PE-TTM 近 5 年分位均值；样本数 = 参与计算的指数数量；分位越低越便宜」+ 窗口说明 + 数据截止日。
- 方格 16 行业、颜色分位映射、显示样本数；点击筛选下方列表；hover 显示行业名/分位/样本数/代表指数。

### A5 红利指数吸引力（需求 5）
- 模式切换 button：绝对估值 / 相对估值。
- 绝对模式：PB（对数轴）× 股息率，气泡=规模，回归线+R²，中位十字线；对数轴用 log 拟合/采样保证回归线口径一致。
- 相对模式：PB 5y 分位 × 股息率 5y 分位，四象限背景与均值线；范围 30 只红利/股息指数；两模式均 hover tooltip。
- 数据：/indices 已含 4 指标分位，无需后端新表；仅增加前端模式与对数轴。

## B. /valuation/HSI 详情页（需求 7、8）
- 头部：HSI 名称/代码/市场/成分数、当前点位+涨跌+日期（红涨绿跌）。
- 4 MetricCard：PE/PB/股息率/风险溢价（当前值+5y 分位+PercentileBar）。
- 主图：估值与点位双轴（近10年/近5年），PE-TTM 左轴/点位右轴/机会危险线，分位带开关。
- 跟踪基金卡：
  - 右上：规模合计 + **数据截至（bp_index_tracker_fund max trade_date）+ 更新于（计算任务 updated_at）**；
  - Top10 规模条形图 + 表格：代码/名称/公司/经理/规模/费率/TE 1y/年化波动/1y收益；TE>5% warning；可排序、展开；hover 高亮；
  - TE 修复后数据：SH513660 ≈ 4.31%（原 50.57% 为 nav 未复权口径错误）。
- 收益风险卡：1y/3y/5y 年化收益、波动、最大回撤、Sharpe（修复后的 bp_fund_risk）。
- 空数据：成分/行业暂空 → 统一空态卡「数据建设中」，不显示骨架；后续补数据。
- 脚注：净值口径（acc_nav / 回退 ETF 后复权）、基准口径（HSI 全收益或 HSI×HKDCNY）、窗口与更新时间。
- 后端修复：`compute_fund_risk.py` 改用 acc_nav（缺失回退 ETF hfq 后复权）并做断点修正；基准改为 HSI 全收益（若无源，用 HSI 价格指数 × HKDCNY 并在 UI 标注）；全量重算 1147 只；跟踪基金接口补 max(trade_date)/updated_at。

## C. /dashboard 四象限 + 一篮子（需求 9）
- 顶部 `PageModeHeader`：整行居中 pill tabs（四象限组合 / 一篮子资产）；右侧操作按模式固定位置，不随切换跳动；容器与内容列对齐（含 TOC 时预留相同 gutter）。
- 四象限：组合下拉居中（宽 320-360px，显示最近更新日）、KPI 卡、净值图 vs 基准、四象限矩阵、持仓表；**每个卡片独立局部 skeleton**。
- 一篮子：
  - 选择器：示例「A股核心资产 12 只（示例）」+ 我的篮子；
  - 示例：`bp_basket.is_demo=true`，owner=管理员，所有人（含匿名）可读，复制需登录，仅 admin 可编辑；`?mode=basket&basket=<id>` 可打开；
  - 12 只（草案，可调整）：贵州茅台600519、宁德时代300750、招商银行600036、中国平安601318、五粮液000858、美的集团000333、长江电力600900、紫金矿业601899、比亚迪002594、恒瑞医药600276、隆基绿能601012、海天味业603288；数据源 `etl_a_stock`（hfq，2020/2021 起）；
  - 指标由服务端重算落库（admin-only POST /api/baskets/{id}/recompute），游客读取缓存结果；修复 BasketBuilder 资产池空缺陷（首次并行拉取资产池+篮子，加载后重映射名称）。
- 交互/性能：模式切换用预取 + 局部 shell，不再整页硬导航；basket 列表 SSR/缓存；匿名回测限流。
- 验收：模式切换 < 300ms 响应；下拉居中；示例匿名可读；游客点保存提示登录；admin 可编辑、非 admin 只读并提示复制。

## D. 平台/全站一致性（需求 11）
- 统一 layout：`AppHeader`（glass/pill）+ 页面容器组件 + `PageHeader` + `SectionCard` + KPI/表格/图表/Skeleton 原语。
- 页面池：/、/methodology 用 A 留白风；/dashboard、/valuation、/cffex、/crypto、/otc 用 C 工作台风；/admin 用简版工作台。
- 迁移顺序：先建 token + 原语 → 3 个标杆页（/valuation、/valuation/HSI、/dashboard）→ /cffex、/crypto → /builder、/otc、/admin → 首页/方法论打磨。
- 可访问性/暗色/响应式/动效在每页验收清单内。

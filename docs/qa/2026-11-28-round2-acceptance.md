# 第二轮全站整改 · 生产验收报告（2026-11-28）

## 部署
- 生产 81.71.158.239：main 最新 9655aef（含 Next 16.4.6 升级、ddl/81 roe_ttm、ddl/82 数据体检表已应用）。
- PM2 五进程 online，bp-ingest 保持 stopped；干净 .next 重建，web 200 / api health ok。
- 新增/安装 cron：bp-index-quotes-free（16-23 每15分+09:00）、bp-data-audit（09:30）、bp-market-valuation（21:20）、bp-risk-free（21:40）、bp-legacy-backfill（21:05）+ 原 bp-quote-gap-repair/bp-valuation/bp-mvi/bp-cffex。

## 测试
- 后端 pytest bp_api/tests：847 passed / 47 skipped（真实库测试需 BP_MIG_TEST_DSN）。
- 前端 typecheck 0、vitest 245 passed、next build 0（Next 16.4.6，25 路由）。
- 代码审查（后端/前端两个 reviewer）：所有 ≥80% 置信问题已修复并回归；生产 QA 全部页面 console/page error = 0。

## UI/交互验收（生产 Chrome headless + agent-browser，截图 docs/qa/round2-qa/）
- /valuation：标题仅 Valuation Band、无「沪深300 ·」/「指标切换本地完成」/「· 数据截至」；热力格点击不筛选、无 blue focus、hover 统一；红利卡居中/上下留白、绝对模式 Y 轴自适应；MVI modal 1152px、overlay 200、点位有数据；PB×股息率轴标签可见；ROE×PE 389 散点（roe_ttm 回填）。
- /valuation/000016：成分饼图 +「隐藏非前10大权重股」默认开启；PB/点位图例可显隐、布局不重叠、右轴说明删除；收益率分布切换基准出现第二系列；跟踪基金 6 列升降序 + aria-sort；详情页静态壳+内容骨架。
- 一篮子：/builder?mode=basket&basket=4 与 /dashboard?mode=basket 游客切四象限均落 /dashboard 无登录门禁；资产行后复权 hfq、无复权开关；打开即显示最近净值 + 7 项扣费后指标（年化收益/最大回撤/年化换手/交易日/Sharpe/Sortino/Calmar）；费用显示 0.03%/0.10%/0.10% 已修复；旧回看卡片移除；latest_result 含 nav/指标/params 指纹，列表裁剪 nav。
- 首页 console 错误随 Next 16.4.6 修复；9 个主要页面生产扫描 0 错误。

## 数据审计
- A股/ETF/港股/基金 bfq+hfq、legacy_index bfq+hfq、CFFEX、估值、MVI、clean 全部 11-27；bp_etl_backlog=0。
- 000985：行情 2440 行（2017-01-01 起）；估值 PE=17.39（PE1 口径修正）、PB 无免费源=NULL、估值历史仅中证官网滚动 20 日（2026-11-02 起，coverage_start 已记录）。
- 10Y 国债 2021-01-04~11-27（1473 行）；市场估值 11-14~11-27（10 行，源无更早历史）；MVI 232 周点。
- 每日体检：39 项 ok、3 warn、0 error（index_quotes 覆盖率 warn、指数收益跳变 warn、PE 跨源样本不足 warn）；落库 bp_data_audit_daily 并通过 /api/v1/market/data-health 暴露。
- 指数行情（最终口径）：免费源可覆盖 tracked 指数 423 只，T+1 覆盖 422/423 = **99.76%**（同日 417/423=98.6%，PASS）；438 只有效 tracked 中 15 只从无任何免费源行情（多为 MSCI/港股通细分，已单列 source_unavailable），6 只为官方源 T+1 发布。

## 遗留限制（需用户决策/授权）
1. 指数行情：免费源口径已达成 99.76%；15 只无免费源指数的数据缺口需代理/付费源才能补齐（不影响 SLO 口径，已记录 source_unavailable）。
2. 000985 长历史估值/PB：免费源物理不可得（中证官网仅滚动 20 日、无 PB）；已记录限制并每日快照。需要历史数据可选付费源。
3. 市场估值仅 5 天历史、10Y 仅 2021 起：免费源历史上限，已记录。
4. 安全 P0：历史文档曾泄露生产库明文密码（当前文件已移除）；需授权轮换 DB 密码并清理 git 历史（维护窗口）。

## 验收证据
- 计划/调研：docs/qa/2026-11-27-round2-plan.md、docs/qa/2026-11-27-round2-data-cron.md
- QA 截图与逐步记录：docs/qa/round2-qa/（28+ 张）
- 生产 audit JSON：/tmp/audit_accept.json（服务器）
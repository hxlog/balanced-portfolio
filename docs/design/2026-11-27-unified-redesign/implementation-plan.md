# 实施计划（多 Agent 并行）

> 前置：用户确认本目录文档与原型变体选择后启动。原则：先数据、后功能、再视觉；每阶段独立验收、可回滚；生产变更走 migrations + git + PM2。

## 阶段与优先级

### P0 · 数据时效与正确性（最高优先，1-3 天）
| 任务 | 内容 | 涉及文件/系统 | 验收 |
|---|---|---|---|
| P0-1 CFFEX | 已完成修复 + cron；加 15:30-16:48 高频轮询（可做 2min）+ 快照 TTL 300s | bp_ingest/cffex.py、/etc/cron.d/bp-cffex | 收盘后 ≤15min 有 11-27 四品种数据 |
| P0-2 估值/MVI 调度 | 已完成 cron；新增 freshness 状态写入；MVI 23:50 | valuation_job、compute_mvi、bp_etl_dataset_state/新表 | 估值 23:00 前 521 指数；MVI 当日 |
| P0-3 指数行情恢复 | 新 `scripts/index_quotes_free.py` 多源轮询（腾讯→新浪→csindex→东财），16:00-23:00 每 15min；修复 190/288 覆盖 | scripts、bp_index_quote_daily | 覆盖 ≥99% 跟踪指数；clean 对齐 |
| P0-4 clean 解耦/对账 | 清洗钩子按 fetched>0 触发（已做）+ 新增指数行情后增量 clean + status 刷新；一次性清旧 backlog 38k；修重复 source 读取口径 | bp_etl/cleaning_hook、orchestrator、health、bp_api/repositories | clean 最大日=行情最大日；backlog<1000 |
| P0-5 市场估值/10Y | 替代免费源或先隐藏；10Y chinabond/akshare 兜底 | bp_ingest/market_valuation、bonds | 源恢复或 UI 明确隐藏 |
| P0-6 全局 freshness API | 新表/端点 + 8 类数据写入；前端 DataFreshnessBadge | bp_api（新路由）、bp_etl/估值/MVI 任务、web | API <50ms、徽标准确 |
| P0-7 组合刷新验证 | 确认 beat+worker+20min enqueue 与 clean 对齐；11-27 组合到 11-27 | 运维验证 | 22/22 组合最新完整日一致 |

### P1 · 估值页功能（2-4 天）
- P1-1 性能方案 B：新表 `bp_index_valuation_latest`（每指数 4 指标当前值/分位/1y spark/更新日），估值任务收尾刷新；`/api/v1/valuation/indices` 改读快照 + gzip + Redis 60-180s；前端 metric 切换零请求、去掉 RSC 导航。
- P1-2 指数选择器（4 只）+ 000985 中证官网源接入 + 000510 窗口标注。
- P1-3 MVI 计算修复：交易日历/周频重采样、NaN 修复、窗口 2 年、全量重算；单测锁死不变量；新增 overlay API。
- P1-4 MVI 前端：info tooltip、去掉文案、展开 modal 双轴 + 4 指数切换。
- P1-5 行业热力 tooltip（公式+样本数）。
- P1-6 红利相对估值模式 + 绝对模式对数轴。
- P1-7 页头全局数据徽标接入。
- 验收：切换 <16ms、payload <150KB gzip、MVI 无尖刺（日变 <5 的占比 >99%）、4 指数可切、tooltip 内容正确。

### P2 · Dashboard 与一篮子（2-3 天）
- P2-1 PageModeHeader 居中/对齐；组合下拉居中加宽；模式切换预取。
- P2-2 basket is_demo 迁移（ddl 78）+ 12 只示例 seed + 权限（游客可读、复制需登录、仅 admin 编辑）+ 服务端重算接口 + 前端只读态。
- P2-3 修复 BasketBuilder 资产池空缺陷（并行加载资产池+basket，缓存 5min）。
- P2-4 局部 loading（KPI/图/表分别 skeleton）。
- 验收：示例匿名可读、复制登录、admin 编辑；模式切换 ≤300ms；12 只示例指标服务端可信。

### P3 · 设计系统与全站 UI 重构（5-8 天，分批）
- P3-1 建立 token/原语：globals.css 扩展（红涨绿跌、双主题、radius 3 级、shadow/glow、motion token）、Skeleton、PageHeader、SectionCard、DataFreshnessBadge、KpiCard、ChartCard、DataTable、Segmented/Tabs、Tooltip。
- P3-2 标杆页迁移：/valuation、/valuation/HSI、/dashboard（按选定变体）。
- P3-3 其余页面：/cffex、/crypto、/builder、/otc、/admin、/、/methodology。
- P3-4 动效/loading 全面替换（删全局 loading，局部 skeleton；路由淡入保留）；暗色与响应式回归。
- P3-5 性能：ECharts 按需引入（30+ 图）、去掉重复请求/ RSC 重算、图片/字体优化。
- 验收：三端（桌面/平板/手机）× 双主题截图验收；Lighthouse ≥90；无 TS/lint/build 错误；测试全绿。

### P4 · 审计与收尾
- 全站时效性/完整性/准确性周报；SLA 监控；文档更新（design-system、OPS、API）。
- 回归：后端 pytest、前端 typecheck/test/build、CI 绿；生产灰度与回滚演练。

## 并行 Agent 拆分（建议）
| Agent | 范围 | 写权限 |
|---|---|---|
| data-agent-1 | P0-3 指数行情多源脚本 + cron + 对账 | scripts/、/etc/cron.d（部署由 root agent） |
| data-agent-2 | P0-4 clean/backlog/重复去重 + P0-5 估值/10Y 源 | bp_etl/、bp_ingest/、scripts/ |
| backend-agent-1 | P0-6 freshness API + P1-1 快照表/接口 + P1-3 MVI 修复 | bp_api/、ddl/、bp_ingest/valuations |
| backend-agent-2 | P1-2 000985 源 + P1-7 显示；P2 basket 后端 | bp_ingest/、bp_api/、ddl/78 |
| frontend-agent-1 | P3 token/原语 + /valuation + /valuation/HSI | web/app/valuation、web/components/ui、web/lib |
| frontend-agent-2 | P2 dashboard/basket 前端 + P3 dashboard | web/app/dashboard、builder、components |
| frontend-agent-3 | P3 /cffex /crypto /otc /admin/首页/方法论 | 对应目录 |
| qa-agent | 测试/验收/CI/截图矩阵 | tests、无生产代码 |

依赖：P0-6 依赖 P0-2/P0-3 写入 state；P1 依赖 P0（数据）；P2 可与 P1 并行；P3 依赖设计确认但 token 可先行。共享写范围需在 Team task 中登记，避免同文件冲突（globals.css、repositories.py、valuation API 分散给不同 agent 时先拆分接口）。

## 数据库/接口变更清单
- 新表：`bp_data_freshness`（dataset, as_of, updated_at, status, note）；`bp_index_valuation_latest`（index_code, trade_date, pe/pb/dividend/erp, pct flags, spark json, updated_at）。
- 新列：`bp_basket.is_demo bool default false`、`display_order int`（ddl 78）；`bp_fund_risk` 重算口径（无 schema 变更）。
- 新 API：`GET /api/v1/market/data-freshness`；`GET /api/v1/market/mvi/overlay`；`GET /api/v1/valuation/indices?metric=`（替换旧慢接口）；`POST /api/baskets/{id}/recompute`（admin）；`GET /api/baskets?scope=demo|mine`。
- 新任务：valuation/latest 快照刷新、index_quotes_free、freshness 写入、daily audit 报告。
- 迁移：ddl/78（basket demo）、79（freshness/latest 表）。

## 验收与回滚
- 每阶段：`python -m pytest bp_api/tests -q` + `cd web && npm run typecheck && npm test && npm run build` + CI 绿。
- 数据阶段：对比修复前后 as_of、覆盖、clean 差异；保留旧 cron 备份（/opt/backup）；新 cron 可单独 disable。
- UI 阶段：feature flag（`NEXT_PUBLIC_UI_V2`）灰度页面，出现问题一键回滚到旧组件；migration 幂等。
- 监控：/admin/market-data 展示 8 类 SLA；失败告警。

## 时间估算
- P0：2-3 天（含验证）；P1：3-4 天；P2：2-3 天；P3：6-8 天（可分批上线）；P4 持续。
- 关键路径：P0-3 指数行情 → P0-4 clean → P0-6 freshness → P1-1 性能 → P3 设计系统。

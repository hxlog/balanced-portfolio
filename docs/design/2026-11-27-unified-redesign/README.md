# 全站整改方案 · 2026-11-27

> 目标：按用户 11 项反馈完成全站整改（数据层 + 产品功能 + UI/UX 重构）。
> 本目录是**对齐用文档 + 可点击原型**，未改动应用代码。确认后按 `implementation-plan.md` 分阶段并行开发。

## 目录
- `content-spec.md` —— 原型内容/交互/数据规格（三个视觉变体共用）
- `design-system.md` —— 全站 design token、组件、动效、loading 规范
- `product-prototype.md` —— 逐页面产品原型说明（含 11 项需求落点）
- `data-timeliness-plan.md` —— 数据层时效性审计结论、免费源聚合方案、SLA 与监控
- `implementation-plan.md` —— 分期实施计划、任务拆解、验收标准、风险与回滚
- `variants/v1-prologue-refined/`、`variants/v2-vercel-mono/`、`variants/v3-openai-airy/` —— 三套可点击 HTML 原型 + 截图
- `variants/index.html` —— 三套原型入口（待生成）

## 已确认的关键决策（本轮 Grilling 答复）
| # | 决策 |
|---|---|
| Q1 | 视觉主线 = C 混合（工作台），营销/文档页用 A 的留白 |
| Q2 | 红涨绿跌（A 股语义）；sky 保留但只用于主按钮/选中/链接；完整暗色 |
| Q3 | 轻动效（150-250ms，expo-out，尊重 reduced-motion）+ 14px 正文；loading 参考 prologue.dev |
| Q4 | 先出 3 方向 × 关键页静态 HTML 变体选择，再分页面池推广 |
| Q5 | “全局数据更新至”包含 8 类数据（A股/港股/ETF/基金/CFFEX/指数行情/指数估值/MVI），取最小完整日 |
| Q6 | Valuation Band 采用方案 B：预计算快照表 + Redis + gzip + 前端 metric 切换零请求；局部 loading |
| Q7 | 首批 4 只指数按钮 + 后续搜索；000985 接中证官网源，000510 接受 2024-09 起 |
| Q8 | MVI 允许全量重算（去周末点/交易日历/周频重采样）；固定权重 v1 保留，滚动重训列后续研究 |
| Q9 | MVI 展开图：默认中证全指 + 4 指数切换、双轴、hover 公式 |
| Q10 | 红利吸引力相对模式：30 只红利/股息指数，PB/股息率 5 年分位；绝对模式对数轴 |
| Q11 | HSI TE：净值用 acc_nav（缺失回退 ETF 后复权），基准 HSI 全收益（无源则价格×HKDCNY 标注），全量重算 |
| Q12 | HSI 空数据区块先隐藏 + 统一空态 |
| Q13 | Dashboard 模式条整行居中，组合下拉居中；内容列与 TOC 对齐 |
| Q14 | 示例篮子用 etl_a_stock 12 只核心资产，服务端重算，is_demo 语义，游客可读、复制需登录、仅 admin 可编辑 |
| Q15 | 只用免费源，尽可能聚合；不采购付费源/不搭代理池；全市场估值源先修，修不好先隐藏 |
| Q16 | 先出方案/原型/设计文档对齐，再 multi-agent 并行实施；P0 数据 → P1 估值/MVI/TE → P2 dashboard/basket → P3 UI 全站 |

## 本轮已完成的数据修复（生产）
- CFFEX T+0：修复 cffex.py 的 upsert 冲突键与事务回滚；contract/premium 已到 2026-11-27；新增 /etc/cron.d/bp-cffex 轮询。
- 估值/MVI 恢复：补跑估值 521 指数到 2026-11-27；MVI 重算到 11-27；新增 /etc/cron.d/bp-valuation 与调整 bp-mvi 到 23:50。
- 存量缺口见 data-timeliness-plan.md，属于 P0 实施范围。

# 指数估值与资产配置工作台 · 交付包

> 状态：**方案阶段完成，等待 Round 6 的 8 个决策后开工 P0**
> 生成：2026-11-14 ｜ 仓库：Balanced Portfolio ｜ 原型：[app/index2.html](../prototypes/app/index2.html)

## 一、这是什么

这是一套可直接进入实施的产品 + 技术方案包：从**数据源实测**、**数据字典**、**数据模型**、**PRD**、**原型**，到**可行性**、**排期**、**验收标准**、**代码审计标准**，覆盖 6 项原始需求（指数估值 PiT、etf.run 式页面、股票三复权、对外 API、篮子风险平价、加密合约看板）。

## 二、怎么读（推荐顺序）

| 顺序 | 文档 | 读者 | 用时 |
|---|---|---|---|
| 1 | [09-product-spec.md](09-product-spec.md) 产品说明书 | 你（决策） | 15 min |
| 2 | [05-master-plan.md](05-master-plan.md) 总体方案 | 你 + 实现者 | 20 min |
| 3 | [06-data-model-v3.md](06-data-model-v3.md) 数据模型 | 实现者 | 20 min |
| 4 | [12-schedule.md](12-schedule.md) 排期 | 你 | 10 min |
| 5 | [13-acceptance-and-test.md](13-acceptance-and-test.md) 验收 | 你 + 实现者 | 15 min |
| 6 | [14-code-review-standard.md](14-code-review-standard.md) 审计 | 实现者 | 10 min |
| 参考 | [01](01-recon-and-data-dictionary.md) 侦察与数据字典 · [02](02-decisions-log.md) 决策日志 · [04](04-quote-adjust-migration.md) 复权迁移 · [07](07-nextjs-performance.md) 性能审计 · [08](08-gap-review.md) 缺口复审 · [11](11-feasibility.md) 可行性 | — | 按需 |

> 编号说明：03 已合并进 02（Round 2 问题被逐条决策替代）；10 已合并进 09（功能说明即 PRD 第 5 章）。

## 三、已确认的 30 条决策（摘要）

| 领域 | 关键决定 |
|---|---|
| 数据源 | 多源聚合；**平安为一等源**（DB 标识来源，前端不显示）；中证官网作官方校验；国债用 akshare |
| 页面 | 卡片式首页；详情 D1 默认 + D2 移动端 + D3 专业模式；居中 1240px；涨跌色可切换默认跟全站 |
| 资产 | 股票全 A 三复权，默认后复权；存复权因子；退市股不展示但保留历史 |
| 组合 | 篮子模式 6 种方法；风险预算按分组 + 可展开；集中度 = 单资产 + 分组上限 |
| API | 全部需 token（admin 签发）；JSON/CSV；Excel 走 Power Query；Python SDK |
| 加密 | 并入 /crypto 上方；A3 分层（30 合约 5min + 其余日频）+ 分层配置表；Cloudflare Worker 转发 |
| 工程 | Next.js 16 性能审计 5 项修复；新增页面 5 条强制规范；13 周 7 个里程碑 |

完整列表见 [02-decisions-log.md](02-decisions-log.md)（D1~D30）。

## 四、五条硬指标

| # | 指标 | 阈值 |
|---|---|---|
| 1 | 521 指数日更覆盖率 | ≥ 99%（≥516/521），连续缺失 ≤ 2 个交易日 |
| 2 | 复权迁移前后 NAV | `max|Δ| < 1e-12`；多源差异 >20% 告警漏报 0 |
| 3 | API / 页面 | P99 < 300ms；首页 TTFB < 400ms、详情 < 500ms |
| 4 | 前端 | 390/768/1024/1440 零横向溢出；axe 0 critical；500 行滚动 ≥55fps |
| 5 | 工程 | 单路由 First Load JS 增量 ≤ 15KB；迁移连续执行 3 次 exit 0 且行数不变 |

## 五、原型

`docs/prototypes/app/index2.html` —— 15 屏可切换：估值首页 / 详情 D1·D2·D3 / 成分与业绩 / ETF 资金 / 股票三复权 A·B / 篮子 A·B·风险预算 / 加密总览·详情·/crypto 布局 / API 中心。皆居中布局、移动端适配、右下角涨跌色切换。

## 六、开工前只剩 8 个决策

Round 6（Q42~Q49）：产品定位、历史深度、估值择时回测、报告导出、域名与 SEO、P0 上线时间、收藏是否进 P0、Cloudflare 操作边界。

回复后即进入 P0：
1. 写 `ddl/51~56` 迁移 + 同步 `schema.sql`；
2. 按 TDD 拆 P0 任务（每个任务：失败测试 → 实现 → 通过 → 提交）；
3. 先跑 3 个 Spike（全 A 抓取耗时 / Excel 拉数 / Cloudflare 回传）。
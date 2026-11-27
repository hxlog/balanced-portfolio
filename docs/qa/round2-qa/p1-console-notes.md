# 生产匿名验收记录（qa-prod-a / p1-*，2026-11-28）

## 会话与范围
- 浏览器会话：agent-browser --session qa-prod-a（与另一 QA 的 qa-r2 隔离，避免互相导航）
- 生产：https://xushilu.com（HEAD 4863c2e），仅供参考/验收，未改代码、未部署
- 视口：1440x900；匿名（无 bp_session）

## 每步 console / page errors
| 页面/步骤 | console errors | page errors | 截图 |
|---|---|---|---|
| /valuation 首屏 | 0 | 0 | p1-01-valuation-top.png |
| /valuation 热力 hover | 0 | 0 | p1-02-valuation-heatmap-hover.png |
| /valuation 点击热力格（无筛选） | 0 | 0 | 同上 |
| /valuation 红利绝对/相对/回绝对 | 0 | 0 | p1-03/04/05 |
| /valuation 打开 MVI 图表（000300/000985） | 0 | 0 | p1-06/07 |
| /valuation 两张估值矩阵 | 0 | 0 | p1-08 |
| /valuation/000016 首屏 | 0 | 0 | p1-10 |
| 000016 成分饼图默认/切换 | 0 | 0 | p1-11/12 |
| 000016 PB 估值×点位 & 图例 | 0 | 0 | p1-13/14 |
| 000016 描述统计 asof 切换 | 0 | 0 | p1-15/16 |
| 000016 跟踪基金表头排序 | 0 | 0 | p1-17 |
| /builder?mode=basket&basket=4 载入/交互 | 0 | 0 | p1-20/21 |
| /builder 篮子 → 四象限（跳 /dashboard） | 0 | 0 | p1-22 |
| /dashboard?mode=basket → 四象限（本地切换） | 0 | 0 | p1-23/24 |

## 关键证据
- 旧文案：document.body.innerText 不含 "沪深300 ·"/"指标切换本地完成"/"· 数据截至"（0 次）；首次加载 HTML 同。
- 热力格点击：点击前后 "显示 60 / 374 只"、行业下拉 ""、URL 不变、无行业 chip。
- 红利：card 高 680.6px，图表 320px，上下留白各 140px；绝对模式 option yAxis min="dataMin"/max="dataMax"，数据 3.31%~6.14%，轴标签 3.3~6.0。
- MVI：/api/v1/market/mvi/overlay?index=000300 200；modal 宽 1152px（>=900）；series MVI 232 点 + 沪深300 1099 点（last 4063.06）；000985 200、34 点、不伪造。
- 矩阵：PB×股息率 yAxis.name="股息率（%）"，scatter 440 + 回归线；ROE×PE scatter 389 + log 回归线。
- 000016 饼图：默认 11 片（前10+其他20只），按钮 aria-pressed=true；点击后 30 片、false。
- PB×点位：legend data ["PB","指数点位"]，selectedMode=multiple；真实点击后 selected={"PB":false,...}，PB 线隐藏；图例右缘(local x≈103) 与右轴名(local x≈801) 不重叠。
- 直方图：默认 vs 沪深300 双系列；切换 000905 后 legend ["本指数","中证500"] 双 bar 系列。
- 跟踪基金：6 个可排序表头；点“规模”两次由默认 desc 变 asc（0.79 亿 → 203.80 亿）。
- 篮子：hfq 出现 14 次、bfq/qfq/前复权 0 次；7 张诊断卡齐全且非空；净值曲线 1574 点；无旧“回看”卡片（仅“回看窗口”参数标签）。游客切四象限 → /dashboard，无登录门禁。
- 问题证据：诊断/净值标题显示 “佣金 0.00% · 滑点 0.00% · 卖出印花税 0.00%”，但 GET /api/baskets/4 → latest_result.fees = {fee_rate:0.0003, slippage_rate:0.001, stamp_duty_rate:0.001,total_cost:0.0122}（应显示 0.03%/0.10%/0.10%）。组件 props 内 fees 值正确，为 formatPct 显示层阈值问题。

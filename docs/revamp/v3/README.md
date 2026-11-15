# v3 高保真原型（3 套风格）

生成脚本：`gen_prototypes.py`（`python docs/revamp/v3/gen_prototypes.py`）。

| 文件 | 风格 | 截图 |
|---|---|---|
| proto-a-light.html | 浅色工作台（默认推荐） | shot-1-valuation.png / shot-4-crypto.png |
| proto-b-dark.html | 深色终端 | shot-2-valuation.png / shot-5-crypto.png |
| proto-c-analyst.html | 分析师风（衬线/米色） | shot-3-valuation.png / shot-6-crypto.png |

每套包含 5 个界面 Tab：指数估值 / 指数详情 / 加密看板 / 资产池 / 场外定价。
技术规格：1600px 容器、纯静态 HTML+内联 SVG、无外部依赖。
确认风格后进入开发（见 docs/index-valuation/20-v3-master-plan.md）。

## 用户确认（2026-11-15 21:45）

- 风格：**A · 浅色工作台**（延续现有站点）；
- 密度：**更宽松**（正文 14px、卡片间距 18px、图表更高 16%）；
- 涨跌色：**红涨绿跌**（A 股习惯）；
- MVI：**双指数仪表盘**（估值分 27 / 风险分 68，双半环 gauge）；
- 说明：当前 HTML 原型为风格样本（单仪表盘）；最终实现按确认结论叠加密度与双仪表盘。

下一步：进入开发阶段 A（MVI 研究脚本 + /valuation 区块级 Suspense + 详情页重构），见 docs/index-valuation/20-v3-master-plan.md。
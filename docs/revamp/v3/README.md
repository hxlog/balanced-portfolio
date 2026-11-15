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

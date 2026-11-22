# Excel 行情自动刷新 · 验收报告（2026-11-22）

## 1. 结论

- **方案**：Power Query + XLOOKUP（.xlsx，无宏、无加载项、无付费数据源），数据来自自建
  balanced-portfolio 的 `/api/v1` 只读接口；打开工作簿自动刷新，失败保留上次数据。
- **MS365 Python in Excel 判定**：官方文档明确 *"The Python code doesn't have network access."*，
  不能联网取数；且家庭/个人版仍是 preview。故 Python in Excel **不参与取数**，只在取数后分析时有用。
- **数据源**：自有库（A 股/港股/ETF/指数/基金净值/汇率/指数估值/分位）为唯一事实源；
  免费源（腾讯/新浪/东财）只用于落库，不在 Excel 侧混用口径。

## 2. 工作簿改动（`C:\Users\Xingyu Liu\OneDrive\Investment.xlsx`）

| 位置 | 改动 |
|---|---|
| 隐藏表 `BP_Config` | 表 `BpConfig`（BaseUrl / Token），token 只在此处 |
| 隐藏表 `BP_Quotes` | 查询 `bp_market_last`（13 列，含 date/status） |
| 隐藏表 `BP_FX` | 查询 `bp_fx`（pair/date/price） |
| `持仓` 表 | `现价` = XLOOKUP；新增 `行情日期`；H~L 加 IFERROR；现价陈旧条件格式；表下说明 |
| `Accounts!Forex` | 4 个货币对恢复文本；`Price`/`日期` = XLOOKUP |
| 新可见表 `BP_行情` | 10Y 国债收益率；沪深300/中证A500/中证500/上证50 的 PE/PB/股息率/ERP/5年分位 |
| 查询刷新属性 | 4 个连接均 `RefreshOnFileOpen=True`、`BackgroundQuery=False`、`FastCombine=True` |

备份：`OneDrive\Investment.backup-20261122.xlsx`（修改前生成）。

## 3. 交叉校验（表内原现价 vs 接口现价）

接口：`GET /api/v1/market/last?codes=...&adjust=bfq`（**只读库内已落库收盘价**，不做盘中兜底）。

| 代码 | 市场 | 原现价 | 接口 close | 行情日期 | 结果 |
|---|---|---|---|---|---|
| 001914 | SZ | 8.16 | 8.16 | 2026-11-20 | ✅ |
| 002352 | SZ | 33.57 | 33.57 | 2026-11-20 | ✅ |
| 002714 | SZ | 44.85 | 44.85 | 2026-11-20 | ✅ |
| 601318 | SH | 55.46 | 55.46 | 2026-11-20 | ✅ |
| 159915 | ETF | 2.23 | 2.23 | 2026-11-20 | ✅ |
| 02020 | HK | 81.05 | 81.05 | 2026-11-20 | ✅ |
| 02714 | HK | 38.8 | 38.80 | 2026-11-20 | ✅ |
| 06936 | HK | 30.2 | 30.20 | 2026-11-20 | ✅ |
| 02390 | HK | 6.21 | 6.21 | 2026-11-20 | ✅ |
| 01358 | HK | 0.865 | 0.865 | 2026-11-20 | ✅ |

**10/10 完全一致**；工作簿 12 行（含重复代码）全部带 `行情日期=2026-11-20`。
汇率：USD/SGD 1.288915、USD/HKD 7.830089、USD/CNY 6.6714、HKD/CNY 0.852021（同一交易日，交叉汇率由人民币腿计算）。

## 4. 后端接口（已上线 xushilu.com）

| 端点 | 用途 | 口径 |
|---|---|---|
| `GET /api/v1/market/last` | Excel 现价 | 库内最新日线，bfq，原币；返回 date/status |
| `GET /api/v1/market/history` | 历史日线（A股/港股/ETF/指数） | 原币、可选 bfq/qfq/hfq |
| `GET /api/v1/market/fx` | 汇率 | 人民币腿 fx_sina，交叉汇率 A/CNY÷B/CNY |
| `GET /api/v1/fund/nav` | 场外基金净值 | bp_fund_nav_daily，latest 或区间 |
| 既有 5 个端点 | 行情/估值/分位/详情/国债 | 语义未改 |

代码：`bp_api/quote_store.py`（统一代码解析与跨市场读取）、`bp_api/market_last.py`、`bp_api/market_extra.py`；
测试：`bp_api/tests/test_market_api.py`（35 用例）；全量后端 551 passed / 3 skipped。

## 5. ETL 最终状态（2026-11-22 18:45）

| 数据 | 状态 |
|---|---|
| A 股 5,227 只 × bfq/qfq/hfq | ✅ 日更 cron 23:35 正常，最新 2026-11-20 |
| 港股主数据 2,811 只 | ✅ 列表完整；bfq **2,803** / qfq **2,808** / hfq **2,808**（缺口为长期停牌/退市无行情代码） |
| ETF/LOF/封闭式 1,392 只 | ✅ 列表完整；bfq/qfq/hfq **各 1,392 = 100%**（bfq 新浪源；qfq/hfq 腾讯 K 线，成交量已统一为「股」） |
| 场外基金 28,072 只 | ✅ 11-16~11-20 每日约 2.47~2.58 万只有净值（其余为封闭/清盘/未到披露日）；覆盖率 28,065 |
| 汇率 | ✅ 11 对（含新增 SGDCNY），最新 2026-11-20 |
| 覆盖快照 | ✅ stocks=28,088 / funds=28,065 / etfs=4,176 / indices=692 |

cron 已安装：港股日更 23:40、ETF 23:45、港股周更周日 02:40、ETF 周更 02:50、基金净值 22:30、覆盖 23:55。
每日行情由腾讯快照（`--source auto` 优先）写入，腾讯 K 线被 WAF 时切 `proxy.finance.qq.com` 或新浪。

## 6. 经验与坑（后续维护必读）

1. 腾讯 `web.ifzq.gtimg.cn` 与 `ifzq.gtimg.cn` 在高频批量下会返回 **HTML 501 WAF**；
   现脚本按 `proxy.finance.qq.com/ifzqgtimg/...` → `ifzq` → `web.ifzq` 顺序回退，并内置全局限速。
2. 东财 push2his 对服务器 IP 直接掐断（TLS 指纹），仓库已有 `curl_cffi` 硬化会话可复用。
3. 本机直连生产库（`BP_ETL_DB_HOST=81.71.158.239`）可跑回填；但并发受 WAN 往返限制，服务器执行更快。
4. `bp_index_config.config_id` 是 identity 列，迁移里禁止显式赋值（74 号已修）。
5. 家庭/个人版 Excel 的 Python in Excel 是 preview 且无网络，**不要**把它设计进取数链路。

## 7. 收尾修复记录（18:00-18:45）

1. **腾讯 WAF 应对**：`web.ifzq` / `ifzq` 的 `fqkline` 路径会被限流返回 HTML 501；脚本改为
   host/端点回退（`proxy.finance.qq.com`、`newfqkline`），并给所有请求加**总耗时上限**
   （`bp_ingest/http_deadline.py`，防 WAF 慢速滴流把线程挂死）。
2. **ETF 成交量口径**：腾讯/东财 K 线成交量单位为「手」，统一 ×100 换算为「股」；
   清理了 611,143 行旧口径腾讯 bfq 行（bfq 以新浪源为准，qfq/hfq 用腾讯源）。
3. **/market/history 去重**：同一 (code, date, adjust) 多源重复按优先级保留一条
   （腾讯/中证/东财 > 其他 > 新浪），并在 `test_market_api.py` 增加回归用例。
4. **港股回填进程崩溃修复**：失败清单引用了未定义变量 `code`，已修复（此前会中断整批任务）。
5. **基金净值空洞**：新增 `--fill-days` 覆盖率补洞模式，11-16~11-19 从 1.0~1.1 万只补到 2.47~2.58 万只。
6. **supervisor 脚本**：`/tmp/etl_supervisor.sh`（服务器）按「港股 bfq → ETF qfq/hfq → 港股 qfq/hfq」
   顺序重试，失败自动续跑（脚本本身支持断点续传）。

## 8. 最终复核命令与结果

```bash
# 后端全量测试
python -m pytest bp_api/tests -q          # 552 passed, 3 skipped
python -m bp_ingest --help                # 冒烟通过

# 生产接口
GET /api/v1/market/last?codes=…           # 10/10 close/date/status=ok，price_basis=last_confirmed_close
GET /api/v1/market/history?codes=159915,02020.HK&start=…   # 4 行无重复（tencent/sina 去重生效）
GET /api/v1/market/fx?pairs=USD/CNY,HKD/CNY,USD/HKD,USD/SGD # 4 对 2026-11-20
GET /api/v1/fund/nav?codes=000001,510300&latest=true        # 2026-11-20 nav
```

工作簿复核（Excel COM，真实文件）：
- `持仓` 12 行现价 + 行情日期=2026-11-20，与上表 10/10 一致；
- `Accounts!Forex` 4 对价格+日期正确；
- `BP_行情` 10Y 国债 1.5755%（2026-11-19）+ 4 个宽基指数 PE/PB/5 年分位；
- 4 个查询、3 张隐藏表、`RefreshOnFileOpen=True`、`FastCombine=True` 均已持久化。

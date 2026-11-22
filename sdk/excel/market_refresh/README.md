# Excel 行情自动刷新（Investment.xlsx）

让 `Investment.xlsx` **打开即自动刷新**持仓现价与汇率：Power Query 拉取
`https://xushilu.com/api/v1/*`，用 XLOOKUP 写入工作表；数据口径与 balanced-portfolio
一致（**只读库内已确认收盘价、不复权 bfq、原币计价**，不做盘中实时兜底）。

## 1. 工作簿里新增了什么

| 位置 | 内容 | 说明 |
|---|---|---|
| 隐藏表 `BP_Config` | 表 `BpConfig`：`BaseUrl`、`Token` | 换 token / 域名只改这里 |
| 隐藏表 `BP_Quotes` | 查询 `bp_market_last` 输出 | 列：`code_raw, code, market, currency, kind, name, date, close, prev_close, pct, adjust, source, status` |
| 隐藏表 `BP_FX` | 查询 `bp_fx` 输出 | 列：`pair, base, quote, date, price, source` |
| `持仓` 表 | `现价` 改为 XLOOKUP；新增 `行情日期` 列；H~L 公式加 IFERROR | 数据缺失时留空而不是 `#VALUE!`；`现价` 有陈旧高亮 |
| `Accounts!Forex` | `Currency Pair` 恢复为 4 个文本货币对；`Price`/`日期` 改为 XLOOKUP | 支持 USD/SGD、USD/HKD、USD/CNY、HKD/CNY |
| 可见表 `BP_行情` | 查询 `bp_bond_yield`（10Y 国债）+ `bp_index_valuation`（宽基 PE/PB/股息率/ERP/5 年分位） | 二期中金所风格数据面板 |

刷新行为：两个/三个 QueryTable 均设置 **打开文件时刷新**、**后台刷新关闭**、数据随工作簿保存。
失败（断网、token 失效、接口 5xx）时 Excel 保留上一次结果，不会清空；`行情日期` 列
可直观看出是否陈旧（`现价` 会被条件格式标橙）。

## 2. 一键重建 / 首次安装

前置：Windows 桌面版 Excel（Microsoft 365），工作簿保存在 OneDrive（Python in Excel 与
查询刷新都要求本地文件可写）；已签发只读 API token（scopes: `quotes`，建议再加 `valuation`）。

```powershell
# 1) 先备份（脚本内也会 SaveCopyAs 一份）
Copy-Item "$env:USERPROFILE\OneDrive\Investment.xlsx" "$env:USERPROFILE\OneDrive\Investment.backup-$(Get-Date -Format yyyyMMdd).xlsx"

# 2) 注入 A 期（持仓现价 + 汇率）
$env:BP_EXCEL_TOKEN = "bp_live_xxx"
python sdk/excel/market_refresh/apply_market_queries.py "$env:USERPROFILE\OneDrive\Investment.xlsx" --attach "--backup=$env:USERPROFILE\OneDrive\Investment.backup.xlsx"

# 3) 注入 B 期（10Y 国债 + 宽基估值/分位）
python sdk/excel/market_refresh/apply_valuation_sheet.py "$env:USERPROFILE\OneDrive\Investment.xlsx" --attach
```

`--attach` 表示复用**已经打开**的 Excel 实例（工作簿正开着时使用）；不加则用独立隐藏实例打开、改完关闭。
`--token=...` 可替代环境变量；`--base-url=` 可指向自建域名。

## 3. 刷新与口径

- 手动刷新：`Ctrl+Alt+F5`（全部刷新）或 数据 → 全部刷新；打开工作簿自动刷新一次。
- 现价口径：`/api/v1/market/last` 返回**库内最新一条日线**（bfq、原币），
  `date` 字段即数据日期；A 股/ETF/港股/指数自动识别（`IDX:` 前缀可强制指数）。
- 行情数据由服务器 crontab 每日落库：A 股 23:35、港股 23:40、ETF 23:45、基金净值 22:30
  （详见 `docs/data/asset-pool-etl.md`）。Excel 打开时若当日尚未落库，会显示上一交易日的收盘价与日期。
- 汇率：`/api/v1/market/fx`，人民币腿来自 `fx_sina`，交叉汇率按同一交易日 `A/CNY ÷ B/CNY` 计算。
- 指数估值/分位：`/api/v1/index/valuation`、`/api/v1/index/percentile`（5 年窗口，0~100%）。

## 4. 常见问题

| 现象 | 处理 |
|---|---|
| 刷新报 401 | token 失效/被撤销：在 `BP_Config!B3` 换新 token，或重跑注入脚本 |
| 刷新报 Formula.Firewall | 工作簿已设置 `Queries.FastCombine=True`；若仍出现，数据→查询选项→隐私→忽略隐私级别 |
| 首次刷新弹凭据 | 选择「匿名」（token 在 Authorization 头里） |
| 现价整列空白 | 查询刷新失败且此前从未成功：检查网络/域名/token；`BP_Quotes` 表是否为空 |
| 某行空白但其他正常 | 该代码库内无行情（如停牌/新上市未落库）：查看 `BP_Quotes[status]` 与 `meta.unknown` |
| 想恢复原始工作簿 | 用 `Investment.backup-*.xlsx` 覆盖（先关闭 Excel） |

## 5. 维护

- 轮换 token：`BP_Config!B3` 改值即可（或重跑注入脚本）。
- 新增持仓：直接在 `持仓` 表末尾加行（代码列填裸代码即可），刷新后 `现价/行情日期` 自动出现。
- 新增自选/指数：在 `BP_行情` 的查询 M 代码里改 `Codes`（`000300,930641,000905,000016`）。
- 不要删 `BP_Config`/`BP_Quotes`/`BP_FX` 三张隐藏表；`BP_行情` 可改样式但不要删查询表。

## 6. 相关文件

- 接口契约：`docs/API.md`（`market/last`、`market/history`、`market/fx`、`fund/nav`）
- ETL 与口径：`docs/data/asset-pool-etl.md`、`docs/data-sources.md`
- 后端实现：`bp_api/market_last.py`、`bp_api/market_extra.py`、`bp_api/quote_store.py`
- 注入脚本：本目录 `apply_market_queries.py`、`apply_valuation_sheet.py`

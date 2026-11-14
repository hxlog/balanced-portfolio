# 指数估值系统 · 侦察报告与数据字典 v1

> 生成时间：2026-11-14 ｜ 状态：**待用户确认（Grilling Round 1）**
> 范围：需求 1（平安指数估值全量抓取 PiT）、需求 2（etf.run 指数估值复刻）、需求 3（股票三复权）、需求 4（对外 API）、需求 5（篮子风险平价）、需求 6（加密多空看板）的数据面。

---

## 一、现有系统数据资源盘点（生产库 postgres@100.75.138.35）

### 1.1 已有事实表与规模

| 表 | 用途 | 实测规模 |
|---|---|---|
| `bp_index_quote_daily` | 原始 OHLCV（TimescaleDB hypertable） | 12 个 source；主流源 2017-01-03 ~ 2026-11-13 |
| `bp_quote_clean` | 回测唯一口径（CNY 折算 + 交易日历对齐 + 插值） | 同上，派生 |
| `bp_index_config` | 资产池（软删） | 279 条有效：etf 118 / index 87 / commodity 49 / bond 13 / forex 11 / crypto 1 |
| `bp_data_source` | 20 个数据源注册（akshare 适配器） | 含 `etf_tx`/`index_tx`（腾讯 fqkline，已支持 fq 复权参数） |
| `bp_trading_calendar` | A 股交易日历 | 全量 |
| `bp_crypto_*` | 加密看板预计算（corr/price/meta） | 日频，NYSE 对齐，原生 USD |
| `bp_cffex_*` | 中金所升贴水预计算 | 日频 |
| `bp_portfolio*` / `bp_backtest_*` | 组合与回测结果 | 4 方法 × N 基准 |

**关键结论**
- 现有资产池 **只有 63 个 A 股指数**（+118 只 ETF），而平安「指数信号灯」有 **521 个指数**；etf.run 列出 351 个。**估值功能必须新建独立的「指数估值域」，不能只依赖 `bp_index_config`。**
- `bp_index_quote_daily` 主键含 `(symbol, source, trade_date)`，**没有 adjust 维度** → 同一代码的前复权/后复权/不复权会撞主键。股票三复权必须用「独立 source 后缀」（如 `stock_em_hfq`）或新增 adjust 列（见 §六，待选）。
- 现有 `etf_tx`/`index_tx` 已走腾讯 `tencent_fqkline`，**复权链路已验证**，股票源可复用。

### 1.2 现有看板/接口形态（复刻模板）
- `/crypto`：Server 壳 + `CryptoClient` 客户端岛；页头 + 快照卡 + 摘要卡 + 双 Y 轴图 + 分位表；预计算表 + `cacheTag("crypto")` + `revalidateTag("crypto","hours")`。
- `/cffex`：指数 4 卡 + 合约表 + 升贴水历史图 + 分位条。
- **铁律**：请求路径永不计算；`effective_td` 必须「当日所需标的齐全 + 收盘确认」才推进；缓存失效 profile 必须与 `cacheLife` 一致。

---

## 二、需求 1：平安证券指数估值（PiT 全量）

### 2.1 页面与接口清单（已实测打通，匿名可访问）

**入口 A：指数信号灯** `GET https://m.stock.pingan.com/omm/phonex/indexZone/light.html`
**入口 B：指数 F10 详情** `GET .../omm/phonex/page/index.html?key=INDEX_F10_H5&type=ZI&code=930641`

| # | 接口 | 方法 | 说明 |
|---|---|---|---|
| E1 | `/omm/v2/http/mop/vault/query` `key=INDEX_DATA` | POST form | 一页拉全市场 521 个指数的主指标（含 peBar 5 年周频序列） |
| E2 | `…vault/query` `key=INDEX_DATA_V2&codes=ZI930641` | POST form | 单指数全字段（含 pbBar/didHis/roeTrace/profitTrace/bond10/风险溢价字段） |
| E3 | `…vault/query` `key=A_INDEX_DESCRIPTION` | POST form | 指数简介/全称/基日/基点/编制方/收益处理方式/加权方式 |
| E4 | `…vault/query` `key=A_INDEX_VALUATION` | POST form | 成分股数量 conNum、总市值 mvTotal |
| E5 | `…vault/query` `key=S_INDEX_PERFORMANCE` | POST form | 阶段收益 1w/1m/3m/6m/1y/2y/3y/发布以来 + 年化波动 + 夏普（1/2/3 年） |
| E6 | `…vault/query` `key=BOND10_TREND` | POST form | 十年期国债到期收益率全历史（1463 行，2017→今）→ 风险溢价基准 |
| E7 | `quote.stock.pingan.com/restapi/nodeserver/quote/kLineDate` | POST form | 日/周/月/分钟 K 线（`kLineType=7` 日线，`cqFlag=2`，`count=300`） |
| E8 | `quote…/quote/quoteIndex` / `realTimeData` | POST form | 实时行情快照 |
| E9 | `/omm/v2/http/shelf/queryOnsiteFundInfoList` | POST form | 跟踪 ETF/联接基金全字段（公司、规模 `positionDTO.fnvsum`、经理、阶段收益/排名、风险等级） |
| E10 | `/omm/v2/http/shelf/query/queryPlateQuotationCommon` | POST JSON | 板块/指数通用报价（closePrice 等，价格需 /100） |
| E11 | `/omm/v2/http/base/omm_pss_dynCard/queryAppDynCardInfoByCardIdList` | GET | 场外基金动态名片（近 1 年收益率等） |

> 请求特征：`POST form-urlencoded`，`key=<数据视图名>&fields=<逗号分隔字段>&wheres[n].field=…&pageSize=999`；**匿名可调用**，但需带移动端 UA + Referer（否则可能被风控）。这意味着**接口可脚本化直采**。

### 2.2 字段字典（E1/E2 合并，521 个指数，实测字段覆盖率）

#### 2.2.1 标识与分类
| 字段 | 中文 | 类型 | 样例 | 覆盖率 | PiT |
|---|---|---|---|---|---|
| `code` | 平安内部代码 | text | `ZI930641` / `SH000300` / `SZ399997` / `HKHSI` / `IXSPX` | 521/521 | 静态 |
| `indexName` | 指数简称 | text | 中证中药 | 521 | 静态 |
| `indexType` | 类型 | enum | 宽基 58 / 策略 87 / 主题 349 / 其他 19 / 全球 6 | 519 | 低频变 |
| `sInfoWindCode` (E3) | Wind 代码 | text | `930641.CSI` | 全 | 静态 |
| `sInfoIndexType` | 指数类别 | text | 股票类 | 全 | 静态 |
| `sInfoPublisher` | 编制方 | text | 中证公司 | 全 | 静态 |
| `weightTypeName` | 加权方式 | text | 市值加权\|调整市值加权 | 全 | 低频变 |
| `indexIntro` | 简介 | text | … | 442/521 | 低频变 |
| `sInfoCompany` | 指数全称 | text | 中证中药指数 | 全 | 静态 |
| `sInfoIndexBaseper` | 基日 | date | 20041231 | 全 | 静态 |
| `sInfoIndexBasept` | 基点 | num | 1000 | 全 | 静态 |
| `sInfoIncomeMethod` | 收益处理方式 | enum | 价格指数/全收益/净收益 | 全 | 静态 |
| `conNum` (E4) | 成分股数量 | int | 39 | 全 | 月度变 |
| `mvTotal` (E4) | 总市值(元) | num | 649055339228 | 全 | 日变 |

#### 2.2.2 估值指标（核心）
| 字段 | 中文 | 单位 | 样例 | 覆盖率 | 备注 |
|---|---|---|---|---|---|
| `peRatio` | 市盈率 PE(TTM) | 倍 | 23.27 | 457 | — |
| `pePercen` | PE 百分位(近5年) | % | 13.68% | 470 | 页显「低于 86.32% 历史交易日」 |
| `peLevel` | PE 分级 | enum | 较低/中等/较高 | 470 | 低/中/高三档标签 |
| `peBar` | PE 历史序列 | text `date,pe|…` | 周频 2021-11-19→今（约 260 点） | 457 | **可直接重建历史 PE 曲线与分位** |
| `highPe`/`lowPe`/`lowPE` | 历史最高/最低 PE | 倍 | 31.14 / 25.7 | 全 | — |
| `pbRatio` | 市净率 PB | 倍 | 2.02 | 470 | — |
| `pbPercen` | PB 百分位 | % | 2.72% | 470 | — |
| `pbLevel` | PB 分级 | enum | 较低 | 470 | — |
| `pbBar` | PB 历史序列 | text | 同 peBar 结构 | 分接口返回 | E2/E184 带回 |
| `isPb` | 是否 PB 有效 | 0/1 | 0 | 全 | 部分指数无 PB |
| `dividendRate` | 股息率 TTM | % | 3.68% | 440 | **页面只给比率，接口原始为比率字符串** |
| `dividendLevel` | 股息率分级 | enum | 较低 | 471 | — |
| `didHis` | 股息率历史序列 | text `date,yield|…` | 周频 260 点 | E2 | — |
| `didPercent` | 股息率分位 | % | 4.98% | 全 | — |
| `highDid`/`lowDid` | 历史最高/最低股息率 | % | 1.72 / 2.74 | 全 | — |
| `bond10` | 十年期国债收益率 | % | 1.6123 | 全 | **风险溢价 = 股息率 − bond10** |
| `peg` / `pegLevel` | PEG 及分级 | 倍 | 4.58 / 较高 | 384 | — |

#### 2.2.3 盈利/成长/风险
| 字段 | 中文 | 单位 | 样例 | 覆盖率 |
|---|---|---|---|---|
| `roe` | ROE(TTM) | % | 8.63 | 403 |
| `roeLevel` | ROE 分级 | enum | 中等 | 519 |
| `roeTtm`/`roeTtmHis` | ROE(TTM)/历史 | % | — | 分接口 |
| `roeGrow` | ROE 同比增速 | % | -0.89 | 全 |
| `roeGpercent` | 同比增长率(百分比口径) | % | 32.01% | 全 |
| `roeGrowlv` | ROE 增速分级 | enum | 较低 | 全 |
| `roeTrace` | ROE/ROA 年度序列 | text `year,roe,roa|…` | `2021,10.77,6.99|…|2026Q3,8.63,5.52` | 全 |
| `profitTrace` | 营收/净利年度序列 | text `year,a,b|…` | `2021,44.8,10.56|…|2026Q3,40.42,9.86` | 全 |
| `profitBar` | 净利润年度柱 | text `year,profit|…` | `2022,265.49|…|2027E,308.06` | 393 |
| `profitExpection` | 净利增速预期 | text `year,abs,yoy%|…` | `2026E,-0.06,-3.6` | 全 |
| `profitY1`/`incomeY1` | 净利/营收同比 | ratio | -3.6 / -0.06 | 全 |
| `volatility` / `volatilityLevel` | 波动率及分级 | % | 1.32% / 中等 | 415 |
| `sharpRatio` / `sharpLevel` | 夏普比率及分级 | % | -39.48% / 较低 | 415 |
| `riseLastday/Week/Month/3Months/6Months/Year` | 涨跌幅 | % | -0.29% | 474 |
| `stdDev1y/2y/3y` (E5) | 年化波动(小数) | ratio | 0.011979 | 全 |
| `sharpratio1y/2y/3y` (E5) | 夏普(1/2/3年) | 倍 | -0.951485 | 全 |
| `pctChgRecent1w…3y` / `siPctChg` (E5) | 阶段收益 & 发布以来 | % | — | 全 |
| `marketShow`, `updateDate` | 展示标记 / 更新日 | — | 1 / 20261114 | 全 |

#### 2.2.4 成分股与关联产品
| 字段 | 中文 | 格式 | 样例 |
|---|---|---|---|
| `stockList` | 前 30 大成分股 | `code,name,weight%\|` | `SZ000538,云南白药,10.76%\|…` |
| `etfFund` | 跟踪 ETF 代码 | 逗号分隔 | `SH560080,SZ159647,SH561510` |
| `otcFund` | 场外/联接基金代码 | 逗号分隔 | `501012,501011,016892,016891` |
| E9 基金字段 | 基金名/公司/规模/经理/收益/排名/风险等级 | JSON | `companyName=鹏华基金`, `positionDTO.fnvsum=881155037.2`（规模，元）, `riskGrade=R4`, `oneYearYield=-15.02` |

### 2.3 由上述字段可派生（etf.run 同款指标）
- PE/PB/股息率 **历史分位**（20%/50%/80% 分位点、当前分位、均值、最高/最低）
- **风险溢价** = `dividendRate − bond10`（接口已给 +2.07% 与 bond10，可直接校验）
- **极限跌幅水位**：70%/80% 水位线点位（用收盘价与历史最高价算）
- **距历史最高**、52 周涨跌
- **全市场/板块估值**：需额外全 A 股 PE/PB 聚合（见 §七 缺口）

### 2.4 PiT 建模要点（关键设计）
1. **双时间轴**：`as_of_date`（数据对应的交易日，如 2026-11-13）+ `captured_at`（我们抓取/入库的时间）。每日 21:00 快照天然形成 PiT；历史回补时 `captured_at` = 回补时间，必须记录，否则会出现「回补数据伪装成当时数据」的前视偏差。
2. **不可覆盖原则**：同一 `(symbol, as_of_date)` 的估值若被供应商修订，保留旧行并标记 `revision`，查询默认取最新 revision（可切换）。
3. **复权口径**：指数点位为价格指数（`sInfoIncomeMethod=价格指数`），股息率/TTM 与点位无关；风险溢价用指数自身股息率，不用全收益。
4. **序列转存储**：`peBar/pbBar/didHis/roeTrace/profitTrace` 是「周频/年度」压缩串，入库时应**拆行存明细表**（长表），否则无法做任意窗口分位。周频序列 → 明细表 `(symbol, as_of_date, pe)`，可再用日频估值补齐。
5. **缺失即缺失**：521 个指数里 peRatio 只有 457、stockList 399、etfFund 374 → 覆盖率载荷入 `meta`，前端不得用 0 填充。

### 2.5 抓取任务设计（已实测验证）
**结论：全量抓取极轻，每日约 10~20 个 HTTP 请求即可完成，不构成瓶颈。**

| 数据视图 | 实测能力 | 每日请求数 |
|---|---|---|
| `INDEX_DATA` | 一次返回 521 个指数（pageSize=999） | 1 |
| `INDEX_DATA_V2` | 支持批量 `codes=`（实测 10 个/次正常，上限待压测） | 46（或 23） |
| `S_INDEX_PERFORMANCE` | **一次分页拿全 439 行** | 1 |
| `A_INDEX_VALUATION` | **一次拿全 494 行** | 1 |
| `A_INDEX_DESCRIPTION` | **全表 1398 行可翻页** | 1~2 |
| `BOND10_TREND` | 全历史 1463 行（2017→今） | 1 |
| `queryOnsiteFundInfoList` | 按 `codeList` 批量 | 约 20~40 |
| `kLineDate` | 单 code 300 根，`count` 可调 | 可选（价格可复用现有源） |

- **无需浏览器**：纯 `requests` 匿名可调（移动端 UA + Referer + X-Requested-With 即可），不需要指纹/登录。
- 限速建议 2~3 req/s + 随机抖动；失败重试 3 次指数退避；落 `bp_data_refresh_run` 审计。
- 存储估算：521 指数 × 250 日 × 约 40 指标 ≈ 5.2M 行/年（窄表）；宽表 130k 行/年。**建议「日频宽表 + 历史序列长表」双层**。
- 历史回补：`peBar/pbBar/didHis` 首拉即可回填 **近 5 年周频**（约 260 点/指数）；更早历史平安不提供（见 G2）。

---

## 三、需求 2：etf.run 指数估值模块功能清单（逐模块）

### 3.1 首页 `/`
| 区块 | 内容 | 字段/交互 |
|---|---|---|
| 全市场估值 `#market-valuation` | 4 张卡：全市场 / 主板 / 创业板 / 科创板 | 每卡：市盈率 + 分位、市净率 + 分位、更新日 |
| 宽指估值 `#broad-index-valuation` | 表格（7 行：上证50/沪深300/科创50/中证1000/中证500/创业板指/中证2000） | 指数、收盘价、涨跌幅、52周涨跌、历史最高、距历史最高、PE、PE分位、PB、PB分位、股息率、分析链接 |
| 全部指数估值 `#index-list` | 351 行全表 | 同上 + Like 收藏 |
| 顶部导航 | 指数估值 / 接入 AI / 持仓管理 / 更多工具 | — |

### 3.2 详情页 `/index/{market}/{code}`
| Tab/区块 | 内容 | 细节 |
|---|---|---|
| 左：主图 | PE + 指数点位双轴折线 | 时间范围：上市以来 / 近10年 / 近5年；工具提示 |
| 右：市盈率 | 估值分布直方图（历史区间/当前区间/等分线）+ 估值百分位卡 | 当前分位、20%/50%/80% 分位、最新/最高/最低/均值 |
| 右：市净率 | 同上 | 同上 |
| 右：股息率 | 最新股息率（历史走势/分布/分位为 Pro） | — |
| 右：指数权重 | 成分股权重（前 8 合计占比 + 条形图）、一级行业权重（申万一级，可切换） | 每月第一天更新 |
| 右：成分股业绩 | 业绩增长中位数（滚动同比，营收/净利双线，季度） | — |
| 右：极限跌幅 | 收盘点位、距最高点跌幅、70/80 水位线点位与距收盘涨跌 | — |
| 顶部 Tab：ETF 异动 | 净申购跟踪（时间序列）+ ETF 申购明细表 | 列：名称/代码、当日净申购额、净申购率、净资产、折溢价率（连续两日） |
| 顶部 Tab：网格策略 | （本次**不做**） | — |

> 结论：需要新增 **指数权重（成分股/行业）+ 成分股业绩 + ETF 申购赎回** 三类数据，均需独立数据源。

---

## 四、需求 3：股票资产类别（三复权）

- 目标：至少 50 只热门股（顺丰控股 002352、招商积余 001914、招商银行 600036、牧原股份 002714、工商银行 601398 …）以 `stock` 类别进入资产池，支持前复权/不复权/后复权，**默认偏好后复权（全收益）**。
- 数据源：`ak.stock_zh_a_hist(adjust=qfq|hfq|"")`（东财）/ 腾讯 `tencent_fqkline`（现成适配器）。
- 主键冲突：现有 `(symbol, source, trade_date)` 无 adjust 维度 → 方案见 Q3。
- 资产 key 建议：`600036@stock_em_hfq` / `600036@stock_em`（bfq）/ `600036@stock_em_qfq`，前端展示为「招商银行（后复权）」。

---

## 五、需求 4：对外数据 API（类 Wind/iFinD/Choice）

### 5.1 已明确要支持的能力
| 能力 | 入参 | 出参 |
|---|---|---|
| 日行情查询 | `code`, `start`, `end`, `adjust` | date, open, high, low, close, volume, amount, pct_change, turnover |
| 指数估值区间统计 | `code`, `window=1/3/5/10y` | 当前值 + 分位 + 均值 + ±1/2/3σ |
| 风险溢价 | 同上 | 股息率 − 十年国债，及其分位/均值/σ |
| 资产元数据 | — | 名称、类别、复权口径、数据区间、数据源 |

### 5.2 接口形态（待选，见 Q5）
- OpenAPI 词汇建议：`GET /api/v1/market/daily?codes=600036&start=2024-01-01&end=2024-12-31&adjust=hfq`，返回 `{"data":[...], "meta":{...}}`，CSV 用 `?format=csv` 或 `Accept: text/csv`。
- 鉴权：`Authorization: Bearer bp_xxx`（服务端只存 hash）；可选 `X-API-Key` + HMAC 签名（Wind 风格）。
- 需同时给 **Excel 插件/宏** 与 **Python SDK**（`bpdata.daily(...)`）。

---

## 六、需求 5 & 6 的数据面

- **篮子风险平价**：纯定义层改动（`bp_portfolio_asset.quadrant='basket'` 伪象限或新方法 `basket_risk_parity`），无新数据表。
- **加密多空比看板**：需新增预计算表 `bp_crypto_longshort_daily`（多空人数比 / 大户持仓比 / 主动买卖比 / 未平仓量金额），数据源 Binance Futures 公开数据（`/futures/data/globalLongShortAccountRatio` 等，免费、限频 1000 req/5min/ip）；**5 分钟刷新 = 实时链路，与现有日频预计算架构不同**（见 Q8）。

---

## 七、缺口清单（必须决策）

| # | 缺口 | 现状 | 可选路径 |
|---|---|---|---|
| G1 | 全市场/板块 PE/PB 历史 | 无 | ①每日抓全 A 股快照自建历史（只能从今天起积累）②第三方历史（韭圈儿/乐咕）③用指数加权近似 |
| G2 | 指数估值历史 >5 年 | 平安只给 5 年周频 | ①接受 5 年 ②中证官网/乐咕补 ③付费源 |
| G3 | 指数全成分股（含权重、行业） | 平安只给前 30 | ①中证官网 Excel 月度 ②东财板块成分 ③付费 |
| G4 | 成分股财务（营收/净利/ROE） | 平安给年报序列（聚合） | ①复用平安聚合值 ②自算（需全成分股财报） |
| G5 | ETF 净申购/折溢价/规模 | 无 | ①东财 ETF 份额与净值 ②上交所/深交所每日申赎清单 |
| G6 | 十年期国债收益率历史 | 现有 `bond_csi_treasury` 是债券指数，非收益率 | 平安 `BOND10_TREND`（1463 行）可直接采，或中债官网 |
| G7 | 股票三复权的存储维度 | 主键无 adjust | ①source 后缀 ②新增 adjust 列（破坏主键/索引）③独立表 |
| G8 | 对外 API 的限频/配额/计费 | 无 | 见 Q5 |

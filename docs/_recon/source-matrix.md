# 公开数据源矩阵：指数估值 PiT 系统

研究时间：2026-11-14（Asia/Shanghai）；目标包：本仓库 `.venv` 中
`akshare==1.18.64`。本文件区分了**本机实测**与**适配器源码可确定的
schema**。后者不是返回值实测，不能替代上线前的连通性验收。

## 实测前提与原始结果

这次执行不能获得任何远端数据行，原因不是接口返回空表，而是环境与网络均
不可用；因此不能诚实地填写虚构的行数、日期范围或样例。

| 项目 | 实测命令/结果 |
|---|---|
| 指定解释器 | `& .\\.venv\\Scripts\\python.exe -c "import akshare"` 失败：`did not find executable at C:\\Users\\Xingyu Liu\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe`。`pyvenv.cfg` 的 `home/executable` 也均指向该不存在路径。 |
| 可用替代解释器 | 系统仅发现 Python 3.8、3.12；3.12 可加载 venv 的纯 Python `requests 2.34.2`，但不能加载 3.14 ABI 的 pandas/akshare。 |
| 东方财富 HTTP | 用 Python 3.12 + venv requests 请求 `push2his.eastmoney.com/api/qt/stock/kline/get`：`ProxyError: RemoteDisconnected('Remote end closed connection without response')`。PowerShell 到 csindex/eastmoney 也报 SSL 连接无法建立。 |
| 八个原始 URL 重试 | 对 CSIndex 三个 indicator xls、乐咕、东财、SSE、SZSE、申万端点的 Python 逐个 20s 超时重试在 30s 调度上限内未返回任何响应；记录为网络挂起，非 0 行。 |
| 反射替代 | 因 `import akshare` 无法执行，以 Python 3.12 `ast` 扫描本地 1.18.64 的全部 `.py`：名称含 `pe/pb/value/indicator/valuation/roe` 的函数 52 个；下面只列金融上有意义者。此为**静态反射替代**，非运行时 `inspect`。 |

**结论边界**：本次不能满足“逐项已取回样例”的严格验收条件。下面所有“实测
行数=未取得”均应在修复原解释器和出网后重新跑一次；已把应验证的列名、端点和
主键明确到可直接落地。

## 源矩阵表

| 数据源 | akshare 函数/URL | 数据内容（适配器 schema） | 主键/唯一键 | 频率 | 历史起点 | 实测行数 | 稳定性 | 增量更新方式 | 限速/风控 |
|---|---|---|---|---|---|---:|---|---|---|
| 中证指数估值 | `stock_zh_index_value_csindex(code)`；`https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls` | 日期、指数代码、中英文全称/简称、PE1、PE2、股息率1、股息率2 | `(指数代码, 日期)`；代码原样保留 | 日 | 文件滚动窗口，待复测 | 未取得（000300/930641/H30374 全部网络失败） | 中；裸 xls 路径易变、境内 SSL/超时 | 每日下载并 upsert；保存原始 xls hash；若仅窗口，T+1 落库 | 无公开配额；单线程、指数间 ≥1s、失败退避 |
| 中证指数历史行情 | `stock_zh_index_hist_csindex`；`/csindex-home/perf/index-perf?indexCode=&startDate=&endDate=` | 日期、代码、名称、OHLC、涨跌、量额、样本数、滚动市盈率 | `(code, 日期)` | 日 | 参数可请求 2010 起（实际范围待测） | 未取得 | 中；同域 | 按最后日期+1 回补；可用来验证估值文件日期 | 低频、缓存 |
| 乐咕指数 PE | `stock_index_pe_lg(symbol)`；`/api/stockdata/index-basic-pe` | 日期、指数、等权静态PE、静态PE、静态PE中位数、等权滚动PE、滚动PE、滚动PE中位数 | `(LG 映射的指数代码, 日期)`，不能以中文名为键 | 日 | API 全历史，具体首日待测 | 未取得 | 低~中；cookie+每日 token+CSRF | 首次全量；之后 `max(date)` 之后 upsert，保留修订最近 10 日 | 必须先取页面 cookie/CSRF；限 1 req/s；403/解析变更报警 |
| 乐咕指数 PB | `stock_index_pb_lg(symbol)`；`/api/stockdata/index-basic-pb` | 日期、指数、市净率、等权市净率、市净率中位数 | `(LG 指数代码, 日期)` | 日 | 待测 | 未取得 | 同上 | 与 PE 同批抓取 | 同上 |
| 乐咕全 A TTM/LYR | `stock_a_ttm_lyr()`；`/api/stock-data/market-ttm-lyr` | 原始 JSON 的 `date` 及等权/中位数估值字段（需实测列） | `date` | 日 | 待测 | 未取得 | 低~中 | 每日滚动积累；不能由快照回补 | token+CSRF；限速 |
| 乐咕个股指标 | `stock_a_indicator_lg(symbol)`；`/api/stock-data/stock-?`（适配器内 token/CSRF） | 个股 PE、PB、股息率及历史序列；最终列须运行确认 | `(股票代码, 日期)` | 日/财报更新 | 待测 | 未取得 | 低；页面反爬 | 全量按股票分片，日更最近 N 日 | 高风险：token、cookie、频率控制 |
| 东财指数行情 | `index_zh_a_hist(symbol, period)`；`push2his.../stock/kline/get` | 日期、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率 | `(secid, 日期)`；`secid=市场ID.6位代码` | 日/周/月 | 指数上市日（参数本身不限制） | 未取得 | 中~高 | `beg=last_date` 后重拉并覆盖最近 5 日 | 无公开配额；批量节流，代码市场映射每日缓存 |
| 东财 A 股快照 | `stock_zh_a_spot_em()`；`82.push2.eastmoney.com/api/qt/clist/get` | 代码、名称、最新价、量额、换手率、**市盈率-动态**、**市净率**、**总市值**、**流通市值**等共 23 列 | `(股票代码, 快照时间/交易日)`；代码还需市场 | 实时快照 | 不适用 | 未取得 | 中 | 每日 21:00 存一版；不可从当前接口回补历史估值 | 分页接口，控制并发；字段 f9/f23 缺失要记 NULL |
| 东财 ETF 快照 | `fund_etf_spot_em()`；`push2delay.../clist/get` | 代码、名称、价量、**IOPV实时估值**、**基金折价率**、**最新份额**、流通/总市值、数据日期、更新时间等 37 列 | `(ETF代码, 更新时间)`；另存市场 | 实时 | 不适用 | 未取得 | 中 | 盘后/21:00 快照；IOPV 仅当时有效 | 延迟行情、无承诺；不能高频轮询 |
| 东财 ETF K线 | `fund_etf_hist_em(symbol, period, adjust)`；`push2his.../stock/kline/get` | 日期、OHLC、成交量/额、振幅、涨跌幅/额、换手率、（原始 f116 总市值） | `(ETF市场.代码, 日期, 复权方式)` | 日/周/月 | ETF 上市日 | 未取得 | 中~高 | 初次全取；随后重取最近 10 日 | `get_market_id`: 5/6 开头 SH=1，其余多为 SZ=0；例外需验证 |
| 上交所 ETF 份额 | `fund_etf_scale_sse(date)`；SSE `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L` | 序号、基金代码、基金简称、ETF类型、统计日期、基金份额 | `(基金代码, 统计日期)` | 日（指定日期） | 官网可查询范围待测 | 未取得 | 中；官方、SQL id 可能改 | 每日传交易日；首次二分/逐日回补验证 | Referer/UA 必需，低频、重试 |
| 深交所 ETF 份额 | `fund_etf_scale_szse()`；`fund.szse.cn/api/report/ShowReport` | 基金代码、简称、类别、投资类别、上市日期、基金份额、管理人/发起人/托管人、净值 | 当前快照键 `(代码, 抓取日)`；接口不带历史日期 | 当前 | 无历史参数（待实测） | 未取得 | 中 | **只能每日滚动积累**；不能由该 API 回补 | Referer/UA；xlsx 格式可能变 |
| ETF 净申购 | 用户点名的 `fund_etf_fund_daily_em`、`fund_etf_fund_info_em` | **1.18.64 顶层无这两个函数**；不应假定存在 | 无 | - | - | 不适用 | 不可用 | 改用 SSE 份额差分（近似） | 份额差不等同净申购，见缺口 |
| 十年国债收益率 | `bond_zh_us_rate(start_date)`；东财 `RPTA_WEB_TREASURYYIELD` | 日期、中国2/5/**10**/30年、10-2、中国GDP；美国2/5/10/30年等 | `日期` | 日 | 函数默认 1990-12-19（真实可用首日待测） | 未取得 | 中~高 | 以日期分页，重拉最近 10 个交易日 | `ps=500` 分页；避免每日全表 |
| 申万一级概览 | `sw_index_first_info()`（实际源为乐咕页面） | 行业代码、行业名称、成份个数、静态PE、TTM PE、PB、静态股息率 | `(申万行业代码, 快照日)` | 快照 | 不适用 | 未取得 | 低~中（HTML CSS selector） | 每日存快照；历史需自己积累 | HTML 解析脆弱、限速 |
| 申万成分 | `index_component_sw('801xxx')`；SW `component_stocks` | 序号、证券代码、证券名称、最新权重、计入日期 | `(申万指数代码, 证券代码, 抓取日)`；“计入日期”不是完整生效区间 | 当前 | 无历史参数 | 未取得 | 中 | **只能每日/调仓日快照积累**，保留 hash | UA，单指数串行 |
| 东财行业板块/成分 | `stock_board_industry_name_em`、`stock_board_industry_cons_em` | 板块代码 BKxxxx、名称、行情；成分接口返回股票代码/名称及实时字段 | `(BK代码, 股票代码, 抓取日)` | 当前 | 无 | 未取得 | 中 | 每日快照积累；不可得到历史归属 | 先名称表再取成分；限速 |

### CSIndex 专项：三个代码与估值口径

对 `000300`、`930641`、`H30374` 的三条 xls URL 均已发起请求，但本机未能 TLS
握手，故**未能确认**行数、实际日期窗口、样例值，也没有证据支持“只含最近 20
交易日”这一断言。适配器把 xls 强制命名为 10 列；其自身没有对 PE1/PE2 作语义
解释。

可作出的保守判定是：中证指标文件通常为“估值指标 1/2”的发布口径，而不是
AKShare 计算口径；在拿到中证当期《指数估值指标说明》或文件表头前，不能把它们
标签为“静态/滚动”或“加权/等权”。应以同一 `930641`、同日的乐咕字段作数值
匹配来验证：PE1/PE2 分别与 `静态市盈率/滚动市盈率` 的相对误差连续比对；若均
不匹配，再检查是否为加权平均、成分股中位数、剔除负值规则不同。股息率同理，且
应检查是否为过去12月现金股利/价格，还是预测股息率。H 开头代码尤其要先确认是
价格、净/全收益还是策略指数，不能和同号价格指数混用。

历史尝试的下一步是 `stock_zh_index_hist_csindex` 的 `index-perf`（它可返回行情及
“滚动市盈率”，不是指标 xls 的完整估值历史）。若 indicator 文件确为滚动 20 日，
该官方行情接口也不能回补 PE/PB/股息率；这部分必须从首次可用日开始归档，或取得
发行方授权历史文件。

## 估值/PE/PB/股息率/ROE 函数清单与可用性

静态 AST 扫描得到 52 个名称命中；剔除 `opec/personal_spending/append` 等误命中后，
与本系统有关的清单如下。所有“运行实测”在本轮均为失败，不能把 schema 当可用性
承诺。

| 函数 | 产物 | PiT 可用性结论 |
|---|---|---|
| `stock_zh_index_value_csindex` | 中证指数 PE/股息率滚动文件 | 值得优先接入；需解决网络并验证窗口/口径 |
| `stock_index_pe_lg` / `stock_index_pb_lg` | 12 只固定指数的多口径 PE/PB 历史 | 可作指数估值历史主补充；受 token/CSRF 约束，覆盖很窄 |
| `stock_market_pe_lg` / `stock_market_pb_lg` | 上/深/创/科市场历史 | 可作市场层指标，不是任意指数 |
| `stock_a_ttm_lyr` | 全 A 等权/中位数 PE | 可作全市场分位基准；需滚动落库 |
| `stock_a_indicator_lg` | 个股 PE/PB/股息率 | 候选；逐股抓取成本和反爬高，先抽样验收 |
| `stock_a_all_pb` | A股 PB（第三方） | 备用；先核对更新与历史 |
| `stock_value_em` | 东财个股估值相关 | 快照性质，适合当日，不适合回补 |
| `stock_zh_valuation_baidu` / `stock_hk_valuation_baidu` / `stock_us_valuation_baidu` | 百度估值历史 | 备用，口径和稳定性待实测 |
| `stock_hk_indicator_eniu` | 港股 PE/PB/股息率/ROE/市值 | 港股候选；不适用于 A 股指数 |
| `stock_industry_pe_ratio_cninfo` | 巨潮行业 PE | 行业交叉校验候选 |
| `stock_zh_valuation_comparison_em` / `stock_hk_valuation_comparison_em` | 估值对比 | 辅助，不作 PiT 主源 |
| `stock_financial_analysis_indicator[_em]`、`stock_financial_hk_analysis_indicator_em`、`stock_financial_us_analysis_indicator_em` | 财报指标（可能含 ROE） | 可重建个股基本面，但需公告期/可得期建模 |
| `bond_zh_cov_value_analysis`、`option_value_analysis_em` | 可转债/期权估值 | 与指数估值无直接关系 |

`fund_etf_fund_daily_em` 与 `fund_etf_fund_info_em` 不在该安装版本导出的 API 内；实际
应使用 `fund_etf_scale_sse` / `fund_etf_scale_szse`，或明确升级版本后再重新反射确认。

## 关联键研判与归一化

推荐 canonical key 为 `instrument_code + '.' + market`，并把发布方代码和显示名放到
别名表，不把中文名当键。

| 对象 | 规范键例 | 来源输入 | 对齐规则/冲突 |
|---|---|---|---|
| CSI 指数 | `000300.CSI`、`930641.CSI`、`H30374.CSI` | CSIndex 原样代码 | `bp_index_config.symbol=000300, source=csindex` 映射为 `.CSI`。不要因为乐咕写 `000300.SH` 就合并为同一“发布方序列”；须以指数名称、基日、规则验证。 |
| 上证/深证指数 | `000300.SH`、`399006.SZ` | 乐咕映射、东财 `secid` | 东财 market id 仅是路由，不等价于标准后缀；`000300` 可同时有 `000300.SH` 与 `000300.CSI`，绝不可仅按六位 join。 |
| A股 | `600000.SH` / `000001.SZ` / `430xxx.BJ` | 东财代码+市场、申万成分 | 6位代码+交易所；申万的 `stockcode` 需补市场映射。 |
| ETF | `510300.SH` / `159919.SZ` | SSE/SZSE/东财 ETF | 不能仅用前缀判市场作最终事实；以上市交易所为准。 |
| 申万行业 | `801010.SW` | SW 指数代码 | 独立资产类，不与东财 `BKxxxx.EM` 强行一一映射。 |
| 东财板块 | `BK1027.EM` | 板块代码 | 仅作东财分类层，分类口径不同于申万。 |

归一化流程：保留原始 `source_code`、`source_name`、`as_of_date`；建立
`instrument_alias(source, source_code, canonical_id, valid_from, valid_to)`；历史 join
必须带 `valid_from/to`，从而允许改名、调仓、同六码多发布方。`H` 开头代码不表示
“普通 A 股指数”：在 alias 中显式记录 `return_type=price/net_total/gross_total/unknown`，
未确认时禁止与价格指数做收益或估值横比。

## 字段语义对照与平安接口比对

| 字段 | 已能确定的语义 | 不能确定/风险 |
|---|---|---|
| 乐咕 `lyrPe/addLyrPe/middleLyrPe` | 适配器明确映射为等权静态、静态、静态中位数 PE | 负盈利剔除、加权权重细节要看乐咕计算规则 |
| 乐咕 `ttmPe/addTtmPe/middleTtmPe` | 映射为等权滚动、滚动、滚动中位数 PE | 同上 |
| CSIndex `市盈率1/2` | 仅知是 xls 的第7/8列 | 本轮无文件表头/说明，**不可断言**静态/TTM或加权/等权 |
| CSIndex `股息率1/2` | 同理为第9/10列 | 不可断言静态/预测、税前/税后、权重法 |
| 平安 `peRatio/dividendRate` | 名称不足以判断；应视为供应商自定义字段 | 不可与上述任一字段直接等同，必须版本化保存原始字段说明 |

可验证方案（取得网络后）：同一交易日抓 `930641.CSI` 的原始 xls 和平安
`peRatio/dividendRate`，同时抓乐咕相近指数的八个 PE 列。对每一配对计算
`abs(a-b)/abs(b)`，连续 60 日 <1e-4 才可暂定同口径；若仅比例常数相同，检查百分数
vs 小数；若仅在调仓日偏离，检查成分生效时点。把“口径版本、下载时间、原始文件
hash”写入事实表，禁止后来用新口径覆盖旧日值。

## 缺口与替代

| etf.run 类指标缺口 | 是否能用公开源完整重建 | 可行平替 |
|---|---|---|
| 全市场历史估值分位 | 否（快照不回溯、口径会变） | 从首日每日存东财全A/乐咕全A；之后以本库 expanding/rolling percentile。历史以前只能标“样本期不足”。 |
| 成分股业绩中位数/ROE | 否（需要历史成分、财报披露可得日、复权基本面） | 每日归档申万/指数成分，抓公告与财报指标，按公告可得日 lag 做 PiT；或将其降级为当期横截面。 |
| ETF 净申购 | 否（份额变化还包含拆分、合并、分红、跨市场/申赎时点差） | SSE 每日份额差分作为“净份额变化 proxy”，结合公告校正；SZSE 从今天起快照积累。不能声称为资金净流入。 |
| ETF IOPV/折溢价历史 | 否（东财接口是实时快照） | 盘中/收盘定时采集并自建历史；若只做日频，记录 14:55/15:00 的观测时间。 |
| 任意 CSI 指数全量 PE/PB/股息率历史 | 否，若 xls 为短窗口 | 每天归档从可得日起；有限覆盖指数可用乐咕补，其他须官方授权/商业源。 |

## 增量方案（每日 21:00 + 一次性回补）

1. 21:00 先取交易日历，再按顺序取：CSIndex xls → 东财指数/ETF K线 → 东财 A股、ETF
   快照 → SSE 份额 → SZSE 份额 → 乐咕 → 申万/东财分类快照 → 国债。每批保存
   `fetched_at`、原始响应 hash、HTTP 状态、行数、最小/最大日期；空表/列变更直接失败。
2. 可回补：东财指数/ETF K线按上市日至今分段；国债按分页；乐咕 PE/PB 在其 API 返回范围内；
   中证 `index-perf` 行情。均采用 `(canonical_id,date,source,field_version)` upsert，并重拉最近
   10 个交易日处理修订。
3. **只能滚动积累**：CSIndex indicator（若证实短窗口）、东财 A/ETF 快照的估值和 IOPV、SZSE
   ETF 份额、申万和东财成分归属、ETF 净申购 proxy。首日建立基线，不伪造回补历史。
4. 一次性回补须先建立 alias/市场映射，然后以小批量、指数/股票级 checkpoint 运行；失败只重试
   该 checkpoint。每日任务应对每源独立降级，不能因为乐咕失败而阻断价格更新。

## 上线前最小验收脚本要求

修复 `.venv` 的原始 Python 3.14 后，对每个上表函数输出：函数名、参数、`shape`、
`columns.tolist()`、首/末日期、`head(2).to_dict('records')`、请求时间、异常文本。对三个
CSIndex xls 额外记录文件 content-length、sheet 名、原始表头、行数与最小/最大日期；只有那时
才能回答“是否最近20日”“覆盖多少指数”及 PE1/PE2/股息率1/2 的官方口径。

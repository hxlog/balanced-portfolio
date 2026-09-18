# 数据源复权口径与可达性（单一事实表）

> 维护时间：2026-09-01（实盘探测，非文档假设）。修改 ETF/指数取数前先看本表，避免混用复权口径污染收益序列。

## ETF 三源复权能力

| 源 | 适配器 | 不复权 | 前复权 qfq | 后复权 hfq | 绝对价口径 | 历史深度 |
|---|---|---|---|---|---|---|
| 东财 `fund_etf_hist_em` | `etf_em` | ✅ | ✅ `adjust=qfq` | ✅ `adjust=hfq` | **价格**（如 511580≈109） | 全量 |
| 腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get` | `etf_tx` | ✅ | ✅ `qfqday` | ✅ `hfqday` | **单位累计净值**（每份 1.0 起步，如 511580 hfq=1.097） | 约 3200+ 日（800/页分页） |
| 新浪 `fund_etf_hist_sina` | `etf_sina` | ✅ | ❌（需 `qfq.js` 因子合成，未实现） | ❌（需 `hfq.js` 因子合成，未实现） | 价格（不复权） | 全量 |

## 指数（不复权，代码通用性）

- **东财 `cn_index_em`** 直连 push2his（`90.xxx` 中证 / `1.xxx` 上证 / `0.xxx` 深证）。
- **新浪 `stock_zh_index_daily`**、**腾讯 `stock_zh_index_daily_tx`**：主流宽基指数代码通用（`sh000300` 等），值与东财一致。
- **例外（反例）**：中证系小众指数（`930050/930651/930713/930719/930758/930782/930997/931775/931865/932000/932365/H30269/H30352/H30356`）**新浪/腾讯均无等价代码**，只有东财有；东财 IP 封禁时只能走「源受限」标记。`980092` 例外，新浪 `sz980092`/腾讯有数据。
- 海外指数（`孟买SENSEX`/`富时100` 等）存在命名入参差异（中文名→em 系列 / 英文 sym→sina 系列），仍分源。

## 复权口径结论（关键约束）

1. **后复权 hfq 是唯一回测/入库口径**（前复权 qfq 泄露未来函数，见 CLAUDE.md 回测端约束）。
2. **同复权口径下，各源绝对价仅差一个常数倍**（累计收益率相同）——东财 hfq 用「价格」，腾讯 hfq 用「单位累计净值」，两者日收益率一致、绝对价不同。
3. 因此多源聚合**绝不混用绝对价**：降级源按「重叠日收盘比值」重锚到主源口径（`_align_fallback_to_base`）；主源整段失败时用库中最后收盘作锚点（`fetch_with_fallback(..., anchor_close, anchor_date)`）缩放降级源。
4. 聚合链（`AGGREGATE_CHAINS`）：
   - `etf_em → etf_tx`（adjust 由 `extra_params.adjust` 驱动）
   - `cn_index_em → cn_index_sina → cn_index_tx → index_tx`
   - `hk_index_em → hk_index_sina`、`global_index_em → global_index_sina`
5. 新浪 ETF 无复权，**不纳入 hfq/qfq 聚合链**（只有 etf_em/etf_tx 提供真正复权）。

## 汇率（CNY 折算的唯一口径）

非 CNY 计价资产在**清洗阶段**（`bp_api/quant/cleaning.py`）折算为人民币，`bp_quote_clean.close` 落折算后价格，`fx_rate` 落所用汇率。汇率来源**只有新浪一个**：

| 项 | 值 |
|---|---|
| 适配器 | `fx_sina`（`bp_ingest/sources.py` 直连，非 akshare 封装） |
| 端点 | `https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_{sina_sym}=/NewForexService.getDayKLine?symbol={sina_sym}` |
| 代码 | `{币种}CNY` → `fx_s{币种小写}cny`，如 `USDCNY` → `fx_susdcny` |
| 返回 | `var _fx_susdcny=("日期,开,低,高,收,|...");`，行尾一个空字段 |
| 列序 | **date, open, low, high, close** —— 全量 8021 行实测：候选「开,高,低,收」只有 2811/8021 行满足 `低 ≤ 开,收 ≤ 高`，候选「开,低,高,收」为 8020/8021（唯一例外是新浪自身脏行 2011-10-03）。close 恒为第 4 个数值字段，两种候选一致 |
| 已入库标的 | `USDCNY`/`HKDCNY`/`JPYCNY`（DDL 43）+ `EURCNY`/`GBPCNY`/`AUDCNY`/`KRWCNY`/`INRCNY`/`RUBCNY`/`BRLCNY`（DDL 45，按资产池实际币种补齐）。均 `is_selectable=FALSE` 不进 /builder 可选池；由 `bp_ingest.db.fetch_active_configs` 的调度路径显式纳入 |
| 覆盖 | 实测 USD 1994-08-30 起、HKD/JPY 2002-11-05 起；EUR/GBP/AUD/KRW/INR/RUB/BRL 均有新浪**直接**人民币报价。`VNDCNY` 新浪有报价但精度仅 4 位小数（≈0.00027 恒为 0.0000）**不可用**，`fx_susdvnd` 也只有「越南盾兑美元」而非兑人民币，故 **VND 无可用汇率对**；`越南胡志明` 因此无法折算，其清洗表被整体清空（`MissingFxRate(total=True)`），管理端显示为无数据 —— **不要把该资产加入任何组合** |

**不聚合**：用户已实测新浪「人民币汇率」与中行牌价（`akshare.currency_boc_sina`）是**两套口径**——USD 日变动相关 0.149、HKD 0.109、EUR 0.053，±2 日移位检验排除日期错位。因此 `AGGREGATE_CHAINS` **不注册** `fx_sina`，汇率是单一事实源，无降级链。

折算口径（决策与理由见 `cleaning.py` 模块头）：
1. **先折算再插值**——折算因子按日精确取值，与插值无关；先折算使插值发生在同一币种的序列上。
2. **OHLC 同时乘汇率**——收益率/协方差/回撤必须与 close 同口径。
3. **volume 不折算**（股数/手数无币种）。
4. **无汇率日不处理**——不 ffill、不外推；该日不产出清洗行，并删除上一轮残留行。
5. **尾部护栏**——汇率落后资产价格超过 4 自然日则抛 `MissingFxRate` 中止该资产本轮清洗（保留上一轮完整结果），避免净值静默截断。
6. **不做美元三角合成**——直接用新浪对各币种的**直接报价**（`{币种}CNY`），比三角合成少一层误差。目前资产池里唯一无可用直接报价的是 VND（精度不足），该资产整表清空、管理端显示为无数据，绝不静默以原币混入。
7. **`crypto_yfinance` / `dxy_em` / `gold_comex_em` 不折算**——其 close 的原生计价单位就是 `/crypto` 看板的展示口径（「BTC 价格 (USD)」），折算会静默改变该看板与相关性口径；这些行 `fx_rate` 为 NULL。**但它们在 `/builder` 里是可选的**（`is_selectable=TRUE`）：一旦加进组合，就是把一条原币序列混进 CNY 折算面板 —— 若要彻底杜绝，需在 `list_assets` 里排除这三个 source 或前端置灰。
8. **`/crypto` 的相关性面板在读侧还原美元价**——标普500/纳斯达克走 `global_index_em`，其 close 在清洗阶段已被折算成人民币；`bp_ingest/crypto_corr.py::_load_close(usd_native=True)` 用 `fx_rate` 除回去，保证该看板（含 sp500/nasdaq 与 BTC 的相关系数）是美元口径。不做这一步的话标普500 快照会显示 52643 而非真实的 7799。

## 反爬事实

- 东财 navigate 基于 **TLS 指纹(JA3)** 掐断 Python 请求（`RemoteDisconnected`）；curl_cffi `chrome120` 伪造指纹是关键。
- **cookie 对封锁无效**（IP 级封锁），已删除所有 cookie 注入/预热/刷新代码与 `BP_EM_COOKIE`/`BP_SINA_COOKIE`/`BP_COOKIE_REFRESH_MIN`。
- 减少调用：保留 `BP_REQUEST_INTERVAL/JITTER` 限速 + 「已最新则本地 skip」交易日护栏（`ingest._sync_one`）。
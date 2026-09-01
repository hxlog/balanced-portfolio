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

## 反爬事实

- 东财 navigate 基于 **TLS 指纹(JA3)** 掐断 Python 请求（`RemoteDisconnected`）；curl_cffi `chrome120` 伪造指纹是关键。
- **cookie 对封锁无效**（IP 级封锁），已删除所有 cookie 注入/预热/刷新代码与 `BP_EM_COOKIE`/`BP_SINA_COOKIE`/`BP_COOKIE_REFRESH_MIN`。
- 减少调用：保留 `BP_REQUEST_INTERVAL/JITTER` 限速 + 「已最新则本地 skip」交易日护栏（`ingest._sync_one`）。
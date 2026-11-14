# Binance Futures 全量数据接口调研

> 调研时间：2026-11-14（本机 Windows / 腾讯云广州部署场景）。范围为 USDⓈ-M 公开 REST；所有实测均为只读请求。数量、上市合约和限额应在上线前再次以 `exchangeInfo`/官方文档核验。

## 可达性结论

| 主机 / 请求 | DNS | TLS / HTTP 实测 | 结论 |
|---|---:|---|---|
| `fapi.binance.com/fapi/v1/ping` | 14 ms，`128.242.240.155` | HTTP 200，813 ms，`{}` | 本机可用 |
| `www.binance.com/fapi/v1/ping` | 缓存命中，`162.125.80.3` | HTTP 200，358 ms，`{}` | 本机可用，非推荐主入口 |
| `data.binance.vision/.../` 目录 | 58 ms，4 个 CloudFront IP | TLS 1.3 76 ms；目录 HTTP 404 / 588 ms | 对象地址可用，目录枚举不支持 |
| Vision K 线 ZIP / aggTrades ZIP | — | HEAD 均 200：54,209 B / 3,116,010 B | 归档可用 |

直接 `TcpClient` 到前两个主机在 10 秒超时、但系统 HTTPS 代理请求成功；这说明本机网络路径经代理，不能据此推断腾讯云广州可直连。生产必须以广州 egress 做同样探针；若失败，采用下文境外 Worker 转发。`www.binance.com/fapi` 是可用兼容路径，但正式采集只用 `fapi.binance.com`，并保留健康切换。

实测 `/fapi/v1/exchangeInfo`：HTTP 200 / 736 ms，946 个总 symbol，其中 **659 个 `contractType=PERPETUAL` 且 `quoteAsset=USDT`**。示例 BTCUSDT 含 `symbol, contractType, onboardDate, pricePrecision, quantityPrecision`，及 `PRICE_FILTER(tickSize)`、`LOT_SIZE(stepSize/minQty/maxQty)`、`MARKET_LOT_SIZE`、`MIN_NOTIONAL`、`PERCENT_PRICE` 等 `filters`。服务器返回的 REQUEST_WEIGHT 为 2,400/min（另有订单限额，采集无关）。

## 接口清单表

除特别标注外均为 `https://fapi.binance.com`。`startTime/endTime` 均应以 UTC 毫秒、按最后一条时间戳向前/后翻页；不要假定返回恰好填满 limit。

| endpoint | 数据 / 频率参数 | limit、历史深度 | weight / 实测字段样例 |
|---|---|---|---|
| `/fapi/v1/exchangeInfo` | 合约元数据；每小时/变更时 | 无；当前全量 | 1；`symbols[].symbol,contractType,onboardDate,pricePrecision,quantityPrecision,filters` |
| `/fapi/v1/klines` | OHLCV；`1m,5m,15m,1h,4h,1d`（另有更多周期） | max 1,500；单次时间跨度最多 200 天；REST 可从上市日分页 | limit `<100/ <500/ <=1000/ >1000` 权重 1/2/5/10；`[openTime,o,h,l,c,volume,closeTime,quoteVol,trades,takerBuyBase,takerBuyQuote,ignore]` |
| `/fapi/v1/fundingRate` | 历史资金费率 | max 1,000；上市以来分页（与 fundingInfo 合计 500 req/5min/IP） | 1；`symbol,fundingTime,fundingRate,markPrice,rateType` |
| `/fapi/v1/premiumIndex` | 当前标记/指数/下一次资金费率；不带 symbol 可一次取全量 | 单点当前 | 单 symbol 1、全量 10；`markPrice,indexPrice,lastFundingRate,interestRate,nextFundingTime,time` |
| `/fapi/v1/openInterest` | 当前未平仓张数 | 当前快照，无历史 | 1；`symbol,openInterest,time` |
| `/futures/data/openInterestHist` | OI 与美元价值；`5m,15m,30m,1h,2h,4h,1d` | default 30、max 500；**最近 30 天** | Data API weight 0，但共享 1,000 req/5min/IP；`sumOpenInterest,sumOpenInterestValue,CMCCirculatingSupply,timestamp` |
| `/futures/data/globalLongShortAccountRatio` | 全市场多/空账户数比；`5m,15m,30m,1h,2h,4h,6h,12h,1d` 全部实测 200 | max 500；最近 30 天 | 同上；`symbol,longAccount,shortAccount,longShortRatio,timestamp` |
| `/futures/data/topLongShortAccountRatio` | 大户账户数多/空比；同上周期（全实测 200） | max 500；最近 30 天 | 同上；字段同 global |
| `/futures/data/topLongShortPositionRatio` | 大户持仓量多/空比；同上周期（全实测 200） | max 500；最近 30 天 | 同上；字段同 global |
| `/futures/data/takerlongshortRatio` | 主动买/卖量比；同上周期（全实测 200） | max 500；最近 30 天 | 同上；`buySellRatio,buyVol,sellVol,timestamp` |
| `/futures/data/basis` | 基差；`pair,contractType,period` | max 500；最近 30 天 | Data API；必须带 `contractType`，漏传虽 HTTP 200 但 JSON `status=ERROR, code=200001054`；实测 `pair,contractType,indexPrice,futuresPrice,basis,basisRate,annualizedBasisRate,timestamp` |
| `/fapi/v1/aggTrades` | 聚合成交，微观主动方可由 `m` 推导 | max 1,000；按 `fromId` 或时间分页，短窗；长期改 Vision | 20；`a,p,q,nq,f,l,T,m`（实测 `m=true`） |
| `/fapi/v1/depth` | L2 盘口快照 | 5/10/20/50/100/500/1000 | 权重 2/2/2/2/5/10/20；`lastUpdateId,E,T,bids,asks` |
| `/fapi/v1/ticker/24hr` | 滚动 24h 行情 | 单 symbol 或全量 | 单个 1、全量 40；`lastPrice,volume,quoteVolume,highPrice,lowPrice,count,openTime,closeTime` |
| `/fapi/v1/liquidationOrders` | 用户指定的旧路径 | — | **实测 404，已不可用**；`allForceOrders` 与 `/futures/data/forceOrders` 亦 404；不能以 REST 设计强平历史 |

`/futures/data/`（USDⓈ-M 公共文档可用的数据序列）即：`openInterestHist`、上述三类 long/short account/position ratio、`takerlongshortRatio`、`basis`；均只有近 30 天，不能当历史归档。逐项实测 BTCUSDT、limit=1 时四种比率九种 period 均 200；5m 最新示例：global `0.7573/0.2427/3.1203`，top-account `0.7827/0.2173/3.6019`，top-position `0.6648/0.3352/1.9832`，taker `buyVol=130.2530,sellVol=152.8060,buySellRatio=0.8524`。

## 历史归档、增量与回补策略

Vision 已实测可下载：

```
data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2023-01-01.zip
data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2023-01-01.zip
```

官方归档还覆盖 USD-M `trades`、`indexPriceKlines`、`markPriceKlines`、`premiumIndexKlines`，并提供 daily/monthly ZIP 与 checksum。首次回补优先 monthly，最后未封月部分用 daily；按 `(symbol, interval, open_time)` 或 `(symbol, agg_trade_id)` upsert。K 线/aggTrades 可回补至各合约上市；资金费率 REST 可从上市分页；OI 历史和四种情绪/主动比、basis **最多只补最近 30 天**，必须从上线起滚动积累。`openInterest` 当前值每 5 分钟自行快照。

增量：每个 5 分钟边界后延迟 20--40 秒抓取已闭合 bar；以 watermark 回拉 2 个周期修订。K 线实时 5m（可由 Vision/REST 历史接上）；资金费率在下一结算后补抓；所有 Data API 用 `endTime=now` 回拉 2 个 bin。失败任务写 checkpoint，恢复后由 30 天窗口补洞；超过窗口的情绪/OI 缺口标为不可恢复，绝不伪造零值。

## 限频与「全 USDT 永续 × 5 分钟」估算

当前 659 合约。每 5 分钟若逐 symbol 采集五条 30 天微观序列（OI hist + 三种多空比 + taker）为 **659 × 5 = 3,295 请求/5min**，超过 Data API 的 1,000 req/5min/IP，即使其 endpoint weight 为 0 也**不可行**。若加 5m kline 则再 659 请求（weight 1/请求），`premiumIndex` 应不带 symbol 一次全取（weight 10），而非 659 次。

分级建议：

* Tier A：流动性前 150（以 24h quoteVolume 每日重排）全五条微观 5m：750 req/5min，留 250 给重试；K 线全量 659/5m 可单独跑，但与 Data API 配额分离仍须限并发。
* Tier B：其余合约五条微观每小时，均匀分 12 个 5 分钟槽：约 212 req/槽；Tier A 750 + Tier B 212 会超 1,000，故同一槽只跑 A，B 放错峰或 A 降至 140（700+216=916）。
* Tier C：全量每日快照/24h ticker；所有 5m K 线全量可行。大户比率、taker 比率不宜用更低频端点“补算”为 5m。

节流实现令牌桶：Data API 900/5min 的硬上限（余量给重试），普通 REQUEST_WEIGHT 目标 1,800/min（低于 2,400）；并发 10--20、对 429/418 遵从 `Retry-After`，指数退避+jitter。每次记录响应头 `X-MBX-USED-WEIGHT-1M`。

## 建议落库表设计

| 表 | 关键列 | 主键 | 保留策略 |
|---|---|---|---|
| `binance_futures_symbols` | symbol、contract_type、onboard_at、precision、filters JSONB、observed_at | `symbol, observed_at` | SCD；永久 |
| `binance_futures_klines_5m` | symbol、open_time、OHLC、base/quote_volume、trades、taker_buy_* | `symbol, open_time` | 原始永久；可压缩 |
| `binance_futures_micro_5m` | symbol、bucket_time、oi_qty、oi_usd、global/top_account/top_position long/short/ratio、taker buy/sell/ratio、basis | `symbol, bucket_time` | 原始 5m 18--24 月；字段 NULL 表示源缺失 |
| `binance_futures_premium_snapshots` | symbol、observed_at、mark/index、last_funding_rate、next_funding_at | `symbol, observed_at` | 5m 12 月；下采样 1h 永久 |
| `binance_futures_funding_rates` | symbol、funding_time、rate、mark_price、rate_type | `symbol, funding_time` | 永久 |
| `binance_futures_agg_trades`（可选、量很大） | symbol、agg_trade_id、event_time、price、qty、is_buyer_maker | `symbol, agg_trade_id` | Tier A 30--90 日热存，冷归档对象存储 |
| `binance_futures_micro_1h/1d` | symbol、bucket_time、OHLC/成交量聚合、末值 OI/比率、均值/分位 | `symbol, bucket_time` | 1h 3 年，1d 永久 |
| `binance_futures_percentiles` | symbol、metric、as_of、window、p05/p25/p50/p75/p95、value | `symbol,metric,as_of,window` | 1 年；用已闭合原始 5m 计算 30d/90d/1y rolling |

所有金额/数量用 `NUMERIC`，时间用 `timestamptz`（源毫秒另可保留 bigint）；不要 float。原始 payload 可在 `raw JSONB` 保留 7--30 日用于审计，业务列为规范化字段。

## 转发架构推荐

### Vercel Cron vs Cloudflare Worker + Cron

| 维度 | Vercel Cron + Function | Cloudflare Worker + Cron |
|---|---|---|
| 5 分钟触发 | Pro/Enterprise 支持分钟粒度；Hobby 仅每天，不能用 | 原生 `scheduled()`，UTC cron，适用 |
| 单次时长 | Function 计划与 Fluid Compute 相关；Pro 最大约 800 秒 | Cron wall time 15 分钟；低于 1h 的 CPU 上限 30 秒 |
| 写 PG | 可直接连公网/托管 PG，但连接池与出网要管理 | 可 `fetch` 回现有 API（推荐）；直连 PG 需 Hyperdrive/driver，增加网络与凭据复杂度 |
| 成本/限制 | Pro 付费、函数/调用与地域限制；批量 900 请求须控制时长 | Workers 免费/付费按请求与 CPU；Cron 可用但保证“at least once”语义设计 |
| 密钥 | 环境变量 `BINANCE_INGEST_SECRET`、`CRON_SECRET` | Worker secret；不下发到浏览器 |

**推荐 Cloudflare Worker + Cron，Worker 仅抓取和批量 POST，数据库只由广州 API 写入。** 原因是 Worker 出口可绕开广州可能的 Binance 网络限制，Worker 不持有 PG 连接串，且 15 分钟 wall time 足够完成分片。上线前务必从拟部署 Worker region 做 Binance 探针；地域和可达性都不是平台承诺。

文字时序图：

```
Cloudflare Cron (*/5 * * * *)
  -> Worker: 取 tier/分片、fetch fapi.binance.com（限流/超时）
  -> Worker: 规范化并以 gzip JSON 批量 POST
  -> Guangzhou /api/internal/ingest: 验签、校验 schema/窗口
  -> PostgreSQL: INSERT ... ON CONFLICT DO UPDATE（+ ingest_run/checkpoint）
  -> 监控：成功数、延迟、429、缺口、DLQ/告警
```

接口契约草案：

```http
POST /api/internal/ingest
Authorization: Bearer <rotatable-secret>
X-Ingest-Timestamp: <unix-ms>
X-Ingest-Nonce: <uuid>
X-Ingest-Signature: v1=<HMAC-SHA256(timestamp + "." + sha256(raw-body), secret)>
Content-Encoding: gzip
Content-Type: application/json

{
  "source":"binance-usdm", "schema_version":1,
  "run_id":"2026-11-14T12:05:00Z:micro:a",
  "dataset":"micro_5m", "period":"5m",
  "observed_at":"...Z", "records":[{"symbol":"BTCUSDT","bucket_time":"...Z", "global_long_account":"0.7573", "...":"..."}]
}
```

服务器仅接受 allowlist dataset、时间漂移 ±5 分钟、nonce 去重 24h、单批最多 500 records/1 MiB 解压后；返回 `{accepted, duplicated, rejected, checkpoint}`。唯一键 upsert 是最终幂等屏障，`run_id + dataset + shard` 另建唯一约束防同一批重复。Worker 对网络/5xx/429 重试 3--5 次（指数退避和 `Retry-After`）；4xx schema/验签不重试，投 DLQ。Cron 可能重叠时由 PG advisory lock 或 `ingest_run` lease 保证同一 `(dataset,period,shard,bucket)` 单写；超过 30 天的缺口直接告警。

## 来源与复核点

* [Binance USDⓈ-M REST 文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)（上线时以页面的 endpoint weight/参数为准）。
* [Binance Public Data 官方仓库](https://github.com/binance/binance-public-data)（Vision 目录、daily/monthly、UM 归档格式）。
* [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/) 与 [Workers limits](https://developers.cloudflare.com/workers/platform/limits/)（Cron 触发和 15 分钟 wall time）。
* [Vercel limits](https://vercel.com/docs/limits) 与 [Vercel Cron 说明](https://vercel.com/i/event-driven-architecture)（Hobby 不能 5 分钟、Pro/Enterprise 分钟级）。

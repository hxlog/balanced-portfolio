# 数据库与行情入库只读侦察

侦察日期：2026-11-14（Asia/Shanghai）。代码依据为 `ddl/schema.sql` 与 `bp_ingest/` 全部现存文件。数据库连接按题给地址并以 `default_transaction_read_only=on` 尝试；本执行环境对 `100.75.138.35:5432` 的 TCP connect 超时，未能建立会话。因此本报告**没有执行任何数据库 SQL（包括 SELECT）**，下文所有“活库”项均明确标为未采集，不能将 schema seed 当作生产事实。

## 一、现有数据字典

记号：NN=NOT NULL；`—`=可空且无默认值；`now()`=写入时当前时刻。所有 `updated_at` 触发器均由 `bp_set_updated_at()` 在 UPDATE 前刷新。下表的“列（类型；可空；默认/语义）”逐列列出；`smallint` 并非 PostgreSQL boolean：`is_deleted` 只能为 0/1，其中 0=未逻辑删除、1=逻辑删除。

|表 / 用途|列（类型；可空；默认/语义）|主键、唯一、检查、索引；外键/删除行为|
|---|---|---|
|`bp_data_source` / 行情源目录|`code text NN`; `description text NN`; `akshare_func text NN`; `asset_class text NN`; `has_volume boolean NN=true`; `supports_date_range boolean NN=false`; `symbol_hint text —`; `is_enabled boolean NN=true`; `vendor text —`; `logical_source text —`（UI 逻辑源）; `is_backup boolean NN=false`; `is_addable boolean NN=true`; `created_at timestamptz NN=now()`; `updated_at timestamptz NN=now()`|PK `code`。被 config、raw/clean quote、portfolio asset/status 以 `source` 引用；均未显式 `ON DELETE`，即 RESTRICT/NO ACTION。|
|`bp_index_config` / 可抓取资产配置|`config_id bigint identity NN`; `symbol text NN`; `source text NN`; `category text —`; `name text —`; `start_date date —`; `extra_params jsonb NN='{}'`; `is_deleted smallint NN=0`（0/1）; `is_selectable boolean NN=true`; `last_sync_at timestamptz —`; `last_error text —`; `row_hash char(32)` generated=`md5(lower(symbol)\|source)`; `currency text NN='CNY'`; `created_at/updated_at timestamptz NN=now()`|PK `config_id`; UQ `(symbol,source)`, `row_hash`; CHECK `is_deleted in (0,1)`; partial index `idx_bp_index_config_active(source,symbol) WHERE is_deleted=0`; FK `source→bp_data_source.code`（NO ACTION）。|
|`bp_index_quote_daily` / 原始日线|`trade_date date NN`; `symbol/source text NN`; `category/name text —`; `open/high/low/close numeric(20,6)`（close NN）; `volume bigint —`; `amount numeric(24,4) —`; `turnover_rate/pct_change numeric(12,6) —`; `row_hash char(32)` generated; `created_at/updated_at timestamptz NN=now()`|PK `(symbol,source,trade_date)`；Timescale hypertable（按 `trade_date`、90 天 chunk）；index `(symbol,source,trade_date DESC)`；FK `source→bp_data_source`（NO ACTION）。|
|`bp_quote_clean` / 清洗后回测价格|`trade_date date NN`; `symbol/source text NN`; `close numeric(20,6) NN`; `open/high/low numeric(20,6) —`; `volume bigint —`; `ret double precision —`; `fx_rate numeric(18,8) —`（外币→CNY，CNY=1）; `fill_flag text NN='real'`; `created_at/updated_at timestamptz NN=now()`|PK `(symbol,source,trade_date)`；Timescale hypertable（90 天）；index `(symbol,source,trade_date DESC)`；CHECK `fill_flag in ('real','interp')`; FK source（NO ACTION）。|
|`bp_admin_user` / 旧管理账户|`id bigint identity NN`; `email text NN`; `password_hash text NN`; `created_at/updated_at timestamptz NN=now()`|PK `id`; UQ `email`。|
|`bp_user` / 用户与权限|`user_id bigint identity NN`; `email/password_hash text NN`; `role text NN='user'`; `status text NN='active'`; `portfolio_limit integer =3`（NULL=无限）; `totp_enabled boolean NN=false`; `totp_secret text —`; `can_manage_assets boolean NN=false`; `created_at/updated_at timestamptz NN=now()`|PK `user_id`; UQ email; CHECK role=`user/admin`, status=`active/disabled`。被 portfolio/task/audit/order/OTC 引用；除明确 CASCADE 者均 NO ACTION。|
|`bp_portfolio` / 组合定义与回测参数|`portfolio_id bigint identity NN`; `name text NN`; `method text NN='quadrant_inner_sharpe_outer_rp'`; `ratio text NN='sharpe'`; `lookback_days integer NN=156`; `start_date date NN`; `effective_start_date date —`; `benchmark_symbol/source/key text NN='000300'/'cn_index_em'/'000300'`; `max_weight numeric(6,4) —`; `rebalance_band numeric(6,4) NN=.05`; `description text NN='组合描述'`; `is_demo boolean NN=false`; `status text NN='pending'`; `error text —`; `last_run_params jsonb NN='{}'`; `owner_user_id/created_by/updated_by bigint —`; `risk_free_rate/fee_rate/slippage_rate/stamp_duty_rate numeric(10,6) NN=0`; `result_version integer NN=1`; `result_updated_at timestamptz —`; `data_as_of_date date —`; `display_order integer —`; `created_at/updated_at timestamptz NN=now()`|PK portfolio_id; checks method（4 种）、ratio（sharpe/sortino）、status（pending/running/done/error）；indexes demo、demo display order、owner；三 user FK 均 NO ACTION。被下列 portfolio 子表 CASCADE。|
|`bp_portfolio_asset` / 组合成分|`portfolio_id bigint NN`; `symbol/source/quadrant text NN`; `display_name text —`; `sort_order integer NN=0`|PK `(portfolio_id,symbol,source,quadrant)`；CHECK quadrant=overheat/stagflation/recovery/recession；portfolio FK CASCADE，source FK NO ACTION。|
|`bp_backtest_nav` / 每日组合净值|`portfolio_id bigint NN`; `method text NN`; `trade_date date NN`; `nav double precision NN`; `benchmark_nav/ret/bench_ret double precision —`|PK `(portfolio_id,method,trade_date)`；portfolio FK CASCADE。|
|`bp_backtest_rebalance` / 调仓记录|`portfolio_id bigint NN`; `method text NN`; `trade_date date NN`; `reason text —`; `target_weights jsonb NN`; `prev_weights/delta/quadrant_weights jsonb —`; `max_deviation double precision —`|PK `(portfolio_id,method,trade_date)`；portfolio FK CASCADE。|
|`bp_backtest_metric` / 指标|`portfolio_id bigint NN`; `method/scope text NN`; `metrics jsonb NN`|PK `(portfolio_id,method,scope)`；scope CHECK portfolio/benchmark；portfolio FK CASCADE。|
|`bp_backtest_cov` / 协方差/权重快照|`portfolio_id bigint NN`; `method text NN`; `as_of_date date NN`; `labels/corr_matrix jsonb NN`; `cov_matrix/optimal_weights/optimal_quadrant_weights jsonb —`|PK `(portfolio_id,method)`；portfolio FK CASCADE。|
|`bp_backtest_benchmark` / 基准净值|`portfolio_id bigint NN`; `benchmark_key text NN`; `trade_date date NN`; `nav double precision NN`; `ret double precision —`|PK `(portfolio_id,benchmark_key,trade_date)`；portfolio FK CASCADE。|
|`bp_backtest_attribution` / 归因载荷|`portfolio_id bigint NN`; `method text NN`; `benchmark_key text NN='bond6040'`; `payload jsonb NN`|PK `(portfolio_id,method,benchmark_key)`；portfolio FK CASCADE。|
|`bp_backtest_coverage` / 成分数据覆盖判定|`portfolio_id bigint NN`; `symbol/source text NN`; `first_date/last_date/first_covered_date date —`; `covered_at_start boolean NN`|PK `(portfolio_id,symbol,source)`；portfolio FK CASCADE。|
|`bp_task` / 异步任务|`task_id uuid NN`; `celery_id text —`; `task_type text NN`; `status text NN='queued'`; `portfolio_id/owner_user_id bigint —`; `progress_current integer NN=0`; `progress_total integer NN=1`; `progress_message text —`; `result jsonb NN='{}'`; `error text —`; `created_at/updated_at timestamptz NN=now()`; `started_at/finished_at timestamptz —`|PK task_id; checks status=queued/running/success/failed/cancelled，type=backtest/daily_update/ingest/ingest_all/clean/asset_probe/asset_ingest/otc_price；index `(portfolio_id,status,created_at DESC)`；portfolio FK CASCADE，owner FK NO ACTION。|
|`bp_asset_data_status` / 每资产入库状态|`symbol/source text NN`; `last_raw_date/last_clean_date/first_clean_date date —`; `raw_rows/clean_rows bigint NN=0`; `last_success_at timestamptz —`; `last_error text —`; `last_probe_ms integer —`; `last_probe_kind text —`; `updated_at timestamptz NN=now()`|PK `(symbol,source)`；CHECK probe kind NULL/ok/unreachable/invalid；source FK NO ACTION。含义和写入方见第二节。|
|`bp_data_refresh_run` / 批刷新运行|`run_id bigint identity NN`; `task_id uuid —`; `target_trade_date date —`; `status text NN='running'`; `error text —`; `started_at timestamptz NN=now()`; `finished_at timestamptz —`|PK run_id；CHECK status running/success/failed；task FK NO ACTION。|
|`bp_portfolio_update_state` / 组合更新水位|`portfolio_id bigint NN`; `last_result_trade_date/last_data_trade_date date —`; `last_task_id uuid —`; `updated_at timestamptz NN=now()`|PK portfolio_id；portfolio FK CASCADE；task FK NO ACTION。|
|`bp_audit_log` / 审计日志|`audit_id bigint identity NN`; `actor_user_id bigint —`; `action/entity_type text NN`; `entity_id text —`; `detail jsonb NN='{}'`; `created_at timestamptz NN=now()`|PK audit_id；index `(actor_user_id,created_at DESC)`；user FK NO ACTION。|
|`bp_user_portfolio_order` / 用户组合排序|`user_id/portfolio_id bigint NN`; `display_order integer NN=0`; `updated_at timestamptz NN=now()`|PK `(user_id,portfolio_id)`；index `(user_id,display_order)`；两 FK 均 CASCADE。|
|`bp_cffex_contract_daily` / CFFEX 合约日线|`trade_date date NN`; `symbol/variety text NN`; `open/high/low/close/settle/pre_settle/turnover numeric(20,4)`（close NN）; `volume/open_interest bigint —`; `row_hash char(32)` generated; `created_at/updated_at timestamptz NN=now()`|PK `(symbol,trade_date)`；Timescale 90 天；indexes `(variety,trade_date DESC)`,`(symbol,trade_date DESC)`。|
|`bp_cffex_premium_daily` / 基差与升贴水|`trade_date date NN`; `variety/contract_symbol/contract_type text NN`; `days_to_expiry integer NN`; `spot_price/futures_price/basis numeric(20,4) NN`; `premium_rate/ann_premium_rate/composite_rate numeric(12,6) —`; `created_at timestamptz NN=now()`|PK `(trade_date,variety,contract_symbol)`；三个 indexes：variety-date、type-date、variety-type-date。|
|`bp_crypto_corr_daily` / 加密相关滚动预计算|`trade_date date NN`; `pair_key/asset_a/asset_b/method text NN`; `corr_3m/6m/9m/12m numeric(12,6) —`; `as_of_ts timestamptz NN=now()`|PK `(trade_date,pair_key,method)`；method CHECK pearson/spearman/kendall/hoeffding；index `(pair_key,method,trade_date)`。|
|`bp_crypto_price_daily` / NYSE 日历对齐价|`trade_date date NN`; `symbol/source text NN`; `close numeric(20,4) NN`; `as_of_ts timestamptz NN=now()`|PK `(trade_date,symbol)`（注意 source 不在 PK）；index `(symbol,trade_date DESC)`。|
|`bp_crypto_meta` / 看板元数据|`key/value text NN`; `updated_at timestamptz NN=now()`|PK key。|
|`bp_trading_calendar` / 交易日历|`market text NN='CN'`; `cal_date date NN`; `is_trading boolean NN`; `confidence text NN='official'`; `note text —`; `created_at/updated_at timestamptz NN=now()`|PK `(market,cal_date)`；CHECK confidence official/estimated/custom；partial index `(market,cal_date) WHERE is_trading`。|
|`bp_otc_deal` / OTC 合约与最近估值|`deal_id bigint identity NN`; `name/product_type text NN`; `engine text NN='mc'`; `underlying_symbol text NN`; `underlying_source text NN='cn_index_em'`; `terms jsonb NN='{}'`; `is_example boolean NN=false`; `owner_user_id bigint —`; `last_price numeric(20,4) —`; `last_present_notional numeric(24,4) —`; `last_greeks jsonb —`; `last_status text —`; `last_valued_at timestamptz —`; `last_result jsonb —`; `created_at/updated_at timestamptz NN=now()`|PK deal_id；type CHECK snowball/phoenix/airbag/barrier；engine CHECK mc/analytic/quad/pde；indexes example、owner；owner FK CASCADE。|
|`bp_otc_deal_price_history` / OTC 估值历史|`history_id bigserial NN`; `deal_id bigint NN`; `priced_at timestamptz NN=now()`; `price/current_pnl double precision —`; `status/task_id text —`; `result jsonb NN`|PK history_id；index `(deal_id,priced_at DESC)`；deal FK CASCADE。|
|`bp_user_otc_deal_order` / OTC 排序|`user_id/deal_id bigint NN`; `display_order integer NN=0`; `updated_at timestamptz NN=now()`|PK `(user_id,deal_id)`；index `(user_id,display_order)`；两 FK CASCADE。|

关联总览：`bp_data_source` 是 source 维表；`bp_index_config` 定义资产，raw/clean quote 用 `(symbol,source,trade_date)` 保存行情；portfolio 为父表，asset、全部 backtest 结果、task/状态/排序等围绕它；user 为权限父表；OTC 为独立 deal→history/order 链。`bp_index_quote_daily`、`bp_quote_clean`、`bp_cffex_contract_daily` 是 schema 明确创建为 90 天 chunk hypertable 的三表。

## 二、活库画像与 schema 差异

### 采集结论（阻塞）

未采集。对题给 `100.75.138.35:5432` 的 TCP 探测返回 connect timeout；故无法安全、诚实地给出任一表行数、日期范围、symbol/source distinct、按 source 汇总、`bp_index_config` 的 category/extra_params/错误/可选性/币种分布，亦无法对 `information_schema` 执行生产-vs-schema 差异比对。没有猜测或补造数字。

恢复连通后应以只读事务一次性执行：

```sql
-- 表、列、约束/索引差异：information_schema.tables/columns，pg_constraint，pg_indexes
-- 各表行数：SELECT count(*) FROM public.<bp_table>;
-- 日线按源：SELECT source,count(DISTINCT symbol),min(trade_date),max(trade_date),count(*)
-- FROM bp_index_quote_daily GROUP BY source; -- bp_quote_clean 同理
-- extra_params：SELECT key, jsonb_agg(DISTINCT value) FROM bp_index_config,
-- jsonb_each_text(extra_params) GROUP BY key;
```

`bp_asset_data_status` 的既定语义：`last_raw_date` 为 raw 最大交易日，`last_clean_date`/`first_clean_date` 为 clean 最大/最小交易日，`raw_rows`/`clean_rows` 是计数，`last_success_at` 是成功同步时刻，`last_error` 是最近错误，`last_probe_ms` 是保存前探测耗时，`last_probe_kind` 为 ok/unreachable/invalid。写入方是 `bp_ingest.db` 的状态刷新/错误标记函数，以及资产保存/probe API 路径；入库 `run()` 仅在原始数据推进时以带 `COUNT` 分支刷新完整计数，以避免热路径扫描代价。

## 三、ingest 管线

### 源适配器与归一化

`sources.py` 的不可变 `SourceAdapter` 字段是 `code, akshare_func, supports_date_range, has_volume, provides_pct, fetch`；`SOURCES: dict[str, SourceAdapter]` 是注册表，含 19 个实现源（schema 的 `futures_cffex` 是独立 `cffex.py` pipeline，不在该表）。所有 fetch 签名为 `(symbol,start,end,extra)->DataFrame`，目标列固定为 `trade_date,open,high,low,close,volume,amount,turnover_rate,pct_change`；`_rename` 映射中文/各供应商列，`_finalize` 补列、日期/数值强转、丢弃无 date/close 行、按窗口过滤和排序。ETF/指数会补交易所前缀；`extra_params.adjust` 控制 ETF 腾讯/东财复权，债券读取 `indicator`。

`AGGREGATE_CHAINS` 把同收益口径的备源串接（如 `cn_index_em→cn_index_sina→cn_index_tx→index_tx`，`etf_em→etf_tx`，`crypto_yfinance→btc_cme_sina`）。主源不覆盖 end 或连接异常时 `fetch_with_fallback()` 取重叠日收盘比值重锚 OHLC；主源整段失败则可用库内锚点。`fx_sina` 刻意无降级，避免混用不同汇率口径。

### 增量、日门控、清洗和 UPSERT

`ingest.py:_sync_one()` 读取 raw 最后交易日，结合 `TradingCalendar.confirmed_expected_latest(today,lag_days)`；已到期望日就 skip，但若今日盘中行在收盘确认 deadline 前写入，则 `_needs_post_close_refresh()` 强制重拉。新品从 `config.start_date` 或默认起始日拉取；存量从最后日向回 `revision_days` 拉取。抓取有 tenacity 随机指数退避；`_drop_unconfirmed_today_bars()` 在收盘确认前绝不写今日 K。缺供应商涨跌幅时 `_compute_pct_change()` 用上一真实 close 本地算；随后 build row、raw UPSERT、标记同步结果。资产间另加随机抖动以降低限流。

当前仓库**没有** `bp_ingest/cleaning.py`（题目文件名与 repo 不符）；实际实现为 `bp_api/quant/cleaning.py`，由 `bp_ingest.ingest.run(..., refresh_clean=True)` 调 `rebuild_clean()`。它按 A 股日历对齐，内部缺口在两侧真实价存在时线性插值（`fill_flag=interp`），先把外币 OHLC 按逐日汇率折算 CNY、再插值；真实 CNY 行 `fx_rate=1`，真实外币行记录当日汇率，插值日不外推汇率（NULL）。BTC/DXY/COMEX 等原生 USD 展示路径不折算，`fx_rate=NULL`。`bp_quote_clean.close` 因此通常是回测 CNY 价格；`interp` 在回测与 crypto 读侧均被明确排除，防止未来函数。

`db.py` 批量 UPSERT raw 的冲突键是 `(symbol,source,trade_date)`，更新 OHLCV、amount、turnover、pct、category/name 与 `updated_at=now()`；clean 同键覆盖 clean 字段。同步成功/错误更新 config 与 `bp_asset_data_status`。这保证 revision window 可幂等覆盖，但也意味着同键不能同时储存不同价格口径。

`http_session.py` 安装 hardened session：requests monkeypatch 注入 Chrome 指纹、按 host 注入东财 cookie、超时/重试相关处理；sources 将 ConnectionError/Timeout/429、curl_cffi/Yahoo 限流识别为“可达性问题”，触发降级或 probe 的 `unreachable`，而各源正常空表才标为 `SymbolNotFoundError/invalid`。

### 调度与 crypto 预计算

`scheduler.py:start()` 使用 `BlockingScheduler(timezone='Asia/Shanghai')`：通用行情每 `BP_SCHEDULE_HOURS`（默认 6h），组合就绪巡检每 20 分钟，CFFEX 每 `BP_CFFEX_SYNC_HOURS`（默认 1h），crypto 增量每 `BP_CRYPTO_SYNC_HOURS`（默认 1h），crypto 另有每日 05:30 北京时间的全量相关性兜底重算；启动时立即跑通用 ingest 和 CFFEX（crypto 不启动即跑）。`cli.py` 的 `schedule` 是入口。

`crypto_corr.py:compute_and_store_crypto_corr()` 每次从 clean quote 读取近 7 年 6 资产，按标普 500 的 NYSE 日历，对 BTC 与四资产对计算 3/6/9/12 月 × pearson/spearman/kendall/hoeffding；选最近六资产齐且收盘确认的 effective date。它全量幂等 UPSERT 到 `bp_crypto_corr_daily`（键 date/pair/method）及 `bp_crypto_price_daily`（键 date/symbol），清除超过 effective date 的旧 tail，维护 `bp_crypto_meta` 的 effective date/is_synced/version 并按变更 ping revalidate。此模块也包含 DELETE，故本次未运行。

### “每日 21:00 抓指数估值”的最小改动

1. 新建独立模块（建议 `bp_ingest/index_valuation.py`）实现 fetch、字段标准化与估值表 UPSERT；不能复用 price-only raw 表承载估值。
2. 在 `bp_ingest/scheduler.py:start()` 新增 `index_valuation_job()`，复用配置/连接/日志，并以 `CronTrigger(hour=21, minute=0, timezone='Asia/Shanghai')` 注册。若仅抓现有 config 的指数，应从 `bp_index_config` 过滤 category=`index`，必要时新增 valuation source；若供应商接口不在 `SOURCES`，在 `sources.py` 增加 `SourceAdapter` 和标准化函数。
3. 在 `bp_ingest/cli.py` 增加显式命令（如 `valuation-run`）以便补跑/运维；在 `config.py` 添加开关、超时、源参数（可选但推荐）。
4. 先加迁移/DDL 新表（见第四节），再写 job；仅改 scheduler 而没有存储结构无法形成 PiT 历史。

## 四、指数/股票维度缺口分析

|维度|现在是否有/位置|缺口与建议表（PiT 都应以 `trade_date` 为事实时点）|
|---|---|---|
|指数 PE/PB/股息率|没有。raw/clean 只有价格、量、金额、换手、涨跌幅；`extra_params` 只是抓取参数，非历史指标。|`bp_index_valuation_daily(index_symbol,index_source,trade_date,pe_ttm,pb,dividend_yield,pe_forward,ps,source,as_of_ts,raw_payload)`；PK `(index_symbol,index_source,trade_date,source)`，并记录供应商发布时间/抓取时刻。|
|指数 ROE/ROA|没有。|可加到上述 valuation 表（`roe_ttm,roa_ttm`），或分离 `bp_index_fundamental_daily`；指数级聚合口径必须有 `methodology`/`coverage`。|
|指数成分股与权重|没有。|`bp_index_constituent_pit(index_symbol,index_source,effective_date,stock_symbol,stock_market,weight,shares,free_float_mktcap,announcement_date,source,as_of_ts)`；PK 至少 `(index_symbol,index_source,effective_date,stock_symbol,source)`。生效日与公告/抓取时刻分开是 PiT 必需。|
|跟踪基金|仅 `bp_index_config` 有 ETF 自身，且无“跟踪哪一指数”的关系。|`bp_index_tracker_fund(index_symbol,index_source,fund_symbol,fund_source,effective_date,fund_name,tracking_type,tracking_error,source,as_of_ts)`；PK `(index_symbol,index_source,fund_symbol,fund_source,effective_date,source)`。|
|基金规模|没有（ETF raw 日线无份额/净资产）。|`bp_fund_aum_daily(fund_symbol,fund_source,trade_date,nav,shares_outstanding,aum,net_flow,source,as_of_ts)`；PK `(fund_symbol,fund_source,trade_date,source)`。|
|股票日线|没有个股 source/config；`bp_index_quote_daily` 名称虽泛化，当前适配器/seed 是指数、ETF、期货等，不是股票 universe。|`bp_stock_quote_daily(symbol,market,trade_date,adjustment,source,open,high,low,close,volume,amount,turnover_rate,pct_change,adj_factor,as_of_ts)`；PK `(symbol,market,trade_date,adjustment,source)`。|
|前/后/不复权及复权因子|ETF 可由 `extra_params.adjust` 指定，但 raw/clean 表没有 `adjustment`/`adj_factor`，且 clean 已转 CNY；指数默认不复权。|上述 stock 表须显式 `adjustment` 枚举 `bfq/qfq/hfq` 与 `adj_factor`。如统一改造价格表，也必须把 adjustment 加入所有唯一键、配置唯一键和 status 键，或以不同物理 source 区分。|

## 五、指数估值 PiT 面板的可复用性判断

可直接复用：`bp_index_config`（资产主数据、币种、可选性、抓取参数）、`bp_index_quote_daily`（指数原始收盘/成交字段、时间序列 UI 联结）、`bp_quote_clean`（CNY 回测口径/收益率，**不应**当估值事实源）、`bp_trading_calendar`（交易日门控/前端空档口径）。可将 valuation 表的 `(index_symbol,index_source,trade_date)` 与前两张价格表连接，但应按公告/可得时间而非仅交易日实现 point-in-time。

不可表达的部分：现有 quote 主键都是 `(symbol,source,trade_date)`。同一 `symbol+source+date` 若同时写 bfq/qfq/hfq，后写入会 ON CONFLICT 覆盖前者；`extra_params.adjust` 属于配置行且 config 又唯一 `(symbol,source)`，同一源同代码也不能配置三种 adjustment。`row_hash` 同样只含 symbol/source。因此“三种复权”必须：（a）新表把 `adjustment` 放入 PK（推荐），或（b）人为创建三个不同 physical source code 并严格隔离（不推荐，污染 source 语义）。复权因子/供应商修订时刻也无现有列，PiT 面板需要 `adj_factor`、`published_at/as_of_ts`、源与原始载荷审计字段。

## 附：恢复数据库连通后必须补写的事实

在报告补齐前不得把本文件当生产规模盘点。需要记录：30 表逐表 count；每个含 date/timestamp 表的 min/max；各关键维度 distinct；raw/clean 按 source 的 symbol 数/首末日/行数；config 的 category、全部 JSON key→distinct 值、last_error 非空数、selectable×currency；以及 public schema 与 `ddl/schema.sql` 的表/列、类型、nullable/default、约束/index/hypertable 差异。查询账户应继续设置 `default_transaction_read_only=on`，不运行本仓库中任何会写入的 ingest/crypto/cffex 函数。

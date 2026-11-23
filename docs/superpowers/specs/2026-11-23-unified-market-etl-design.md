# 全市场日行情统一 ETL 与"交易日当天就绪"设计（2026-11-23）

> 状态：待批准（实现前不得写产品代码）
> 依据：2026-11-23 审计 + 问答 Q1–Q8 / D1–D5（见 §14 决策记录）
> 关联计划：`docs/superpowers/plans/2026-11-23-market-etl-p1-framework.md`、
> `docs/superpowers/plans/2026-11-23-market-etl-p2-legacy-cleaning.md`

**一句话目标**：把 A 股个股 / 港股个股 / 场内基金（ETF/LOF/封闭式）/ 场外基金净值 四类全量
日行情，连同旧指数/商品/汇率行情链，收敛到一条"多源聚合、锚定口径、当日轮询追赶"的统一
ETL 链路；交易日当天完成落库、覆盖快照刷新、管理端可见，并把清洗面板与回测接入同一链路
（L3）。

## 1. 背景与审计事实（2026-11-23 21:39–22:30 实测）

### 1.1 现状：两套并行 ETL，都做不到"当天就绪"

| 数据面 | 表 | 今日(11-23)实况 | 根因 |
|---|---|---|---|
| 新资产池·A 股 | `bp_stock_quote_daily` | bfq 0 行（日更 23:35 才跑）；**qfq/hfq 5,045/5,047 只停在 11-13** | 三口径仅"周日 02:30 补齐"，且被腾讯 WAF 截断（覆盖 1,923/5,227）；日常只补 bfq |
| 新资产池·港股 | 同上（5 位码） | 0 行；三口径停在 11-20 | 日更 23:40 才跑；无追赶/轮询机制 |
| 新资产池·ETF | `bp_etf_quote_daily` | 0 行；三口径停在 11-20 | 日更 23:45 才跑；hfq 依赖腾讯且 WAF 敏感 |
| 新资产池·基金 | `bp_fund_nav_daily` | 23,931/28,078（21:50 起批量榜+补缺，458s） | 时点晚、无多波追赶，晚发布基金次日才补 |
| 覆盖快照 | `bp_asset_coverage` | 最后刷新 11-22 18:42 | 23:55 单次全量重建，ETL 失败/延迟即整体陈旧 |
| 旧链·指数 | `bp_index_quote_daily` / `bp_quote_clean` | 547 只指数仅 139 只当日；health=120 ok/339 stale/61 missing | 东财 push2his 封禁服务器 IP（264 只自 11-20 无成功）；串行 2.5–6s/只（460 只耗时 7,973s）；修复 cron 只覆盖部分 |

### 1.2 接口层实测（生产服务器 + 本机交叉验证）

| 源/通道 | 当日可用性 | 延迟/吞吐 | 限速/封禁 |
|---|---|---|---|
| 腾讯 `qt.gtimg.cn` 批量快照 | bfq 收盘即就绪（A/ETF） | 60–100 只/请求，40–70ms；5,227 只≈88 请求 | 高频触发 WAF；需全局限速 |
| 腾讯 `fqkline`/`hkfqkline` | 复权部分就绪：22:16 抽样 A 7/10、ETF 6/10、HK 8/10；22:24 ETF 0/5 | 单请求 25–60ms | **WAF 敏感且不稳定**，有 `proxy.finance.qq.com`/`newfqkline` 回退 |
| 新浪 A 股 `stock_zh_a_daily` | **hfq 10/10 当日就绪**（服务器直连） | 0.4–0.8s/只（含因子文件） | 需 4–8 线程+节流；11-16 全量回填实测 13,740 请求/16 分钟可用 |
| 东财 push2his（直连服务器） | **封禁**（40/40 连接被掐，HTTP/curl_cffi 全失败） | — | 自 11-21 起；`push2.eastmoney.com` 快照与天天基金 API 不受影响 |
| 东财 push2his（SG relay） | 可用，当日数据齐 | 热连接 0.3–2.1s；8 线程 2.7 req/s、0 错误（32 请求） | 只适合小流量（旧指数链 ~550 请求/日≈3.5 分钟） |
| 新 VLESS 节点（prologue） | 可用（EM/腾讯/基金均 200） | 单请求 2–4.7s；8 线程 0.64 req/s、22/32 超时 | **只作低流量容灾/第二 relay**，不能承载全量 |
| 天天基金 rankhandler / lsjz | 直连正常；21:50 一轮写入 2.39 万条 | 1.9s / 0.16s | 无压力，多波追赶可覆盖晚发布基金 |

### 1.3 服务器与 DB 硬约束
- 2 vCPU / 3.7GB，swap 已用 1.5GB，可用内存 ~300MB；PostgreSQL 18.4 同机（shared_buffers 954MB，24 连接）。
- 旧 `index_quote_incremental.py` 串行 460 只耗时 2.2 小时；PM2 `bp-ingest` 每小时全量轮询，是"T+1 化"核心瓶颈。
- 结论：新 ETL 必须**小内存流式写、通道级限速、错峰**；重活（历史重建）在夜间窗口 or 本机跨 WAN 分批执行。

### 1.4 根因归纳
1. **调度时点错**：日更全部排在 23:35–23:55，且只有一次机会、无轮询追赶/截止兜底；
2. **复权日更缺失**：hfq 依赖"周日补齐"，且该任务被 WAF 截断，日常不更新；
3. **单源脆弱**：无锚定/回退/熔断/源健康；东财一封、腾讯一限流就停摆；
4. **旧链未收敛**：旧 ETL 与旧 cron 各自为政、串行低效、与清洗/组合就绪脱节；
5. **口径隐患**：A 股 hfq 表内同时存在新浪（11-13 主体）与腾讯（1,923 只）两套绝对基准，
   跨源按日切换会引入"假跳空"。

## 2. 目标 / 非目标 / 验收

### 2.1 目标（本设计交付）
- **G1 统一链路**：一个新 ETL 服务（`bp_etl`）覆盖：A 股个股、港股个股、场内基金、场外基金净值，
  以及（P2）旧指数/商品/汇率行情链；替代现有 ad-hoc crontab 与 1h 轮询。
- **G2 当日就绪（L2 硬验收）**：交易日当天完成——原始表落库、`bp_asset_coverage` 刷新、
  `/api/assets/unified` 与 `/api/v1/market/*` 返回当日 `last_date`、`/admin/market-data` 看板绿灯。
- **G3 复权正确（L2+）**：bfq 与 hfq 当日都要落库并交叉校验；**停用 qfq**（不拉取、API/前端隐藏、
  历史行保留只读）。
- **G4 可回测（L3）**：清洗面板（`bp_quote_clean`）与回测/构建器消费 v3 资产；港股按当日
  汇率折算 CNY；保持既有"无未来函数/插值/覆盖率"口径（P2 验收）。
- **G5 可观测**：每次运行落库（run/wave/覆盖率/耗时/错误）；源可用性矩阵每日可查；
  失败可复盘、可重放、幂等。
- **G6 时效目标与无限追赶**（目标就绪 = 期望时点；**升级时点** = 超过此点转黄色/红色告警，但
  **不停止重试**；任何 dataset 未追平就持续进入追赶循环，跨交易日从 backlog 续跑，直到
  `last_date == 最新可用交易日`。以 Phase 0 实测校准目标时点）：

| 数据集 | 内容 | 目标就绪 | 升级告警（不停止） | 说明 |
|---|---|---|---|---|
| A 股 | bfq | 15:30 | 15:55 | 腾讯 qt 批量 |
| A 股 | hfq | 16:30 | 23:30 | 新浪主锚，10 分钟一轮追赶 |
| ETF | bfq | 15:30 | 15:55 | 腾讯 qt 批量 |
| ETF | hfq | 16:30 | 23:30 | 腾讯主锚 → 东财 relay 兜底 |
| 港股 | bfq | 16:30 | 17:30 | 16:00 收盘后新浪 |
| 港股 | hfq | 17:30 | 23:30 | 腾讯主锚 → 东财 relay 兜底 |
| 基金净值 | 全部 | 23:00（≥99% 可发布子集） | 23:45 | 20:00 起多波（20:00/20:40/21:20/22:00/22:40/23:20） |
| 覆盖快照/API | 全量 | 23:50 | 23:59 | 增量随每类完成刷新 + 23:50 全量校准 |
| 旧指数链 | bfq | 16:30 | 23:30 | P2：广基走新浪/腾讯，EM 独占走 relay |

### 2.2 非目标
- 不引入盘中实时价（`/api/v1/market/last` 仍是"已确认收盘价"）；
- 不改动既有表主键/既有 API 信封语义（只加表、加字段、加隐藏逻辑）；
- 不物理删除历史 qfq 行（D5）；
- 不重写估值/分位/CFFEX/加密合约的数据链（只把行情类迁入框架）；
- 不做多租户/权限体系改造（管理页沿用超级管理员鉴权）。

### 2.3 验收口径
- **覆盖率**：以"当日应发布集合"为分母。A 股 5,227、港股 2,811、ETF 1,392、基金 ~2.5–2.6 万
  （货币/QDII 等晚发布按可发布子集），旧指数 521 只跟踪池。停牌/退市/无行情代码不计入分母
  （由主数据 is_delisted、当日成交量为 0/无行 判定，白名单落库可审计）。
- **质量门**：见 §8；任何一类不达标必须落 `bp_etl_quality_issue` 并在管理页红色告警，
  不允许静默。
- **回归**：`python -m pytest bp_api/tests -q`、`cd web && npm run typecheck && npm test && npm run build` 全绿；
  既有 `/api/v1/market/*`、资产池、回测用例语义不变。

## 3. 口径决策（必须遵守）

1. **只保留 bfq（不复权）与 hfq（后复权）**；qfq 停止拉取，API 对 `adjust=qfq` 返回
   400 `invalid_parameter`（`qfq 已停用`），前端选项删除；历史 qfq 行保留只读（D5）。
   - 回测默认 hfq 不变；展示/现价用 bfq 不变。
2. **每个 (dataset, adjust) 只有一个"锚定源"**（anchor），锚定源决定该序列的绝对价格基准；
   其它源只做回退/校验。回退源写入前必须按重叠日常数比 **重锚** 到锚定基准（只缩放价格字段，
   收益率不变），并以 `source='{fallback}:anchored'` 落库以保留可审计性。
3. **禁止同一序列跨日混用绝对基准**：若历史数据基准与目标锚不一致，必须一次性重建该序列
   （D4 已批准 A 股 bfq/hfq、港股 bfq/hfq、ETF bfq/hfq 从 2020 起重建）。
4. **港股 CNY 折算只发生在清洗层**（沿用 `fx_sina` 唯一汇率口径、先折算再插值、OHLC 同乘、
   volume 不折、无汇率日不产出、尾部护栏）；原始行情表存原币（HKD/CNY）。
5. **基金净值**：以单位净值为准（`bp_fund_nav_daily.nav`），累计净值 `acc_nav` 有则补；
   货币基金/晚发布基金不伪造净值；覆盖率按"可发布子集"。
6. **收盘确认**：A 股/ETF 15:10 后、港股 16:15 后（HK 16:00 收盘 + 缓冲）才允许写当日行；
   盘中行一律丢弃（沿用 `close_confirm` 语义）；ETL 波次自动遵循。
7. **Provenance 必须落库**：原始表 `source` 列记录实际提供方；`bp_etl_run` 记录每波
   目标/实际覆盖率与各源用量。

## 4. 总体架构（方案 A：统一 ETL 平台 + 多源聚合层）

### 4.1 组件
```
bp_etl/                          # 新包（与 bp_ingest 并存，逐步取代其行情职责）
├── config.py                    # 环境/通道/限速/截止时间配置
├── registry.py                  # DatasetSpec + SourceSpec + ChannelSpec 注册表
├── channels.py                  # 出口通道：direct / relay_sg(10809) / relay_prologue(10810)
│                                #   per-channel session（curl_cffi 指纹）、代理选择、健康计数
├── rate_limit.py                # 通道级全局令牌桶 + 自适应退避 + WAF/封禁探测
├── retry.py                     # deadline-aware 重试（总耗时上限，防慢速滴流挂死）
├── adapters/
│   ├── base.py                  # Adapter 协议：capabilities()/fetch()/probe_channel()
│   ├── tencent.py               # qt 批量、fqkline/hkfqkline/newfqkline、proxy.finance 回退
│   ├── sina.py                  # A 股原始+hfq 因子、港股日线、指数备用
│   └── eastmoney.py             # push2his（经 channel）、基金 rankhandler/lsjz（直连）
├── anchors.py                   # 锚定解析 / 重叠日常数比重锚 / 比率漂移校验
├── writer.py                    # 幂等 upsert（batch）、prev_close/pct、coverage 增量
├── quality.py                   # 质量门（§8）
├── coverage.py                  # 增量 upsert + 全量校准（替代 TRUNCATE 重建）
├── health.py                    # run/wave/source_health/issue 落库
├── orchestrator.py              # 数据集波次调度、轮询追赶、截止、锁、幂等、重放
├── datasets/
│   ├── a_stock.py / hk_stock.py / etf.py / fund_nav.py
│   └── legacy_index.py          # P2
└── cli.py                       # python -m bp_etl run|service|rebuild|verify|health
```

### 4.2 数据流
```
收盘确认后 → orchestrator 按 dataset 波次触发
  → adapters 多源拉取（通道限速/熔断；源优先级链）
  → writer 归一化 + 重锚 + 幂等写 bp_stock_quote_daily / bp_etf_quote_daily / bp_fund_nav_daily / bp_index_quote_daily
  → quality 门（行数/OHLC/交叉源收益差/hfq·bfq 比率漂移）→ 不达标落 issue 并触发下一波重试
  → coverage 增量刷新（last_date 可视化）→ 缓存失效
  → 全部数据集合规后：触发清洗（P2）与组合就绪（复用 bp_api.daily_update）
所有步骤写 bp_etl_run / bp_etl_source_health，管理页只读展示。
```

### 4.3 与现有系统关系
- **表**：保留现有行情表；新增 3 张 ETL 运行/健康/问题表（§5）。不新建宽表（避免 C 方案风险）。
- **API**：`/api/v1/market/*` 与 `/api/assets/unified` 复用现有表；只调整 `quote_store` 的来源
  优先级映射为"锚定优先"，并拒绝 qfq。
- **调度**：新增 PM2 进程 `bp-etl`（`python -m bp_etl service`），同步停用 v3 的 4 条 root
  crontab 与旧链 ad-hoc cron（分阶段，P2 完成前旧链保留但降频）。
- **清洗**：`bp_api/quant/cleaning.py` 复用（P2 扩展 v3 资产 + 触发方式改为 ETL 收尾/波次）。
- **管理页**：`/admin/market-data`（仅超级管理员）；`/admin/assets` 顶栏加入口。

## 5. 数据模型变更（新迁移 75/76/77，编号顺延）

`ddl/75_etl_health.sql`：
- `bp_etl_run(run_id, dataset, trade_date, wave, status, target_coverage, achieved_coverage,
  rows_written, sources_used jsonb, errors int, started_at, finished_at)`
- `bp_etl_source_health(stat_date, dataset, source, channel, attempts, ok, failed, banned_count,
  avg_latency_ms, p95_latency_ms, coverage_today numeric, updated_at,
  PK(stat_date,dataset,source,channel))`
- `bp_etl_quality_issue(issue_id, dataset, symbol, trade_date, kind, severity, detail jsonb,
  created_at, resolved_at)`
- `bp_etl_dataset_state(dataset PK, last_success_date, last_run_id, updated_at)`
- `bp_etl_backlog(dataset, trade_date, scope, symbol, reason, attempts, next_retry_at, created_at,
  updated_at, PK(dataset, trade_date, scope, symbol))` —— 未追赶条目持久队列（无硬停追赶的载体）

`ddl/76_drop_qfq.sql`（逻辑停用，不删数据）：
- `bp_index_config.adjust_modes` 中移除 qfq（仅 8 条 stock 配置）；
- 不改现有行情表；不删 qfq 行。

`ddl/77_etl_asset_bridge.sql`（P2 用）：
- `bp_index_config` 增 `managed_by text`（NULL=旧链；'bp_etl'=新 ETL 管理）；
- 为可回测的 v3 资产建立桥接配置（详见 P2 计划，按需启用，避免 admin 资产池爆炸）。

## 6. 数据集与源矩阵

| dataset | key | 目标表 | adjust | 锚定源 | 回退链 | 校验源 | 备注 |
|---|---|---|---|---|---|---|---|
| a_stock | 6 位 A 股码 | bp_stock_quote_daily | bfq | tencent_qt | sina_ql | em(relay)/sina | 批量快照 60–100/请求 |
| a_stock | 同上 | 同上 | hfq | sina_kline（复用 11-13 前历史基准） | tencent_kline | em(relay) | 每日逐只（原始+因子） |
| hk_stock | 5 位港股码 | bp_stock_quote_daily | bfq | sina_hk_kline | tencent_hk_kline | em(relay) | 16:15 后 |
| hk_stock | 同上 | 同上 | hfq | tencent_hk_kline | em(relay) | sina_hk_daily | 与 hfq 历史锚一致 |
| etf | 场内基金码 | bp_etf_quote_daily | bfq | tencent_qt | sina_etf_spot | em(relay) | 列表由 bp_etf_master |
| etf | 同上 | 同上 | hfq | tencent_etf_kline | em_etf_kline(relay) | sina_etf_daily* | *新浪 ETF hfq 因子待 Phase 0 验证 |
| fund_nav | 基金码 | bp_fund_nav_daily | — | em_rankhandler | em_lsjz | — | 20:00 起多波 |
| legacy_index | 指数码 | bp_index_quote_daily | bfq | 见 P2 | sina/tx/csindex/em(relay) | — | P2，521 跟踪池 |

通道定义（channel）：`direct`（服务器直连）、`relay_sg`（`http://127.0.0.1:10809`，现 bp-relay）、
`relay_prologue`（新 VLESS 节点，`127.0.0.1:10810`，P2 部署）。EM push2his 只允许走 relay 通道。

## 7. 调度、SLA 与可靠性

- **波次**：每 dataset 按 §2.1 时间点开启；每波拉取 → 写 → 质量门 → 计算覆盖 → 未达标则 10 分钟后
  下一波（退避上限 30 分钟），**无限循环直到追平**（无硬停；未追平条目进 backlog，跨交易日续跑）。
所有波次幂等（upsert + 内容校验）。
- **锁**：Postgres advisory lock `pg_try_advisory_lock(hash(dataset))`，跨进程/跨 cron 安全；
  同 dataset 并行仅允许"补缺子任务"。
- **重放**：`bp_etl run --dataset a_stock --date 2026-11-23 --wave 3` 可手动重放任意波次；
  `--force` 覆盖；全部操作写 run log。
- **失败策略（无限追赶，无硬停）**：源级错误计数 → 通道熔断（连续 N 次失败/封禁标记，
  冷却 5–30 分钟）；dataset 不达标不阻塞其它 dataset，但**该 dataset 自身不停止**——
  按 10 分钟起、最长 30 分钟的退避继续波次，直到覆盖率达到目标；仍未达标的条目（symbol×date）
  写入 `bp_etl_backlog` 持久队列，次日/之后每轮优先重试，直到追平最新可用交易日。
  升级规则：超过目标就绪 +2h 转黄色告警；次日 09:00 仍未追平转红色告警（仍不停止）。
  源封禁时降低并发/切通道，不放弃。
- **恢复**：进程重启后从 `bp_etl_dataset_state` 恢复；未完成波次自动续跑；幂等保证重复执行安全。
- **资源**：ETL 进程常驻内存 <300MB；单 dataset 并发按通道上限（direct-腾讯 6 / direct-新浪 4 /
  relay 2–4）；写入 batch 500–2000 行、单写连接；重活（rebuild）夜窗 01:00–05:00、nice/ionice。

## 8. 聚合与质量门

1. **锚定与重锚**：回退源与锚定源在重叠日按 `ratio = anchor_close / fallback_close`（取最近 3 个重叠
   日日比中位数，四舍五入 6 位）缩放 OHLC；写 `source='{fallback}:anchored'`；重锚后收益差
   与锚定源同口径校验。
2. **交叉校验**：每日对 ≥5% 样本（且 ≥100 只）做双源比对：bfq 收盘差 ≤0.1%；hfq 收益率差
   ≤0.3%（同日）；超过阈值记 issue（不阻断，除非超 5% 样本）。
3. **hfq/bfq 比率漂移**：对 (symbol, date) 计算 r=hfq/bfq；除除权日外 r 应为常数。每日扫描
   r 变化的 symbol，命中"非除权日变化"记 issue 并要求人工复核（阈值：99.5% 通过）。
4. **行数门**：当日写入行数 ≥ 上一交易日 98%（分 dataset、按 adjust），否则触发重试波次。
5. **OHLC 合规**：low ≤ open,close ≤ high；close>0；volume≥0；非法行拒写并记 issue。
6. **pct 一致性**：若源给 pct，校验与 prev_close 计算值偏差 ≤0.2%；否则本地计算（沿用现有规则）。
7. **新鲜度门**：`last_date == 最新确认交易日` 才允许 coverage 标记"当日就绪"；否则
   `lag_trading_days` 告警（管理页）。

## 9. 旧链路迁移（P2）

- 旧链 dataset：A 股指数（000/399 等，新浪/腾讯直连）、中证系（EM 独占 → relay）、全球指数
  （EM relay 或替代源）、港股指数（EM relay）、商品/国债/汇率（现源保留）。
- 迁移方式：把 `index_quote_incremental.py`/`retry_missing_quotes.py`/`xueqiu_quote_backfill.py`/
  `csindex_quote_backfill.py`/`repair_stale_quotes.py` 的有效逻辑抽成 adapter+dataset，
  统一由 `bp_etl` 调度；旧表/API 不变。
- 停用：root crontab 的 A 股/HK/ETF/基金/coverage 五条 + `/etc/cron.d/bp-index-quotes`、
  `bp-index-quotes-retry`、`bp-xueqiu-quotes`、`bp-csindex-quotes`、`bp-quote-repair`、
  `bp-data-health` 中的行情部分；`bp-ingest` 降级为"清洗/状态刷新"（P2 后由 `bp_etl` 触发）。
- 回滚：保留旧脚本与 cron 注释模板，Env `BP_ETL_MODE=off` 时自动回退旧调度；发布文档给回滚步骤。

## 10. 清洗与回测接入（L3，P2）

- **桥接**：新资产以 `bp_index_config` 配置行接回既有 `symbol@source` 体系（`managed_by='bp_etl'`），
  cleaning 读取新行情表写 `bp_quote_clean`（复用现有规则：A 股日历、插值、汇率折算、尾部护栏）。
- **触发**：ETL 收尾按 dataset 增量清洗；23:50 全量校准；失败自动重试并落 issue。
- **回测/构建器**：`repositories.list_assets/load_price_panel` 无感读取（桥接后资产 key 不变）；
  `quant/coverage.py` 口径不变；新增 v3 资产的 no-future/覆盖率回归测试。
- **管理端资产池**：`/api/assets/unified` 继续读 `bp_asset_coverage`，新增 source 维度健康信息。

## 11. 管理端"数据健康"页（/admin/market-data）

- 仅超级管理员（`require_super_admin`），非法访问 401/403；
- 内容：① 四类 + 旧指数的 last_date/当日覆盖率/目标 vs 升级告警/是否追平（红黄绿）；
  ② 每 dataset 最近 N 次 run（波次、耗时、写入、错误）；③ 源可用性矩阵（source×channel×日期：
  成功率/延迟/封禁标记）；④ 质量问题列表（可筛选/标记已解决）；⑤ 手动触发按钮
  （重放波次、补缺、刷新 coverage）——受审计日志保护。
- 入口：`/admin/assets` 顶部卡片 + `/admin/market-data`；`web/lib/api.ts` 增加对应类型。

## 12. 运维、部署、资源与回滚

- 部署：PM2 新增 `bp-etl` 进程；`deploy/ecosystem.config.cjs` 更新；`deploy/deploy.sh` 不变
  （pm2 restart 全量）。`bp-relay2`（prologue 节点）作为 systemd 单元（P2 部署，127.0.0.1:10810）。
- 监控：`pm2 logs bp-etl`；日志按天轮转（现有 logs/ 目录）；管理页只读即告警面。
- 资源红线：ETL 进程 RSS <300MB；服务器 load <2.0；PG 连接 ≤ +4；写放大受控（每日 <10 万行）。
- 回滚：`BP_ETL_MODE=off` → 旧 crontab 恢复（发布前备份 crontab）；新表保留；`bp_etl` 进程停止即可。
- 安全：监控/运维端点仅内网/管理员；不新增公网端口；不提交任何密钥/代理配置（relay 配置在服务器
  `/etc/bp-relay2/config.json`，不入 git）。

## 13. 分期与里程碑

| 期 | 内容 | 验收 | 预计任务数 |
|---|---|---|---|
| **P0** | 源时点研究（首 5 个交易日 run log 自动统计各源"首次齐备时刻"）、基准校准 | 输出 `docs/superpowers/reports/2026-11-2x-source-timing.md`，SLA 校准 | 1 |
| **P1** | `bp_etl` 框架 + 通道/限速/熔断 + 4 类 adapter + writer/锚定/质量/coverage + 四类 dataset + 历史重建 + 管理页 + qfq 停用 + 调度接入 | 交易日 16:30/17:30/23:00 全绿（含 hfq），重建校验报告通过 | 15 |
| **P2** | 旧指数链迁入 + 停用旧 cron + 清洗/回测接入（L3）+ relay2 + 运维文档 | 旧链当日就绪 ≥99%（可发布子集）；回测面板当日可用；全量测试绿 | 8 |
| **P3** | 优化：并发/成本、源扩展（新浪 ETF hfq 等）、告警通道 | 视 P1/P2 运行数据决定 | 按需 |

## 14. 已确认决策记录
- Q1 两者都做，合并到同一 ETL 链路（多源、高鲁棒、注意口径）→ §4/§9。
- Q2 按最佳实践/最完整（L1/L2/L3）→ §2/§10。
- Q3 SLA 同意（分品类，见 §2.1，Phase 0 校准）。
- Q4 只保留 bfq/hfq；锚定 + 多源聚合 + 每日源可用性监测 → §3/§6/§8（东财因服务器 IP 封禁，
  调整为"小流量通道"，A 股 hfq 锚定新浪、ETF/HK hfq 锚定腾讯——与实测和既有历史基准一致）。
- Q5 基金以可发布子集 ≥99.5% 验收，不伪造净值 → §2.3。
- Q6 服务器 root SSH 已授权（密码经 `SSH_PASSWORD` 环境变量）；部署随 PM2。
- Q7 管理页 /admin/market-data 仅管理员 → §11。
- Q8 补缺口 + 全量历史 + 增量 ETL，口径交叉校验 → §3/§8/§13。
- D1 接受多源锚定策略；D2 新 VLESS 节点作第二 relay（低流量/容灾）；D3 全做（含 L3）；
  D4 历史重建范围确认；D5 管理页位置 + qfq 逻辑停用、历史行保留。

## 15. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 腾讯 WAF 加剧（ETF/HK hfq 当日不可得） | 轮询波次 + EM relay 兜底（ETF 1,392 请求≈8.6 分钟；HK 仅补缺）+ 新浪备用；未追平持续重试并落 issue/backlog |
| 新浪限流/封 IP | 4–8 线程+节流+退避；EM relay/腾讯回退；每日源健康矩阵告警 |
| EM relay 带宽/延迟（2.7 req/s） | 仅小流量数据集使用；新增 relay_prologue 容灾；通道熔断 |
| 服务器 2C/3.7GB 内存压力 | 流式写、单进程、并发上限、夜间重建、监控 load/RSS，必要时临时升配 |
| 历史重建期间数据不可用于回测 | 重建在夜窗、按 dataset 灰度；保留旧行直到新校验通过（双写/切换） |
| 口径跳变（混源/重建基准变化） | 单锚+重锚；重建前后比率校验报告；`quote_store` 锚定优先 |
| 旧链迁移回归 | 分阶段开关 `BP_ETL_MODE`；保留旧脚本/cron 备份；逐 dataset 灰度上线 |

## 16. 交付物
- 本设计文档；
- `docs/superpowers/plans/2026-11-23-market-etl-p1-framework.md`（P1 实施计划，可多 agent 并行）；
- `docs/superpowers/plans/2026-11-23-market-etl-p2-legacy-cleaning.md`（P2 实施计划）；
- 代码、迁移 75/76/77、测试、`/admin/market-data`、运维 runbook（执行阶段产出）。

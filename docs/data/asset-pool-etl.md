# 资产池全量数据与增量 ETL

## 1. 数据表

| 表 | 内容 | 主键 |
|---|---|---|
| `bp_stock_master` | A 股主数据（5,227 只） | stock_code |
| `bp_stock_quote_daily` | A 股日线，三口径：`bfq` 不复权 / `qfq` 前复权 / `hfq` 后复权 | (symbol, trade_date, source, adjust) |
| `bp_fund_master` | 基金主数据（代码/名称/是否 ETF） | fund_code |
| `bp_fund_nav_daily` | 基金净值（日频） | (fund_code, trade_date) |
| `bp_index_quote_daily` | 指数行情（原始 OHLCV） | 现有 |

迁移：`ddl/71_stock_quotes.sql`。

### 复权口径（前端中文名与含义）

| 代码 | 中文 | 含义 | 用途 |
|---|---|---|---|
| `bfq` | 不复权 | 原始成交价，分红/拆股处价格跳空 | 展示真实成交价、涨跌幅 |
| `qfq` | 前复权 | 以**最新**价格为基准向前复权 | 图表展示（价格连续） |
| `hfq` | 后复权 | 以**上市首日**为基准向后复权，分红再投 | **回测默认**（避免分红/拆股造成假信号） |

前端展示统一用中文，并在资产行/开关上加 tooltip 说明；builder 回测固定使用 `hfq`。

## 2. 全量回填（本机运行，写生产库）

```bash
# A 股：腾讯行情，约 5,227 只 × 3 口径 × 6 年；断点续跑（跳过已有 symbol+adjust）
python scripts/local_backfill_stocks.py --years 6 --threads 12

# 基金：天天基金 pingzhongdata，约 2.8 万只；断点续跑（跳过已有基金）
python scripts/local_backfill_funds.py --threads 12
```

- 连接串参数：`BP_BACKFILL_DB_HOST`（默认生产库 81.71.158.239）、`.env` 的 `PG*`；
- 每个线程一个持久连接 + `synchronous_commit=off` + 批量提交（股票 20 只/次、基金 10 只/次），降低 WAN 往返与 WAL 压力；
- 失败样本（停牌/退市/无效代码）会跳过并记录日志，不影响整体。

## 3. 服务器增量（cron 已安装）

| 时间 | 任务 | 说明 |
|---|---|---|
| 周一至周五 23:35 | `incremental_stock_quotes.py --mode daily` | 腾讯批量快照（60 只/请求），仅 15:10 收盘确认后写当日 `bfq` |
| 周日 02:30 | `incremental_stock_quotes.py --mode weekly --days 40 --threads 6` | 近 40 天三口径 kline 增量补齐（分红/拆股会改变历史复权因子） |
| 周一至周五 21:50 | `incremental_fund_nav.py --threads 6 --days 30` | 基金净值日增量（只写近 30 天，跳过已更新基金） |

日志：`/opt/balanced-portfolio/logs/etl-stock-daily.log`、`etl-stock-weekly.log`、`etl-fund-daily.log`。
脚本均在 `scripts/`，可手动执行；数据库连接优先 `BP_ETL_DB_HOST`（默认 127.0.0.1）。

## 4. 覆盖率报告

```bash
python scripts/asset_coverage_report.py --json /tmp/coverage.json
```

输出：A 股三口径的覆盖股票数 / 覆盖率 / 起止日期 / 近 7 日有数据数；基金覆盖；指数行情覆盖。用于发布前数据完整性校验。

## 5. 前端入口

- `/assets`：统一资产池（股票 / 指数 / 基金 / ETF 搜索，覆盖状态，三口径中文切换说明）；
- `/builder?mode=basket`：选股/资产池弹窗，选中股票按后复权口径加入；
- API：`GET /api/assets/unified?q=&type=&adjust=&limit=&offset=`（缓存 60s）。


## 6. 数据源降级（重要）

- 腾讯 `web.ifzq.gtimg.cn` 在**本机高频请求**后会触发 WAF（返回 HTML 501 页），此时 `local_backfill_stocks.py` 会大量报 `RuntimeError empty`；
- 已支持 `--source sina`（akshare `stock_zh_a_daily`，新浪口径，自带复权因子）：`python scripts/local_backfill_stocks.py --source sina --years 6 --threads 8`；
- 约 17s/只（1 线程，含 3 口径），8 线程约 3 小时可回填 5,000 只；
- 服务器增量任务走服务端 IP，不受本机 WAF 影响；若服务器也被限流，可切 `--source sina`。


## 7. 全量回填结果（2026-11-16）

| 数据 | 覆盖 | 行数 | 区间 |
|---|---|---|---|
| A 股 bfq（不复权） | 5,396 只（含主数据外的退市/北交所代码） | 7,341,601 | 2020-01-02 ~ 2026-11-13 |
| A 股 qfq（前复权） | 5,394 只 | 7,337,479 | 同上 |
| A 股 hfq（后复权） | 5,394 只 | 7,341,740 | 同上 |
| 基金净值 | **27,978 只（100% 基金列表）** | 33,092,396 | ~2026-11-13 |

- 回填方式：服务器侧新浪原始行情 + hfq/qfq 因子（3 请求/只），12 线程约 16 分钟完成 A 股；基金 8 线程约 2 小时完成；
- **抽样校验**（scripts/validate_asset_data.py）：A 股 19/19 与新浪实时接口一致（收盘价+日期）；基金 10/10 与天天基金最新净值一致；三口径因子关系抽检通过；
- 覆盖率报告：docs/data/coverage-latest.json；校验结果：docs/data/validation-latest.json；
- 指数行情覆盖 455/521（87%），缺口为 MSCI/创业板细分/港股通细分等无公开行情源的自定义指数，非本次 A股/基金 ETL 范围；
- 服务器增量任务保持：A 股日快照（工作日 23:35）、三口径周补齐（周日 02:30）、基金净值日增量（工作日 21:50），日志在 `/opt/balanced-portfolio/logs/etl-*.log`。

## 8. 港股 / 场内基金 / 基金净值日更（2026-11-22 补齐）

### 8.1 表结构

| 表 | 内容 | 主键 |
|---|---|---|
| `bp_stock_quote_daily` | A 股**与港股**日线（港股 symbol 为 5 位码，如 `00700`），三口径 | `(symbol, trade_date, source, adjust)` |
| `bp_etf_master` | 场内基金主数据（ETF/LOF/封闭式） | `etf_code` |
| `bp_etf_quote_daily` | 场内基金日线，三口径 | `(etf_code, trade_date, source, adjust)` |
| `bp_fund_nav_daily` | 场外基金净值（全市场） | `(fund_code, trade_date)` |

迁移：`ddl/73_etf_quotes.sql`、`ddl/74_sgd_fx.sql`（补 SGDCNY 汇率对）。

### 8.2 全量回填

```bash
# 港股（约 2,800 只，默认近 6 年；--full 才从 1990 起）
python scripts/hk_stock_quotes.py --mode backfill --threads 8

# 场内基金（先同步列表，再回填三口径）
python scripts/etf_quotes.py --mode sync
python scripts/etf_quotes.py --mode backfill --threads 8

# 基金净值缺口补齐（rankhandler 批量榜 + lsjz 逐只补缺）
python scripts/incremental_fund_nav.py --gap-limit 32000
```

限速：港股/ETF 走腾讯 `ifzq.gtimg.cn`（2026-11-22 起；旧 `web.ifzq` 主机会返回 HTML 501 WAF 页），批量请求仍可能触发限流；两个脚本内置
**全局最小请求间隔**（`BP_HK_MIN_INTERVAL` / `BP_ETF_MIN_INTERVAL`，默认 60ms/50ms）
与指数退避重试，失败清单写入 `logs/hk-failures-*.txt` / `logs/etf-failures-*.txt`。

### 8.3 服务器增量（cron）

| 时间 | 任务 | 说明 |
|---|---|---|
| 工作日 15:10 后任意 | `incremental_stock_quotes.py --mode daily` | A 股当日 bfq 快照 |
| 工作日 23:40 | `hk_stock_quotes.py --mode daily` | 港股当日 bfq 快照（16:15 收盘确认后） |
| 周日 02:40 | `hk_stock_quotes.py --mode weekly --days 40` | 港股近 40 天三口径补齐 |
| 工作日 23:45 | `etf_quotes.py --mode daily` | 场内基金当日 bfq 快照 |
| 周日 02:50 | `etf_quotes.py --mode weekly --days 40` | 场内基金近 40 天三口径补齐 |
| 工作日 22:30 | `incremental_fund_nav.py` | 基金净值：rankhandler 全量榜 + lsjz 补缺 |
| 工作日 23:55 | `refresh_asset_coverage.py` | 覆盖快照（stock/etf/fund/index） |

### 8.4 口径提醒

- 现价/展示口径一律 **不复权 bfq**；回测默认 hfq。
- 腾讯 ETF `hfq` 是「单位累计净值」口径（每份 1.0 起步），与东财后复权绝对价不同，
  **只可比收益率**；文档与前端 tooltip 已标注。
- 港股/场内基金未做人民币折算（`bp_quote_clean` 仍只服务指数/资产池），
  `/api/v1/market/*` 返回原币价格，汇率走 `/api/v1/market/fx`。

## 9. 统一 ETL（bp_etl，2026-11 起，替代第 3/8.3 节的 ad-hoc cron）

> 设计：`docs/superpowers/specs/2026-11-23-unified-market-etl-design.md`
> 计划：`docs/superpowers/plans/2026-11-23-market-etl-p1-framework.md` / `…-p2-legacy-cleaning.md`

### 9.1 数据集与锚定源（只保留 bfq/hfq；qfq 已停用）

| dataset | 表 | bfq 锚定 | hfq 锚定 | 目标就绪 | 说明 |
|---|---|---|---|---|---|
| a_stock | bp_stock_quote_daily | tencent_qt（当日批量） | sina_kline（库内 bfq × 新浪因子） | bfq 15:30 / hfq 16:30 | 5,227 只 |
| hk_stock | bp_stock_quote_daily | sina_hk_kline | tencent_hk_kline | bfq 16:30 / hfq 17:30 | 2,811 只；EM relay 兜底 |
| etf | bp_etf_quote_daily | tencent_qt | tencent_etf_kline | bfq 15:30 / hfq 16:30 | 1,392 只；EM relay 兜底 |
| fund_nav | bp_fund_nav_daily | em_rankhandler（批量榜） | — | 23:00 | 28,101 只，lsjz 补缺 |

**无限追赶**：任何数据集未追平最新交易日时，按 10→30 分钟退避持续波次，未达标条目落
`bp_etl_backlog` 跨交易日续跑，直到 `bp_etl_dataset_state.last_success_date` 追平；
目标时点只触发升级告警，不停止。运行/源健康/质量问题分别落
`bp_etl_run` / `bp_etl_source_health` / `bp_etl_quality_issue`，管理端 `/admin/market-data` 只读展示。

### 9.2 运维命令

```bash
pm2 status bp-etl                       # 常驻进程（BP_ETL_MODE=off 时不执行）
pm2 logs bp-etl --lines 100 --nostream
python -m bp_etl health                 # dataset 状态/最近运行/backlog
python -m bp_etl run --dataset a_stock --adjust hfq --waves 1 --json   # 手动波次
python -m bp_etl rebuild --dataset all --json                          # 夜窗单锚重建
python -m bp_etl verify --out /tmp/etl-verify.json                     # 覆盖/比率漂移校验
bash scripts/etl_legacy_cron_toggle.sh dry-run                         # 旧 cron 下线预演
```

### 9.3 灰度与回滚

1. 代码发布后 `BP_ETL_MODE=shadow` 启动 `bp-etl`：只拉取/校验/写 run 与 issue，不写行情表；
2. 手工 `python -m bp_etl run --dataset …` 核对行数与覆盖；
3. 切 `BP_ETL_MODE=on`，确认连续 2 个交易日达标后，用 `etl_legacy_cron_toggle.sh disable` 停旧 cron；
4. 回滚：`BP_ETL_MODE=off` + `etl_legacy_cron_toggle.sh restore`（脚本自动备份 crontab 与 cron.d 文件）。


## 10. L3：v3 资产接入清洗/回测（桥接，2026-11 起）

v3 行情在 `bp_stock_quote_daily` / `bp_etf_quote_daily`；回测面板只读 `bp_quote_clean`
（key = `symbol@source`）。桥接做法（迁移 77 + 脚本）：

1. `ddl/77_etl_asset_bridge.sql`：`bp_index_config.managed_by` 列 + 注册
   `etl_a_stock`/`etl_hk_stock`/`etl_etf` 三个数据源；
2. `python scripts/seed_etl_assets.py --dry-run` 预演 → `--apply` 写入配置
   （A股 5,227 / 港股 2,811 / ETF 1,392，`adjust='hfq'`，`adjust_modes={bfq,hfq}`，
   `currency` 分别为 CNY/HKD/CNY，`managed_by='bp_etl'`）；
3. `bp_api/quant/cleaning.py` 对 `etl_*` 源从 v3 表读原始价，仍按既有口径
   （A股日历对齐/内部插值/港股 CNY 折算/尾部护栏）写 `bp_quote_clean`；
   `refresh_asset_status` 的 raw 侧 MAX/COUNT 自动路由到 v3 表；
4. 回测/构建器无感复用（资产 key `600036@etl_a_stock` 等）。

运维顺序（首次）：

```bash
python scripts/seed_etl_assets.py --dry-run          # 确认规模
python scripts/seed_etl_assets.py --apply            # 写入配置（幂等）
python -m bp_etl rebuild --dataset all               # 先保证 v3 原始数据齐
# 触发清洗（ETL 收尾自动按符号增量；首次全量可手动）
.venv/bin/python -c "from bp_api.quant.cleaning import rebuild_clean; from bp_ingest.db import connect; from bp_ingest.config import load_config; \
  c=connect(load_config().db); print(rebuild_clean(c)); c.commit()"
```

验收：`python -m bp_etl verify --out /tmp/etl-verify.json`；
回测样例（含 `etl_*` 资产）跑通且 `test_backtest.py` 无未来函数约束通过。


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

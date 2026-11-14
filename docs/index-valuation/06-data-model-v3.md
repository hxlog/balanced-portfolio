# 数据模型 v3（基于生产库真实约束核定）

> 核对时间：2026-11-14 ｜ 依据：DBX 直连 `postgres@100.75.138.35` 的 `pg_constraint` / `pg_stat_user_tables` / `timescaledb_information.hypertables`
> 原则：**能用旧表就不建新表**；必须新建的，主键/外键/CHECK 全部显式声明；PiT 语义落到列上。

## 0. 生产库现状（实测）

| 事实 | 数值 |
|---|---|
| 表总数 | 30 张 `bp_*` |
| Timescale hypertable | 3 张：`bp_index_quote_daily`(1274 chunks)、`bp_quote_clean`(1275)、`bp_cffex_contract_daily`(495) |
| 最大表 | `bp_backtest_benchmark` 20.3 万行 / 29MB；`bp_backtest_nav` 10.1 万行 / 23MB |
| 行情主键 | `(symbol, source, trade_date)`，**无 adjust** |
| 资产池 | `bp_index_config` 287 行，`UNIQUE(symbol, source)` + `UNIQUE(row_hash)` |
| 组合方法 | `ck_bp_portfolio_method` 仅 4 个值 |
| 组合资产 | PK `(portfolio_id, symbol, source, quadrant)`，`quadrant` 仅 4 值 |
| 数据源 | `bp_data_source` PK=code，`is_addable` 控制可添加性 |

### 0.1 现有约束的三个硬阻塞点

1. `ck_bp_portfolio_asset_quadrant` 只允许 4 象限 → **篮子模式无法落库**。
2. `ck_bp_portfolio_method` 只允许 4 方法 → **最大 Sortino / 最小方差 / 等权 / 风险预算无法落库**。
3. quote 两表主键无 `adjust` → **三种复权互相覆盖**（详见 `04-quote-adjust-migration.md`）。

## 1. 复用与修改清单（不新建 = 优先）

| # | 现有表 | 处理 | 迁移 |
|---|---|---|---|
| 1 | `bp_data_source` | **复用**：新增 3 行 `pingan_index` / `csindex_value` / `binance_futures`（`is_addable=false`） | 52 |
| 2 | `bp_trading_calendar` | **复用**：估值按 `market=A股` 日历对齐，不新建日历表 | — |
| 3 | `bp_task` / `bp_data_refresh_run` | **复用**：估值/合约抓取写任务与运行审计；`ck_bp_task_type` 增加 2 个类型 | 52 |
| 4 | `bp_index_config` | **修改**：`+adjust TEXT DEFAULT 'bfq'`、`+index_code`（可空 FK 到 master） | 51 |
| 5 | `bp_index_quote_daily` / `bp_quote_clean` | **修改**：`+adjust` 并纳入主键（见 04 文档） | 51 |
| 6 | `bp_portfolio` | **修改**：`+mode`（quadrant/basket）、放宽 method CHECK 至 8 个 | 53 |
| 7 | `bp_portfolio_asset` | **修改**：quadrant CHECK 加 `basket`、`+adjust` | 53 |
| 8 | `bp_asset_data_status` | **复用**：股票/指数探测状态沿用 | — |
| 9 | `bp_crypto_meta` | **复用**：加密看板 meta（新增 key 命名空间 `futures:*`） | — |
| 10 | `bp_backtest_*` | **复用**：篮子模式复用全部回测结果表（method 维度天然支持新方法） | — |

## 2. 新增表（12 张）

### 2.1 指数主数据（1 张）

```sql
CREATE TABLE bp_index_master (
    index_code     TEXT PRIMARY KEY,              -- 930641 / H30374 / 000300（保留原码，勿补零）
    market         TEXT NOT NULL,                 -- CSI | SH | SZ | CNI | HK | US
    wind_code      TEXT,                          -- 930641.CSI
    name           TEXT NOT NULL,
    short_name     TEXT,
    index_type     TEXT,                          -- 宽基 | 行业 | 主题 | 策略 | 全球
    publisher      TEXT,
    base_date      DATE,
    base_point     NUMERIC(20,6),
    income_method  TEXT,                          -- 价格指数 | 全收益 | 净收益
    weight_method  TEXT,
    intro          TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    is_tracked     BOOLEAN NOT NULL DEFAULT TRUE, -- 是否进入每日估值抓取
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_index_master_market CHECK (market IN ('CSI','SH','SZ','CNI','HK','US')),
    CONSTRAINT uq_index_master_wind UNIQUE (wind_code)
);
CREATE UNIQUE INDEX uq_index_master_code_market ON bp_index_master (index_code, market);
CREATE INDEX idx_index_master_tracked ON bp_index_master (is_tracked, index_type);
```

> 为什么不复用 `bp_index_config`：后者是「可回测资产池」(287 行)，有 `UNIQUE(symbol,source)` 与 `is_deleted` 语义；估值域要装 521+ 只且绝大多数不参与回测。分离后 `bp_index_config.index_code` 做桥接。

### 2.2 估值日频宽表（1 张）

```sql
CREATE TABLE bp_index_valuation_daily (
    index_code      TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    calc_src        TEXT NOT NULL REFERENCES bp_data_source(code),
    pe_ttm          NUMERIC(14,4),
    pe_static       NUMERIC(14,4),
    pb              NUMERIC(14,4),
    dividend_yield_ttm  NUMERIC(10,6),
    dividend_yield_lyr  NUMERIC(10,6),
    roe_ttm         NUMERIC(10,4),
    roa_ttm         NUMERIC(10,4),
    bond10y         NUMERIC(10,6),
    erp             NUMERIC(10,6),                -- dividend_yield_ttm - bond10y
    pe_basis        TEXT,                         -- equal_weight_ttm | cap_weight_ttm | official_pe1 | official_pe2 | vendor_default
    pb_basis        TEXT,
    div_basis       TEXT,                         -- ttm | lyr
    level_pe        TEXT,                         -- 低估 | 中性 | 高估
    level_pb        TEXT,
    level_dividend  TEXT,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw             JSONB,
    PRIMARY KEY (index_code, trade_date, calc_src),
    CONSTRAINT ck_val_pe  CHECK (pe_ttm IS NULL OR pe_ttm > 0),
    CONSTRAINT ck_val_pb  CHECK (pb IS NULL OR pb > 0),
    CONSTRAINT ck_val_div CHECK (dividend_yield_ttm IS NULL OR dividend_yield_ttm BETWEEN -1 AND 100)
);
CREATE UNIQUE INDEX uq_val_primary ON bp_index_valuation_daily (index_code, trade_date) WHERE is_primary;
CREATE INDEX idx_val_date ON bp_index_valuation_daily (trade_date DESC, is_primary);
CREATE INDEX idx_val_code ON bp_index_valuation_daily (index_code, trade_date DESC);
```

### 2.3 估值历史长表（1 张，承接平安 5 年周频 + 中证官网日频）

```sql
CREATE TABLE bp_index_valuation_series (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    trade_date  DATE NOT NULL,
    metric      TEXT NOT NULL,
    calc_src    TEXT NOT NULL REFERENCES bp_data_source(code),
    value       NUMERIC(16,6) NOT NULL,
    is_weekly   BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, trade_date, metric, calc_src),
    CONSTRAINT ck_series_metric CHECK (metric IN ('pe_ttm','pe_static','pb','dividend_yield_ttm','dividend_yield_lyr','erp'))
);
CREATE INDEX idx_series_lookup ON bp_index_valuation_series (index_code, metric, trade_date DESC);
```

### 2.4 分位预计算（1 张）

```sql
CREATE TABLE bp_index_percentile (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    as_of_date  DATE NOT NULL,
    metric      TEXT NOT NULL,
    window_key  TEXT NOT NULL,        -- 5y | 10y | all
    calc_src    TEXT NOT NULL,
    pct         NUMERIC(8,4),
    mean        NUMERIC(16,6),
    sd          NUMERIC(16,6),
    p20 NUMERIC(16,6), p50 NUMERIC(16,6), p80 NUMERIC(16,6),
    min_value   NUMERIC(16,6),
    max_value   NUMERIC(16,6),
    sample_size INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, as_of_date, metric, window_key, calc_src),
    CONSTRAINT ck_pct_window CHECK (window_key IN ('5y','10y','all')),
    CONSTRAINT ck_pct_sample CHECK (sample_size >= 0)
);
CREATE INDEX idx_pct_scan ON bp_index_percentile (as_of_date DESC, metric, window_key);
```

### 2.5 成分股与行业权重（3 张 + 1 张主数据）

```sql
CREATE TABLE bp_stock_master (
    stock_code   TEXT PRIMARY KEY,        -- 600036 / 002352（6 位）
    market       TEXT NOT NULL,           -- SH | SZ | BJ
    board        TEXT,                    -- 主板 | 创业板 | 科创板 | 北交所
    name         TEXT NOT NULL,
    industry_l1  TEXT,
    industry_l2  TEXT,
    is_st        BOOLEAN NOT NULL DEFAULT FALSE,
    is_delisted  BOOLEAN NOT NULL DEFAULT FALSE,
    listed_at    DATE,
    delisted_at  DATE,
    adjust_modes TEXT[] NOT NULL DEFAULT ARRAY['bfq','qfq','hfq'],
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bp_index_constituent (
    index_code     TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    stock_code     TEXT NOT NULL REFERENCES bp_stock_master(stock_code),
    weight         NUMERIC(10,6),
    rank           INTEGER,
    source         TEXT NOT NULL,
    announced_at   DATE,
    PRIMARY KEY (index_code, effective_date, stock_code),
    CONSTRAINT ck_const_weight CHECK (weight IS NULL OR weight BETWEEN 0 AND 100)
);

CREATE TABLE bp_index_industry_weight (
    index_code     TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    scheme         TEXT NOT NULL,       -- sw_l1 | csi_l1
    industry_code  TEXT NOT NULL,
    industry_name  TEXT NOT NULL,
    weight         NUMERIC(10,6),
    PRIMARY KEY (index_code, effective_date, scheme, industry_code)
);
```

### 2.6 跟踪基金（2 张）

```sql
CREATE TABLE bp_fund_master (
    fund_code    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    company_code TEXT,
    company_name TEXT,
    fund_type    TEXT,
    risk_grade   TEXT,
    is_etf       BOOLEAN NOT NULL DEFAULT TRUE,
    listing_date DATE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bp_index_tracker_fund (
    index_code  TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    fund_code   TEXT NOT NULL REFERENCES bp_fund_master(fund_code),
    trade_date  DATE NOT NULL,
    aum         NUMERIC(20,2),          -- 规模（元）
    shares      NUMERIC(20,4),          -- 份额
    nav         NUMERIC(12,4),
    premium_rate NUMERIC(10,6),         -- 折溢价率
    net_subscribe_amount NUMERIC(20,2), -- 净申购额
    net_subscribe_ratio  NUMERIC(10,6), -- 净申购率
    source      TEXT NOT NULL,
    PRIMARY KEY (index_code, fund_code, trade_date)
);
```

### 2.7 全市场估值 + 宏观序列（2 张）

```sql
CREATE TABLE bp_market_valuation_daily (
    board      TEXT NOT NULL,           -- all | main | chinext | star | bse
    trade_date DATE NOT NULL,
    pe_median  NUMERIC(14,4),
    pe_equal   NUMERIC(14,4),
    pb_median  NUMERIC(14,4),
    pb_equal   NUMERIC(14,4),
    pct_pe     NUMERIC(8,4),
    pct_pb     NUMERIC(8,4),
    sample_size INTEGER NOT NULL,
    calc_src   TEXT NOT NULL,
    PRIMARY KEY (board, trade_date),
    CONSTRAINT ck_mkt_board CHECK (board IN ('all','main','chinext','star','bse'))
);

CREATE TABLE bp_macro_series (
    series_code TEXT NOT NULL,          -- cn_10y_yield | cn_2y_yield | cn_term_spread
    trade_date  DATE NOT NULL,
    value       NUMERIC(16,8) NOT NULL,
    unit        TEXT,
    source      TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, trade_date)
);
-- 国债收益率存在这里，避免为 2Y/30Y/利差反复建表；ERP 用 cn_10y_yield 计算
```

### 2.8 对外 API 鉴权（2 张）

```sql
CREATE TABLE bp_api_token (
    token_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    prefix       CHAR(8) NOT NULL,               -- 明文前 8 位，用于定位
    token_hash   CHAR(64) NOT NULL,              -- sha256(secret + pepper)
    scopes       TEXT[] NOT NULL DEFAULT ARRAY['quotes']::TEXT[],
    user_id      BIGINT REFERENCES bp_user(user_id) ON DELETE SET NULL,
    expires_at   TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_by   BIGINT REFERENCES bp_user(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_api_token_hash UNIQUE (token_hash),
    CONSTRAINT uq_api_token_prefix UNIQUE (prefix),
    CONSTRAINT ck_api_token_scopes CHECK (scopes <@ ARRAY['quotes','valuation','percentile','crypto','portfolio']::TEXT[])
);

CREATE TABLE bp_api_request_log (
    log_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_id   UUID REFERENCES bp_api_token(token_id) ON DELETE SET NULL,
    path       TEXT NOT NULL,
    status     SMALLINT,
    latency_ms INTEGER,
    rows       INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_api_log_time ON bp_api_request_log (created_at DESC);
```

### 2.9 收藏与数据质量（2 张）

```sql
CREATE TABLE bp_user_favorite_index (
    user_id    BIGINT NOT NULL REFERENCES bp_user(user_id) ON DELETE CASCADE,
    index_code TEXT NOT NULL REFERENCES bp_index_master(index_code) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, index_code)
);

CREATE TABLE bp_data_quality_log (
    log_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    index_code   TEXT, trade_date DATE, metric TEXT,
    primary_src  TEXT, check_src TEXT,
    primary_value NUMERIC(16,6), check_value NUMERIC(16,6),
    rel_diff     NUMERIC(10,6),
    level        TEXT NOT NULL,                  -- warn | error
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_dq_level CHECK (level IN ('warn','error'))
);
```

### 2.10 加密合约（8 张，按 binance 调研结论）

| 表 | 主键 | 说明 | 分区 |
|---|---|---|---|
| `bp_crypto_futures_symbol` | (symbol, observed_at) | 合约元数据 SCD | — |
| `bp_crypto_futures_kline_5m` | (symbol, open_time) | 5m K 线全量 | hypertable(1 day) |
| `bp_crypto_futures_micro_5m` | (symbol, bucket_time) | OI + 4 类多空比 | hypertable(7 day) |
| `bp_crypto_futures_premium_snapshot` | (symbol, observed_at) | mark/index/funding 快照 | hypertable(7 day) |
| `bp_crypto_futures_funding_rate` | (symbol, funding_time) | 资金费率历史 | — |
| `bp_crypto_futures_micro_1h` / `_1d` | (symbol, bucket_time) | 聚合 | hypertable(90 day) |
| `bp_crypto_futures_percentile` | (symbol, metric, as_of, window_key) | 分位 | — |

## 3. 关联关系（ER 摘要）

```
bp_data_source(code) ──< bp_index_valuation_daily(calc_src)
                    ──< bp_index_valuation_series(calc_src)
                    ──< bp_index_quote_daily(source)

bp_index_master(index_code) ──< bp_index_valuation_daily / _series / _percentile
                            ──< bp_index_constituent >── bp_stock_master(stock_code)
                            ──< bp_index_industry_weight
                            ──< bp_index_tracker_fund >── bp_fund_master(fund_code)
                            ──< bp_user_favorite_index >── bp_user(user_id)

bp_index_config(index_code) ──> bp_index_master(index_code)   -- 可空桥接
bp_portfolio(portfolio_id) ──< bp_portfolio_asset >── bp_index_config
bp_portfolio(portfolio_id) ──< bp_backtest_*                    -- 篮子复用

bp_api_token(token_id) ──< bp_api_request_log
```

**唯一键要点**
| 表 | 唯一约束 | 作用 |
|---|---|---|
| `bp_index_valuation_daily` | `UNIQUE(index_code, trade_date) WHERE is_primary` | 每日仅一个主口径 |
| `bp_index_valuation_series` | PK `(index_code, trade_date, metric, calc_src)` | 多源同日同指标并存 |
| `bp_index_percentile` | PK 含 `window_key` | 5y/10y/all 三个窗口并存 |
| `bp_index_constituent` | PK `(index_code, effective_date, stock_code)` | PiT 快照 |
| `bp_api_token` | UNIQUE(hash) + UNIQUE(prefix) | 防碰撞 + 快速定位 |
| `bp_stock_master` | PK stock_code | 三复权与成分股共用 |

## 4. 容量估算

| 表 | 日均增量 | 年增量 | 5 年 |
|---|---|---|---|
| `bp_index_valuation_daily` | ~1,000（521×2 源） | 25 万 | 125 万 |
| `bp_index_valuation_series` | 首拉 ~80 万；日增 ~800 | 20 万 | 180 万 |
| `bp_index_percentile` | ~3,000（521×6 指标×3 窗口/周更） | 15 万 | 75 万 |
| `bp_index_constituent` | 月更 ~1.5 万 | 18 万 | 90 万 |
| `bp_index_tracker_fund` | ~1,000 | 25 万 | 125 万 |
| `bp_crypto_futures_kline_5m` | 30×288=8,640 | 315 万 | 1,575 万（hypertable） |
| `bp_crypto_futures_micro_5m` | 30×4×288=34,560 | 1,260 万 | — |

## 5. 迁移编排（51~56）

| 编号 | 内容 | 可回滚 |
|---|---|---|
| 51 | quote 两表 + config 加 adjust；`bp_index_config.index_code` | 是（删列） |
| 52 | 数据源 3 行 + task_type 扩展 + `bp_index_master` + 估值 4 表 | 是 |
| 53 | `bp_portfolio.mode` + method CHECK 放宽 + asset quadrant/adjust | 是 |
| 54 | 成分股 4 表 + 跟踪基金 2 表 + 全市场估值 + 宏观序列 | 是 |
| 55 | API token 2 表 + 收藏 + 质量日志 | 是 |
| 56 | 加密合约 8 表（hypertable） | 是 |

> 全部同步进 `ddl/schema.sql` 基线（全新环境只跑 schema）；已部署环境只跑未应用编号。

## 6. 待确认（Round 5）

1. `bp_index_master` 是否也要装"可回测指数"之外的品类（如港股/全球指数）？现方案 market 已留 HK/US。
2. `bp_stock_master` 是否要存财务字段（ROE/净利润）？现方案只存身份与行业，财务走单独表或直接存快照。
3. 估值日频表是否要按年分区（当前估 125 万/5 年，无需分区；若接入 3 源以上再议）。
4. 加密 5m 表保留策略：micro 18 个月 / kline 永久，是否接受。
# D6 落地设计：行情「复权维度」一次性治理（含全站回归清单）

> 目标：让 `bfq / qfq / hfq` 三种口径**同时**存在于行情主干表，且语义显式、可查询、可回测；
> 约束：**不得破坏改动前任何全站功能**（回测、coverage、CFFEX、crypto、admin、API）。

---

## 一、现状与根因（已核验）

| 事实 | 位置 |
|---|---|
| 原始行情主键 `(symbol, source, trade_date)`，无复权维度 | `ddl/schema.sql:161` |
| 清洗表同构主键 | `ddl/schema.sql:192` |
| `row_hash` 是 **GENERATED ALWAYS STORED** 列：`md5(symbol\|source\|trade_date)` | `ddl/schema.sql:156-158` |
| 两张表都是 TimescaleDB hypertable（按 `trade_date` 90 天分片） | `ddl/schema.sql:164-168, 196-200` |
| 写入唯一入口 `_UPSERT_SQL`，`ON CONFLICT (symbol, source, trade_date)` | `bp_ingest/db.py:171-191` |
| 复权目前藏在配置 JSON：`bp_index_config.extra_params.adjust`（仅 ETF，默认 hfq） | `bp_ingest/sources.py:455,560-562`；前端 `web/lib/asset-form.ts:36-38` |
| 前端资产表单只允许 ETF 选复权 | `web/components/CreateAssetDialog.tsx:219`；`web/app/admin/assets/page.tsx:563-566` |

**根因**：复权口径被表达在「资产配置」层（一个 config 一行），但主线只有一条，同一 `(symbol, source)` 配两种复权会**互相覆盖**。

**已确认的历史数据陷阱（必须处理）**：现有 `etf_em / etf_tx` 的 close **本身就是后复权**（`sources.py:455` 默认 `hfq`）。迁移时若统一把存量标成 `bfq`，ETF 历史收益会被静默改变 → 回测结果漂移。

---

## 二、目标模型（三条不变式）

1. **一个 (symbol, source, adjust) = 一条独立序列**；主键 `(symbol, source, adjust, trade_date)`。
2. **默认口径是 bfq**（与现有指数/商品/债券行为一致），存量 ETF 数据回填为 hfq。
3. **组合侧显式声明口径**：`bp_portfolio_asset.adjust`，默认 `hfq`（股票/ETF 全收益偏好），指数默认 `bfq`；回测只读与声明口径一致的序列。

---

## 三、DDL 迁移草案（`ddl/51_quote_adjust_dimension.sql`）

```sql
-- 1) 原始行情表
ALTER TABLE bp_index_quote_daily ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
ALTER TABLE bp_index_quote_daily DROP CONSTRAINT IF EXISTS pk_bp_index_quote_daily;
ALTER TABLE bp_index_quote_daily
    ADD CONSTRAINT pk_bp_index_quote_daily PRIMARY KEY (symbol, source, adjust, trade_date);
DROP INDEX IF EXISTS idx_bp_quote_symbol_source_date;
CREATE INDEX idx_bp_quote_symbol_source_adj_date
    ON bp_index_quote_daily (symbol, source, adjust, trade_date DESC);

-- 2) row_hash 重建（含 adjust；不改表达式则同 symbol+date 三口径撞唯一性）
ALTER TABLE bp_index_quote_daily DROP COLUMN IF EXISTS row_hash;
ALTER TABLE bp_index_quote_daily ADD COLUMN row_hash CHAR(32)
    GENERATED ALWAYS AS (md5(symbol || '|' || source || '|' || adjust || '|' || (trade_date - DATE '1970-01-01')::text)) STORED;

-- 3) 清洗表同构（同样处理 row_hash 若存在）
ALTER TABLE bp_quote_clean ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
ALTER TABLE bp_quote_clean DROP CONSTRAINT IF EXISTS pk_bp_quote_clean;
ALTER TABLE bp_quote_clean
    ADD CONSTRAINT pk_bp_quote_clean PRIMARY KEY (symbol, source, adjust, trade_date);

-- 4) 配置层：复权从 extra_params 升为一等列（保留 extra_params 兼容）
ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'bfq';
UPDATE bp_index_config
   SET adjust = COALESCE(extra_params->>'adjust', 'bfq')
 WHERE extra_params ? 'adjust';

-- 5) 组合资产：显式口径
ALTER TABLE bp_portfolio_asset ADD COLUMN IF NOT EXISTS adjust TEXT NOT NULL DEFAULT 'hfq';

-- 6) 存量数据回填（关键！按现有真实口径打标，而不是一律 bfq）
UPDATE bp_index_quote_daily SET adjust = 'hfq'
 WHERE source IN ('etf_em','etf_tx') AND adjust = 'bfq';
UPDATE bp_quote_clean SET adjust = 'hfq'
 WHERE source IN ('etf_em','etf_tx') AND adjust = 'bfq';
```

> **TimescaleDB 注意事项**
> - 主键必须仍包含分区列 `trade_date`（本方案满足）；
> - `ADD COLUMN ... DEFAULT` 在 PG11+ 是元数据级操作，但**加生成列会触发表重写**；行情表约 70 万行、clean 表同量级，预计秒级到分钟级，需在部署窗口执行并先做 `pg_dump`；
> - 若担心重写耗时，可先 `DROP COLUMN row_hash`（quote 表无任何读取方，已 grep 确认），把「重建」降级为「删除」，风险最小。

---

## 四、代码改造清单（按依赖顺序）

### 4.1 写入侧（bp_ingest）
| 文件 | 改动 |
|---|---|
| `bp_ingest/db.py:171-191` | `_UPSERT_SQL` 增加 `adjust` 列与 conflict target；`QuoteRow` 增加字段 |
| `bp_ingest/db.py:194-218` | `upsert_quotes` payload 透传 adjust |
| `bp_ingest/db.py:70-108` | `fetch_active_configs` 返回 `adjust`（配置列）与「需要抓取的复权集合」 |
| `bp_ingest/ingest.py` | 抓取循环由「1 资产 1 次」改为「1 资产 × N 口径」；`extra_params.adjust` 由 `bp_index_config.adjust` 派生（股票默认抓 bfq+qfq+hfq） |
| `bp_ingest/sources.py:455,560-562` | 适配器签名已支持 adjust，补 `stock_em`/`stock_tx` 注册 |
| `bp_ingest/cli.py` | `clean` 命令按 (symbol, source, adjust) 面板重建 |

### 4.2 清洗侧（bp_api/quant/cleaning.py）
- 面板键从 `(symbol, source)` 改为 `(symbol, source, adjust)`；
- 汇率折算、交易日历对齐、插值、`ret` 重算逻辑不变；
- `fill_flag` / `fx_rate` 语义不变。

### 4.3 读取侧（bp_api）
| 文件 | 改动 |
|---|---|
| `bp_api/repositories.py:2 处` | 价格面板查询：按每个 portfolio asset 的 `adjust` 过滤（不能全局默认） |
| `bp_api/quant/coverage.py` | coverage 判定键加 adjust |
| `bp_api/cffex.py:6 处` | 期货不涉复权，显式 `adjust='bfq'` 固定过滤，避免误取 |
| `bp_ingest/crypto_corr.py` | 加密恒 `bfq`，显式过滤 |
| `bp_api/repositories_otc.py` | 显式 `bfq` |

> **原则**：所有读取必须**显式**带 adjust 过滤，禁止依赖隐式默认值——否则未来多口径并行时会读到重复行。

### 4.4 前端
| 文件 | 改动 |
|---|---|
| `web/lib/api.ts:270-288` | 资产类型加 `adjust`；组合资产 payload 加 `adjust` |
| `web/lib/asset-form.ts:33-41` | `buildExtraParams` 的 `category==='etf'` 判断改为「etf \|\| stock」；复权选项对股票开放 |
| `web/components/CreateAssetDialog.tsx:205-228` | 股票可选复权；新建时按「三口径」创建 |
| `web/app/admin/assets/page.tsx:547-580,811` | 同上 + 列表徽章按 category 泛化 |
| `web/app/builder/BuilderClient.tsx:958,1143-1151` | 「ETF · 复权」徽章泛化为「{类别} · {复权}」；默认排序把 hfq 优先 |
| 新增 | 组合资产行上的复权选择器（默认后复权） |

### 4.5 测试
- 新增 `bp_api/tests/test_quote_adjust.py`：同 symbol 三口径并存、互不覆盖、clean 面板独立、回测按口径取数。
- 回归：`test_backtest.py`（no-future）、`test_fx_cleaning.py`（折算）、`test_repositories.py`、`test_api_routes.py`、`test_source_aggregation.py`。

---

## 五、三阶段实施（降风险）

| 阶段 | 内容 | 可验证标志 |
|---|---|---|
| P1 加维度 | DDL + 回填 + 写入侧带上 adjust（默认值与存量一致） | 全站行为**零变化**：回测净值与迁移前逐位一致（取 3 个 demo 组合对比） |
| P2 多口径 | ingest 对股票抓三口径；前端开放复权选择 | 同一股票三条序列各自可查；组合切换口径后回测结果合理 |
| P3 消费升级 | 对外 API 暴露 adjust；资产区间/coverage 带口径 | API 契约 + 文档更新 |

**P1 的验收硬指标**：迁移前后对同一批组合跑回测，NAV 序列 `max|Δ| < 1e-12`；否则说明回填口径错了。

---

## 六、回滚

- 迁移只做「加列 + 改约束 + 改生成列」，回滚脚本为反向 DDL（删列/恢复旧 PK/旧 row_hash），数据行不删；
- 若 P1 验收不通过：`adjust` 列加回默认值不影响旧读路径（旧代码忽略该列），可先回滚代码、保留列。

---

## 七、遗留问题（待 Round 3 确认）

1. `bp_index_config` 是否允许同一 `(symbol, source)` 存在多条不同 adjust 的配置行？（影响前端资产列表是否出现重复项）
2. 对外 API 的 `adjust` 缺省值：股票默认 hfq 还是 bfq？（影响分析师习惯）
3. 老 ETF 资产（现有 118 只）在 UI 上是否一律显示「后复权」并可改？

# UI 打磨 + Crypto 数据源 + 非CNY限制 + 索引优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 BTC 数据停更（yfinance→新浪CME期货 fallback 链）、重构 builder 确认变更 diff、限制非 CNY 资产、补数据库索引/row_count、统一全站宽度与现代扁平化打磨。

**Architecture:** 后端沿用 bp_ingest source adapter 注册表 + AGGREGATE_CHAINS ratio re-anchor 降级模式；DB 走编号迁移 40（生产库 Tailscale 100.75.138.35 直连应用）；前端改动集中在 ChangeDiffDialog/BuilderClient/card.tsx/Navbar/CffexClient/globals.css。

**Tech Stack:** FastAPI + psycopg3 + PostgreSQL18/TimescaleDB + akshare/yfinance；Next.js 16 + React 19 + Tailwind v4 (CSS-first) + shadcn 风格组件 + Radix AlertDialog。

## Global Constraints

- **不 commit**：所有 git 操作由用户自己执行；每个任务以「测试/构建通过」为完成检查点，无 commit 步骤。
- 改动直接落主 checkout `D:\balanced-portfolio`（无 worktree）。
- DB 连接：`PGHOST=100.75.138.35 PGPORT=5432 PGDATABASE=postgres PGUSER=postgres`，密码在 `.env` 的 `PGPASSWORD`。**含中文的 SQL 必须写入 utf-8 文件后 `psql -f` 执行**（勿用 -c 内联中文）。
- DDL 纪律：新迁移编号从 **40** 起；同步把变更合并进 `ddl/schema.sql`（基线）；不重跑历史迁移、不改已应用脚本。
- 颜色方案不动：sky 主色、`text-up`/`text-down` 涨跌语义、四象限色、`web/lib/chart-theme.ts` 图表色全部保留。
- 禁止 `window.alert/confirm`；确认框一律 Radix AlertDialog；toast 用 sonner。
- 前端安装依赖必须 `npm install --legacy-peer-deps`。
- 每任务收尾必跑：`python -m pytest bp_api/tests -q`（涉及后端时）+ `cd web && npm run build`（涉及前端时）。
- Python venv：`.venv`（py 3.14）；运行后端命令前先 `.venv\Scripts\activate` 或用 `.venv\Scripts\python.exe`。

---

## Phase A：后端与数据层

### Task 1: DDL 40 迁移 + schema.sql 合并 + 生产库应用

**Files:**
- Create: `ddl/40_currency_rowcount_btc_source.sql`
- Modify: `ddl/schema.sql`（合并同样变更：`bp_index_config` 建表加 `currency` 列、`bp_data_source` 加 `is_addable` 列、`bp_asset_data_status` 加 `row_count` 列、两个新索引、`btc_cme_sina` seed 行、`futures_cffex` 行 `is_addable=FALSE`）
- Read first: `ddl/schema.sql` L35-100（`bp_data_source` / `bp_index_config` 精确列定义）、L890-905（crypto seed 行）

**Interfaces:**
- Produces: `bp_index_config.currency TEXT NOT NULL DEFAULT 'CNY'`；`bp_data_source.is_addable BOOLEAN NOT NULL DEFAULT TRUE`；`bp_asset_data_status.row_count BIGINT`；索引 `idx_bp_portfolio_demo_order`、`idx_cffex_premium_variety_type_date`。后续 Task 4/7 依赖这些列。

- [ ] **Step 1: 写迁移文件**（先读 schema.sql 确认 `bp_data_source` 的 INSERT 列序，seed 行仿照 `gold_comex_em` 那行）

```sql
-- 40: currency 列 + row_count + demo/premium 索引 + btc_cme_sina 降级源 + futures_cffex 不可添加
BEGIN;

ALTER TABLE bp_index_config ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'CNY';
COMMENT ON COLUMN bp_index_config.currency IS
  '资产计价币种。CNY=人民币可直接回测; 非CNY(USD/HKD/JPY等)=外币计价指数, 无外汇数据换算, builder 沉底并弹确认';

ALTER TABLE bp_data_source ADD COLUMN IF NOT EXISTS is_addable BOOLEAN NOT NULL DEFAULT TRUE;
COMMENT ON COLUMN bp_data_source.is_addable IS 'FALSE=不可在 /admin/assets 添加资产(如 futures_cffex 走独立 pipeline)';

ALTER TABLE bp_asset_data_status ADD COLUMN IF NOT EXISTS row_count BIGINT;

-- 非 CNY 标记: 港股指数=HKD, 全球指数默认 USD, 日经系=JPY, crypto/外汇/COMEX=USD
UPDATE bp_index_config SET currency='HKD' WHERE source IN ('hk_index_em','hk_index_sina');
UPDATE bp_index_config SET currency='JPY'
  WHERE source IN ('global_index_em','global_index_sina') AND name LIKE '%日经%';
UPDATE bp_index_config SET currency='USD'
  WHERE source IN ('global_index_em','global_index_sina') AND currency='CNY';
UPDATE bp_index_config SET currency='USD' WHERE source IN ('crypto_yfinance','dxy_em','gold_comex_em');
-- cmdty_main_sina(沪金/沪铜等国内期货主力) 与境内指数/ETF 保持 CNY 默认值

-- futures_cffex 走 bp_ingest/cffex.py 独立 pipeline, 通用 adapter 注册表无此 source, 禁止从 admin 添加
UPDATE bp_data_source SET is_addable=FALSE WHERE code='futures_cffex';

COMMIT;
```

注意：`btc_cme_sina` 的 `INSERT INTO bp_data_source (...)` 必须按 schema.sql 实际列序写（仿 `gold_comex_em` 行：description=`'CME比特币期货(BTC主力)-akshare futures_foreign_hist'`, akshare_func=`'futures_foreign_hist'`, asset_class=`'alternative'`, symbol_hint=`'BTC-USD'`, vendor=`'新浪财经'`, logical_source=`'crypto'`, is_backup=`TRUE`, is_addable=`TRUE`），加 `ON CONFLICT (code) DO NOTHING`。

- [ ] **Step 2: 加索引 + row_count 回填（迁移文件末尾，事务外）**

```sql
CREATE INDEX IF NOT EXISTS idx_bp_portfolio_demo_order
  ON bp_portfolio (display_order, portfolio_id) WHERE is_demo = TRUE;
CREATE INDEX IF NOT EXISTS idx_cffex_premium_variety_type_date
  ON bp_cffex_premium_daily (variety, contract_type, trade_date);

-- row_count 一次性回填(全表 GROUP BY 一遍, 分钟级, 只跑一次)
UPDATE bp_asset_data_status st
SET row_count = sub.c
FROM (SELECT symbol, source, COUNT(*) AS c FROM bp_index_quote_daily GROUP BY symbol, source) sub
WHERE st.symbol = sub.symbol AND st.source = sub.source;

ANALYZE bp_portfolio; ANALYZE bp_cffex_premium_daily;
ANALYZE bp_index_config; ANALYZE bp_asset_data_status; ANALYZE bp_data_source;
```

- [ ] **Step 3: 应用到生产库**

```bash
cd /d/balanced-portfolio
PGPASSWORD=$(grep '^PGPASSWORD=' .env | cut -d= -f2) psql -h 100.75.138.35 -U postgres -d postgres -v ON_ERROR_STOP=1 -f ddl/40_currency_rowcount_btc_source.sql
```
Expected: `BEGIN/ALTER TABLE/UPDATE n/INSERT 0 1/CREATE INDEX/UPDATE n/ANALYZE`，无 ERROR。

- [ ] **Step 4: 验证**

```bash
psql ... -c "\d bp_index_config" | grep currency
psql ... -c "SELECT currency, COUNT(*) FROM bp_index_config GROUP BY currency;"
psql ... -c "SELECT COUNT(*) FROM bp_asset_data_status WHERE row_count IS NULL;"   # 应只剩无行情数据的资产
psql ... -c "EXPLAIN SELECT portfolio_id FROM bp_portfolio WHERE is_demo=TRUE ORDER BY display_order NULLS LAST, portfolio_id LIMIT 1;"
# Expected: Index Scan using idx_bp_portfolio_demo_order
psql ... -c "EXPLAIN SELECT trade_date FROM bp_cffex_premium_daily WHERE variety='IF' AND contract_type='当月' AND trade_date BETWEEN '2025-01-01' AND '2025-06-01' ORDER BY trade_date;"
# Expected: Index Scan/Index Only Scan using idx_cffex_premium_variety_type_date
```

- [ ] **Step 5: 合并进 schema.sql**（同列/同索引/同 seed；中文注释照抄迁移文件）

- [ ] **Step 6: 回归** `python -m pytest bp_api/tests -q` → 全绿（DDL 不应破坏任何测试）。

---

### Task 2: `btc_cme_sina` adapter + fallback 链 + HTTPError 降级触发

**Files:**
- Modify: `bp_ingest/sources.py`（L594-634 区域加 fetch 函数；L693-702 注册表；L718-724 AGGREGATE_CHAINS；L798-827 fetch_with_fallback 异常捕获）
- Test: `bp_api/tests/`（新增或就近扩展 ingest source 测试；若无现成 sources 测试文件则建 `bp_api/tests/test_sources_btc.py`）

**Interfaces:**
- Consumes: 现有 `ak.futures_foreign_hist`、`_rename`、`_finalize`、`STANDARD_COLUMNS`、`SourceAdapter`。
- Produces: `SOURCES["btc_cme_sina"]`；`AGGREGATE_CHAINS["crypto_yfinance"] == ["btc_cme_sina"]`；`fetch_with_fallback` 对 `requests.exceptions.HTTPError`（含 Yahoo 429）也触发降级链。

- [ ] **Step 1: 写失败测试**（mock akshare，不联网）

```python
# bp_api/tests/test_sources_btc.py
from datetime import date
from unittest.mock import patch
import pandas as pd
from bp_ingest import sources


def _fake_btc_raw() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2026-09-01", "2026-09-02", "2026-09-03"],
        "open": [108000.0, 109000.0, 110000.0],
        "high": [109500.0, 110500.0, 111500.0],
        "low": [107500.0, 108500.0, 109500.0],
        "close": [109000.0, 110000.0, 111000.0],
        "volume": [1000, 1100, 1200],
    })


def test_btc_cme_sina_registered_and_normalized():
    adapter = sources.get_adapter("btc_cme_sina")
    assert adapter.akshare_func == "futures_foreign_hist"
    with patch.object(sources.ak, "futures_foreign_hist", return_value=_fake_btc_raw()):
        df = adapter.fetch("BTC-USD", date(2026, 9, 1), date(2026, 9, 3), {})
    assert list(df["trade_date"]) == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert float(df["close"].iloc[-1]) == 111000.0


def test_crypto_yfinance_chain_falls_back_on_http_error():
    import requests
    assert sources.AGGREGATE_CHAINS.get("crypto_yfinance") == ["btc_cme_sina"]
    with patch.object(sources.SOURCES["crypto_yfinance"], "fetch",
                      side_effect=requests.exceptions.HTTPError("429 Too Many Requests")), \
         patch.object(sources.ak, "futures_foreign_hist", return_value=_fake_btc_raw()):
        df = sources.fetch_with_fallback(
            "crypto_yfinance", "BTC-USD", date(2026, 9, 1), date(2026, 9, 3), {},
            anchor_close=222000.0, anchor_date=date(2026, 9, 3),
        )
    # 库中锚点重锚: 期货 close 111000 → 现货口径 222000 (ratio=2)
    assert abs(float(df["close"].iloc[-1]) - 222000.0) < 1e-6
```

注意：`SourceAdapter` 是 frozen dataclass，`patch.object(adapter, "fetch", ...)` 若不可行则改为 patch `sources.SOURCES` 字典项（构造一个 fetch=side_effect 的新 SourceAdapter 替换进 dict，测试后还原）或 patch `_fetch_crypto_yfinance`。执行者任选可行方式，保持断言不变。

- [ ] **Step 2: 跑测试确认失败** `python -m pytest bp_api/tests/test_sources_btc.py -v` → FAIL（KeyError: btc_cme_sina）。

- [ ] **Step 3: 实现**（`bp_ingest/sources.py`）

fetch 函数（放在 `_fetch_gold_comex_em` 之后，注释块说明用途）：

```python
def _fetch_btc_cme_sina(symbol: str, start: date, end: date, extra: dict) -> pd.DataFrame:
    """akshare futures_foreign_hist 拉 CME 比特币期货(BTC 主力)日线。

    yfinance BTC-USD 的境内降级源(prod IP 被 Yahoo 429 时接管)。单资产源: symbol 参数
    忽略, akshare symbol 固定 "BTC"。期货价与现货有基差但收益率高度相关, 经
    AGGREGATE_CHAINS 重叠收盘比值重锚到现货口径后拼接, 对下游清洗/相关性透明。
    """
    raw = ak.futures_foreign_hist(symbol="BTC")
    if raw is None or raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    df = _rename(raw, {"date": "trade_date"})
    return _finalize(df, start, end)
```

注册表（`SOURCES` dict 中 `crypto_yfinance` 之后）：

```python
    "btc_cme_sina": SourceAdapter(
        "btc_cme_sina", "futures_foreign_hist", True, True, False, _fetch_btc_cme_sina
    ),
```

降级链（`AGGREGATE_CHAINS` 加一行，并更新上方注释）：

```python
    "crypto_yfinance": ["btc_cme_sina"],
```

`fetch_with_fallback` 异常触发扩展（L798-806 区域）：

```python
    # curl_cffi 抛自己的 ConnectionError(非 requests 子类), 一并纳入降级触发条件;
    # HTTPError 纳入是为 Yahoo 429(yfinance 抛 requests HTTPError)触发 crypto 降级链。
    _conn_exc = (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout,
                 _requests.exceptions.HTTPError)
```

同时更新 L594-597 注释块：BTC-USD 现在有境内降级源。

- [ ] **Step 4: 跑测试确认通过** `python -m pytest bp_api/tests/test_sources_btc.py bp_api/tests -q` → 全绿。

- [ ] **Step 5: 真实拉数冒烟**（联网，验证新浪端点可用）

```bash
.venv\Scripts\python.exe -c "from datetime import date,timedelta; from bp_ingest.sources import SOURCES; df=SOURCES['btc_cme_sina'].fetch('BTC-USD', date.today()-timedelta(days=90), date.today(), {}); print(len(df), df['trade_date'].min(), df['trade_date'].max(), df['close'].iloc[-1])"
```
Expected: 行数 ~60-90，last date 距今 ≤4 天（CME 期货日线），close 为 5 位数量级美元价。若新浪端点挂了，记录并改用 WebSearch 找替代（如 `ak.crypto_js_spot` 只能快照不行——此时向用户上报）。

---

### Task 3: probe 透传 extra + futures_cffex 前端过滤 + is_addable 透出

**Files:**
- Modify: `bp_api/main.py:661-707`（probe 端点）、`bp_api/repositories.py:1447-1471`（list_data_sources SELECT 加 `is_addable`）
- Modify: `web/lib/api.ts`（DataSource 类型加 `is_addable?: boolean`；`probeAsset` 加可选 `extra` 参数，对应 L878-911 区域）
- Modify: `web/app/admin/assets/page.tsx`（probe 调用带表单 extra；数据源下拉过滤 `is_addable === false`，L42/L257-381 区域）

**Interfaces:**
- Consumes: Task 1 的 `is_addable` 列。
- Produces: `POST /api/admin/assets/{source}/{symbol}/probe` 接受 JSON body `{"extra_params": {...}}`（可选，缺省 `{}`，向后兼容）；前端 `api.probeAsset(source, symbol, extra?)`。

- [ ] **Step 1: 后端 probe 接受 extra**

在 main.py 的 Pydantic 输入模型区（AssetAdminIn 附近）加：

```python
class AssetProbeIn(BaseModel):
    extra_params: dict = Field(default_factory=dict)
```

probe 端点签名与调用改为：

```python
@app.post("/api/admin/assets/{source}/{symbol}/probe")
def probe_admin_asset(source: str, symbol: str, payload: AssetProbeIn | None = None,
                      _: auth.UserContext = Depends(auth.require_asset_editor)) -> dict:
    ...
    extra = dict(payload.extra_params) if payload else {}
    ...
                df = fetch_with_fallback(source, symbol, start, today, extra)
```

- [ ] **Step 2: repositories.list_data_sources 加列**：SELECT 列表加 `is_addable`，返回 dict 加 `"is_addable": bool(row[...])`。

- [ ] **Step 3: 前端**
  - `web/lib/api.ts`：`DataSource` 接口加 `is_addable?: boolean;`；`probeAsset(source: string, symbol: string, extra?: Record<string, unknown>)` → body `JSON.stringify({ extra_params: extra ?? {} })`（保持 method/headers 与现有一致）。
  - `page.tsx`：数据源下拉 options 过滤 `(s) => s.is_addable !== false`；「测试读取」按钮的 probe 调用传入与保存时相同口径的 extra（读现有 save() 里 extra_params 的构造逻辑，抽成 `buildExtraParams()` 复用——ETF 传 `{adjust}`，bond_csi_treasury 传 `{indicator: "财富"}`（若表单有该字段则用表单值），其余传 `{}`）。

- [ ] **Step 4: 后端测试**：在 `bp_api/tests/` 找现有 admin assets probe 测试（grep `probe`），扩展断言 body 带 `extra_params` 时能透传（mock fetch_with_fallback 断言收到的 extra）。跑 `python -m pytest bp_api/tests -q` 全绿。

- [ ] **Step 5: 前端构建** `cd web && npm run build && npm run typecheck` → 通过。

---

### Task 4: row_count 增量维护（COUNT 移出热路径）+ /api/assets 透出 currency

**Files:**
- Modify: `bp_api/repositories.py:1560-1620`（refresh_asset_status）、L240-287（list_assets）、L1474-1518（list_admin_assets）
- Modify: `bp_ingest/ingest.py`（sync 成功路径更新 row_count）
- Read first: refresh_asset_status 全文，确认现有 COUNT/MAX 用法与 bp_asset_data_status 列

**Interfaces:**
- Consumes: Task 1 的 `row_count`、`currency` 列。
- Produces: `refresh_asset_status(conn, symbol, source, *, error=None, probe_ms=None, with_count=False)`——默认**不再跑 COUNT**（保留库中 row_count 旧值）；`with_count=True` 时才 COUNT 并写回。`list_assets`/`list_admin_assets` 返回的每个资产 dict 加 `"currency": str`。

- [ ] **Step 1: refresh_asset_status 加 `with_count: bool = False` 参数**：把 `SELECT COUNT(*) FROM bp_index_quote_daily WHERE symbol/source`（及 clean 表同款）包进 `if with_count:`；无 with_count 时 UPDATE 语句不包含 row_count 列。MAX(trade_date) 查询保留（走索引，廉价）。

- [ ] **Step 2: 调用点分级**：
  - probe / admin 保存 / 单资产 sync（main.py、ingest 回调）→ 默认 `with_count=False`。
  - `POST /api/admin/assets/refresh-status`（刷新状态按钮）与 bp_ingest 每日调度收尾（scheduler.py 的全量 run 之后，或 ingest.run 的 refresh_clean 收尾处）→ `with_count=True`。
  - `bp_ingest/ingest.py`：每个 symbol sync 成功后，若本次有新行写入（fetch df 的 max trade_date > 库中 last_raw_date），对该资产做一次 `with_count=True` 刷新（每天最多一次每资产，代价可接受）。

- [ ] **Step 3: list_assets / list_admin_assets 透出 currency**：SELECT 加 `c.currency`，返回 dict 加 `"currency"` 键。grep 测试中对资产列表断言的地方（conftest 合成资产 seed），必要时补列。

- [ ] **Step 4: 测试**：`python -m pytest bp_api/tests -q` 全绿；若现有测试直接调 refresh_asset_status 断言 row_count，调整为 `with_count=True`。

- [ ] **Step 5: 生产验证**（应用 Task 1 后）：

```bash
psql ... -c "SELECT symbol, source, row_count, last_clean_date FROM bp_asset_data_status ORDER BY row_count DESC NULLS LAST LIMIT 5;"
```
Expected: 有数据的资产 row_count 为正值（回填过）。

---

### Task 5: BTC 历史补缺 + crypto 相关性重算 + 看板验证

**Files:**
- Create: `scripts/backfill_btc_cme.py`（一次性脚本，放 `scripts/` 维护脚本目录，不参与 API 运行）
- Run: `bp_ingest`（clean）、`bp_ingest.crypto_corr.compute_and_store`（或对应 Celery 任务 `bp_api.refresh_calendar` 同款调用方式——读 crypto_corr.py L307 确认函数签名）

**Interfaces:**
- Consumes: Task 2 的 `_fetch_btc_cme_sina` / `fetch_with_fallback`；现有 `bp_ingest clean`、`crypto_corr.compute_and_store_crypto_corr`。
- Produces: `bp_quote_clean` 中 BTC-USD@crypto_yfinance 无近期缺口；3 张 crypto 表重算到最新 effective_td。

- [ ] **Step 1: 现状盘点**

```bash
psql ... -c "SELECT MAX(trade_date), COUNT(*) FROM bp_index_quote_daily WHERE symbol='BTC-USD' AND source='crypto_yfinance';"
psql ... -c "SELECT MAX(trade_date) FROM bp_quote_clean WHERE symbol='BTC-USD';"
psql ... -c "SELECT key, value FROM bp_crypto_meta;"   # effective_td / is_synced 现值
```
记录停更日期。

- [ ] **Step 2: 写补缺脚本** `scripts/backfill_btc_cme.py`：

```python
"""一次性: 用新浪 CME 期货补 BTC-USD 缺口(重锚到库中现货口径), 只补缺失日期, 不覆盖已有行。

用法: .venv\\Scripts\\python.exe scripts/backfill_btc_cme.py [--dry-run]
"""
import argparse, os, sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bp_ingest.sources import get_adapter, _align_fallback_to_base  # noqa: E402
from bp_api import db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    df = get_adapter("btc_cme_sina").fetch("BTC-USD", date(2017, 1, 1), date.today(), {})
    print(f"futures rows={len(df)} range={df['trade_date'].min()}..{df['trade_date'].max()}")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, close FROM bp_index_quote_daily "
                "WHERE symbol='BTC-USD' AND source='crypto_yfinance' ORDER BY trade_date")
            have = cur.fetchall()
        if not have:
            print("库中无现货历史, 无法重锚 —— 中止(需先让 yfinance 拉一次或人工定锚)"); return
        have_dates = {r[0] for r in have}
        anchor_close, anchor_date = float(have[-1][1]), have[-1][0]
        aligned = _align_fallback_to_base(None, df, anchor_close=anchor_close, anchor_date=anchor_date)
        missing = aligned[~aligned["trade_date"].isin(have_dates)]
        print(f"missing dates to insert: {len(missing)} ({missing['trade_date'].min() if len(missing) else '-'}"
              f"..{missing['trade_date'].max() if len(missing) else '-'})")
        if args.dry_run or missing.empty:
            return
        with conn.cursor() as cur:
            for _, r in missing.iterrows():
                cur.execute(
                    """INSERT INTO bp_index_quote_daily
                       (symbol, source, trade_date, open, high, low, close, volume, amount,
                        turnover_rate, pct_change)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL)
                       ON CONFLICT (symbol, source, trade_date) DO NOTHING""",
                    ("BTC-USD", "crypto_yfinance", r["trade_date"],
                     r.get("open"), r.get("high"), r.get("low"), float(r["close"]), r.get("volume")),
                )
        conn.commit()
        print("inserted; 注意: pct_change 为 NULL, 由 bp_ingest clean 基于清洗价重算收益率")
```

注意：INSERT 列必须与 `bp_index_quote_daily` 实际 schema 对齐（先 `\d bp_index_quote_daily` 核对 NOT NULL 列与默认值，按需调整；NaN 值必须先转 None——psycopg 拒 NaN token）。`db.get_conn` 若依赖 `load_settings()`，先读 `bp_api/db.py` 确认本地直连可用的初始化方式（.env 已有 PG* 配置）。

- [ ] **Step 3: 执行**（先 dry-run 看缺口量，再实跑）

```bash
.venv\Scripts\python.exe scripts/backfill_btc_cme.py --dry-run
.venv\Scripts\python.exe scripts/backfill_btc_cme.py
```

- [ ] **Step 4: 重建 clean + 重算相关性**

```bash
.venv\Scripts\python.exe -m bp_ingest clean
# 重算 crypto corr: 读 bp_ingest/crypto_corr.py L307 确认入口签名后直调, 例如:
.venv\Scripts\python.exe -c "from bp_api import db; from bp_ingest.crypto_corr import compute_and_store_crypto_corr; from bp_ingest.config import load_config; \
conn_ctx=db.get_conn(); \
exec('with conn_ctx as conn:\n    compute_and_store_crypto_corr(conn, load_config())'); \
exec('with db.get_conn() as c:\n    c.commit()')"
```
（若入口签名不同——如自带连接管理——按实际签名调用；也可通过 Celery `send_task` 触发。执行者读源码后选最直路径。）

- [ ] **Step 5: 验证**

```bash
psql ... -c "SELECT MAX(trade_date) FROM bp_quote_clean WHERE symbol='BTC-USD';"   # 应到最近交易日(考虑 CME 与 A 股日历差, T-1~T-3)
psql ... -c "SELECT key, value FROM bp_crypto_meta;"                                # effective_td 前进, is_synced=true
curl -s http://127.0.0.1:8000/api/crypto/correlation | head -c 400                  # (若本地 API 起着) 有最新数据
```

- [ ] **Step 6: 端到端 source 验收（用户要求：所有数据源模拟用户操作可添加并拉数）**——起本地 API + web（见 Task 13 Step 1），在 /admin/assets 对每类 source 至少 probe 一个代表资产：`cn_index_em`(000300)、`etf_em`(510300, adjust=hfq)、`bond_csi_treasury`、`cmdty_main_sina`(AU0)、`hk_index_em`(HSI)、`global_index_em`(标普500)、`crypto_yfinance`(BTC-USD)、`dxy_em`、`gold_comex_em`、`btc_cme_sina`（若 addable）。全部返回 ok + rows>0；`futures_cffex` 不再出现在下拉。probe 通过后任选一个执行「增量」sync 验证入库。

---

## Phase B：前端功能修复

### Task 6: 确认变更对话框重构（placement 级 diff + 分组渲染 + 加宽）

**Files:**
- Modify: `web/components/ChangeDiffDialog.tsx`（全文重写渲染部分）
- Modify: `web/app/builder/BuilderClient.tsx`（L239-245 快照、L338-381 diffs useMemo、调用 ChangeDiffDialog 的 props 处；grep 其它调用点一并更新）

**Interfaces:**
- Produces: `AssetDiff` 接口（ChangeDiffDialog 导出）：`{ added: {label,quadrant}[]; removed: {label,quadrant}[]; moved: {label,from,to}[] }`；`ChangeDiffDialog` props 中 `assetSummary: string | null` 替换为 `assetDiff: AssetDiff | null`。

- [ ] **Step 1: BuilderClient 快照改存 quadrant key**（L239-245）：

```tsx
        assets: QUADRANT_ORDER.flatMap((q) =>
          selected[q].map((a) => ({
            key: keyOf(a),          // symbol@source (不变)
            label: a.name || a.symbol,
            quadrant: q,            // 改: 存象限 key(overheat/...), 显示层再转 QUADRANT_SHORT
          }))
        ),
```
（grep `origSnapRef` 与 `.quadrant` 的其它消费点，全部适配。）

- [ ] **Step 2: diffs useMemo 重写资产部分**（替换 L359-375 的 assetSummary 逻辑；参数 rows 逻辑不动——它已经只 push 有变更的行）：

```tsx
    // 资产构成: placement(symbol@source@quadrant) 级对比; 同 symbol 的 移除+新增 配对为「象限调整」
    const cur = QUADRANT_ORDER.flatMap((q) =>
      selected[q].map((a) => ({ sym: keyOf(a), label: a.name || a.symbol, quadrant: q })));
    const pkey = (p: { sym: string; quadrant: string }) => `${p.sym}@${p.quadrant}`;
    const oSet = new Set(o.assets.map((a) => `${a.key}@${a.quadrant}`));
    const cSet = new Set(cur.map(pkey));
    const addedP = cur.filter((p) => !oSet.has(pkey(p)));
    const removedP = o.assets
      .filter((a) => !cSet.has(`${a.key}@${a.quadrant}`))
      .map((a) => ({ sym: a.key, label: a.label, quadrant: a.quadrant }));
    // 同 symbol 配对 → moved; 剩余落 added/removed
    const remBySym = new Map<string, typeof removedP>();
    for (const r of removedP) {
      const arr = remBySym.get(r.sym) ?? [];
      arr.push(r);
      remBySym.set(r.sym, arr);
    }
    const moved: AssetDiff["moved"] = [];
    const added: AssetDiff["added"] = [];
    for (const a of addedP) {
      const bucket = remBySym.get(a.sym);
      if (bucket && bucket.length > 0) {
        const r = bucket.shift()!;
        moved.push({ label: a.label, from: QUADRANT_SHORT[r.quadrant], to: QUADRANT_SHORT[a.quadrant] });
      } else {
        added.push({ label: a.label, quadrant: QUADRANT_SHORT[a.quadrant] });
      }
    }
    const removed = [...remBySym.values()].flat()
      .map((r) => ({ label: r.label, quadrant: QUADRANT_SHORT[r.quadrant] }));
    const assetDiff: AssetDiff | null =
      added.length || removed.length || moved.length ? { added, removed, moved } : null;
```
返回对象改为 `{ rows, assetDiff, hasBacktestChange }`；调用 ChangeDiffDialog 处 props 同步（`assetSummary=` → `assetDiff=`）；「有无变更」判定（底栏按钮/空态）改为 `rows.length > 0 || assetDiff != null`。

- [ ] **Step 3: ChangeDiffDialog 重写**：

```tsx
"use client";

import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface DiffRow {
  label: string;
  before: string;
  after: string;
}

export interface AssetDiff {
  added: { label: string; quadrant: string }[];
  removed: { label: string; quadrant: string }[];
  moved: { label: string; from: string; to: string }[];
}

function AssetGroup({ title, className, children }: {
  title: string; className?: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className={`text-xs font-medium mb-1 ${className ?? ""}`}>{title}</div>
      <ul className="text-sm space-y-0.5">
        {children}
      </ul>
    </div>
  );
}

export function ChangeDiffDialog({
  open, onOpenChange, diffs, assetDiff, canRecompute, busy, onMetaSave, onRecompute,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  diffs: DiffRow[];
  assetDiff: AssetDiff | null;
  canRecompute: boolean;
  busy: boolean;
  onMetaSave: () => void;
  onRecompute: () => void;
}) {
  const hasChange = diffs.length > 0 || assetDiff != null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>确认变更</DialogTitle>
          <DialogDescription>
            以下为本次修改的参数。可仅保存（不重算回测），或保存并重新计算。
          </DialogDescription>
        </DialogHeader>
        {!hasChange ? (
          <p className="text-sm text-muted-foreground py-4">没有检测到参数变更。</p>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto space-y-4">
            {diffs.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[28%]">参数</TableHead>
                    <TableHead className="w-[36%]">变更前</TableHead>
                    <TableHead className="w-[36%]">变更后</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {diffs.map((r) => (
                    <TableRow key={r.label}>
                      <TableCell className="text-sm font-medium">{r.label}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{r.before || "—"}</TableCell>
                      <TableCell className="text-sm">{r.after}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {assetDiff && (
              <div className="border border-border rounded-lg p-4 space-y-3">
                <div className="text-sm font-medium">资产构成变更</div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {assetDiff.added.length > 0 && (
                    <AssetGroup title={`新增 (${assetDiff.added.length})`} className="text-success">
                      {assetDiff.added.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> → {x.quadrant}</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                  {assetDiff.moved.length > 0 && (
                    <AssetGroup title={`象限调整 (${assetDiff.moved.length})`} className="text-warning">
                      {assetDiff.moved.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> （{x.from} → {x.to}）</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                  {assetDiff.removed.length > 0 && (
                    <AssetGroup title={`移除 (${assetDiff.removed.length})`} className="text-destructive">
                      {assetDiff.removed.map((x, i) => (
                        <li key={i} className="text-sm">
                          {x.label}
                          <span className="text-muted-foreground"> （{x.quadrant}）</span>
                        </li>
                      ))}
                    </AssetGroup>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {canRecompute && (
          <p className="text-xs text-warning">
            含回测参数变更：仅保存不会更新回测结果，组合将标记为「待重算」。
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>取消</Button>
          <Button variant="outline" onClick={onMetaSave} disabled={busy || !hasChange}>
            {busy ? "保存中…" : "仅保存"}
          </Button>
          {canRecompute && (
            <Button onClick={onRecompute} disabled={busy}>
              {busy ? "提交中…" : "保存并重算"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: grep 全部调用点** `grep -rn "ChangeDiffDialog\|assetSummary" web/` → 全部更新到新 props。

- [ ] **Step 5: 构建验证** `cd web && npm run build && npm run typecheck` → 通过。

- [ ] **Step 6: 浏览器回归**（起 dev server 后）：编辑 demo 组合副本 → 只改一个资产象限 → 保存 → 对话框只显示该行「象限调整」一条，无参数行；再加一个新资产 → 出现「新增 (1)」；截图确认宽度/滚动正常。

---

### Task 7: 非 CNY 资产沉底 + AlertDialog 确认 + 币种标签

**Files:**
- Modify: `web/lib/api.ts`（Asset 接口 L281-292 加 `currency?: string`）
- Modify: `web/app/builder/BuilderClient.tsx`（AssetPicker：rank L766-773、列表项渲染、onPickMany/勾选路径 L739-958）
- Read first: AssetPicker 全文（确认勾选交互是 checkbox 列表 + 确认按钮，还是即点即加）

**Interfaces:**
- Consumes: Task 4 的 `/api/assets` currency 字段；现有 `components/ui/alert-dialog.tsx`（若无则 `npx shadcn@latest add alert-dialog --legacy-peer-deps` 或从现有 ui 组件风格手写）。
- Produces: 勾选非 CNY 资产需 AlertDialog 二次确认后才生效；非 CNY 资产在 picker 列表排最后并带币种 Badge。

- [ ] **Step 1: api.ts Asset 加 `currency?: string;`**（后端 Task 4 已透出）。

- [ ] **Step 2: rank 加档**（非 CNY 沉底，stale 次之）：

```tsx
  // 排序优先级: 后复权(hfq) ETF 最前; 停更与 前复权(qfq) ETF 沉底; 非 CNY 计价(外币指数)一律排最后。
  const rank = (a: Asset): number => {
    const fx = (a.currency ?? "CNY") !== "CNY" ? 10 : 0;   // 外币计价: 无外汇数据, 回测口径受限
    if (a.logical_source === "etf" && a.adjust === "hfq") return 0 + fx;
    if (a.is_stale) return 2 + fx;
    if (a.logical_source === "etf" && a.adjust === "qfq") return 1 + fx;
    return 1 + fx;
  };
```

- [ ] **Step 3: 列表项币种标签**：非 CNY 资产名旁加 `<Badge variant="outline" className="text-[10px] px-1 py-0 text-muted-foreground">{a.currency}</Badge>`。

- [ ] **Step 4: AlertDialog 确认**：在 AssetPicker 的提交选择处（onPickMany 触发前）拦截：

```tsx
  const [pendingNonCny, setPendingNonCny] = useState<Asset[] | null>(null);  // 待确认的非CNY批次

  const tryPick = (list: Asset[]) => {
    const fx = list.filter((a) => (a.currency ?? "CNY") !== "CNY");
    if (fx.length > 0) { setPendingNonCny(list); return; }   // 弹确认, 确认后 proceedPick(list)
    proceedPick(list);
  };
  const proceedPick = (list: Asset[]) => { onPickMany(list); /* 关闭 picker/清空勾选, 沿用现有逻辑 */ };
```

AlertDialog（放 AssetPicker 返回 JSX 末尾；文案精确）：

```tsx
  <AlertDialog open={pendingNonCny != null} onOpenChange={(v) => { if (!v) setPendingNonCny(null); }}>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>包含外币计价资产</AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div className="space-y-2">
            <p>
              以下资产以<strong>外币计价</strong>（非人民币）：
            </p>
            <ul className="text-sm list-disc pl-4">
              {(pendingNonCny ?? []).filter((a) => (a.currency ?? "CNY") !== "CNY").map((a) => (
                <li key={`${a.symbol}@${a.source}`}>{a.name || a.symbol}（{a.currency}）</li>
              ))}
            </ul>
            <p>
              当前系统没有外汇数据，无法把外币收益换算成人民币。回测将直接使用外币价格收益率，
              <strong>未包含汇率变动</strong>，可能影响回测效果。确定继续添加吗？
            </p>
          </div>
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>取消</AlertDialogCancel>
        <AlertDialogAction onClick={() => { const l = pendingNonCny!; setPendingNonCny(null); proceedPick(l); }}>
          仍要添加
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
```
（import 从 `@/components/ui/alert-dialog`；若组件缺失，按 shadcn 标准模板补 `web/components/ui/alert-dialog.tsx`。）
注意：单个资产点选（X 移除不拦；加入才拦）——若 picker 是即点即加模式，把拦截放在单资产 add 路径，`pendingNonCny` 存单个 Asset 亦可，逻辑同上。

- [ ] **Step 5: 推荐 ETF 面板**（L777-780, 903-946）：海外投资组的 QDII ETF 是 CNY 计价**不受影响**，无需改动；确认该面板不会把外币指数混入（它按 symbol 白名单，无指数）。

- [ ] **Step 6: 构建 + 浏览器回归**：`npm run build && npm run typecheck`；dev server 中打开 /builder → 资产列表最末尾出现 日经225/标普500/纳斯达克/HSI 等带 USD/HKD/JPY 标签 → 勾选其一 → AlertDialog 弹出、文案正确 → 「仍要添加」后进入象限、「取消」不进入；QDII ETF（513500 等）勾选**不弹**确认。

---

### Task 8: card.tsx pt-0 修复 + builder 象限卡片居中

**Files:**
- Modify: `web/components/ui/card.tsx:63,73`
- Modify: 全站所有 `CardHeader` + `CardContent` 组合的调用文件（grep 审计）
- Modify: `web/app/builder/BuilderClient.tsx:451-480`（象限卡片）

**Interfaces:**
- Produces: `CardContent` 基类 `p-5 sm:p-6`（四边等距）；依赖旧 `pt-0` 行为的 header 卡片在调用处显式 `pt-0`。

- [ ] **Step 1: card.tsx**：

```tsx
// CardContent
<div ref={ref} className={cn("p-5 sm:p-6", className)} {...props} />
// CardFooter
<div ref={ref} className={cn("flex items-center p-5 sm:p-6", className)} {...props} />
```
（根因：旧基类 `p-5 sm:p-6 pt-0 sm:pt-0` 中，调用方传的 `p-4` 经 twMerge 只覆盖无断点的 `pt-0`，`sm:pt-0` 保留 → ≥640px 顶部 padding 恒为 0。）

- [ ] **Step 2: 审计**：`grep -rln "CardHeader" web/app web/components` → 对每个文件检查 CardHeader 之后的 CardContent/CardFooter：凡未显式传 padding class 的，加 `pt-0`；凡传了 `p-*` 的（如 `p-4`），改成 `p-4 pt-0`（pt-0 放最后确保 twMerge 生效）。CardFooter 同理（旧基类同样有 pt-0）。

- [ ] **Step 3: builder 象限卡片**（BuilderClient L451-480）：

```tsx
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:min-h-[500px]">
              {QUADRANT_ORDER.map((q) => (
                <Card key={q} className="flex flex-col min-h-[240px]">
                  <CardContent className="p-4 flex-1 flex flex-col">
                    <div className="flex justify-between items-center mb-4">
                      <div className={`text-sm font-medium ${QUADRANT_COLOR[q]}`}>{QUADRANT_LABELS[q]}</div>
                      <Badge variant="secondary">已选 {selected[q].length}</Badge>
                    </div>
                    <div className={`flex flex-wrap gap-2 flex-1 ${selected[q].length === 0 ? "items-center content-center" : "content-start"}`}>
                      {selected[q].map((a) => (
                        <Badge key={keyOf(a)} variant="outline" className="pr-1 bg-card border-border text-foreground">
                          {a.name || a.symbol}
                          <X className="w-3 h-3 ml-1 text-muted-foreground cursor-pointer hover:text-foreground"
                            onClick={() => removeAsset(q, keyOf(a))} />
                        </Badge>
                      ))}
                      {selected[q].length === 0 && (
                        <p className="text-sm text-muted-foreground w-full text-center">该象限为空。</p>
                      )}
                    </div>
                    <AssetPicker ... />
```
（变化：Card 加 `min-h-[240px]`；空态时 badge 容器 `items-center content-center` + 文本 `w-full text-center` → 垂直水平居中。）

- [ ] **Step 4: 构建** `npm run build && npm run typecheck` → 通过。

- [ ] **Step 5: 视觉回归**（dev server + 浏览器截图）：/builder step1 四象限卡片顶部有 16px padding、空象限文本居中；抽查 3-5 个使用 CardHeader 的页面（/dashboard、/otc、/admin）间距无双重放大。

---

## Phase C：UI 一致性

### Task 9: 全站宽度统一 1440 + navbar 禁止换行

**Files:**
- Modify: `web/components/Navbar.tsx:70`、`web/app/layout.tsx:102`（footer）、`web/app/cffex/CffexClient.tsx:420,437`、`web/app/crypto/CryptoClient.tsx:335,373`、`web/app/otc-derivatives-pricing/OtcPricingClient.tsx:821`、`web/app/admin/assets/page.tsx:249`、`web/app/admin/users/page.tsx:161`
- Modify: `docs/design-system.md` §3 容器规范
- 不动：dashboard `max-w-[1440px]`（已是目标值）、builder `max-w-4xl`（表单窄栏是刻意设计）、首页 hero `max-w-5xl`（用户确认保留）

**Interfaces:**
- Produces: 全站主容器统一 `max-w-[1440px]`；桌面 nav 链接 `whitespace-nowrap shrink-0` 永不换行。

- [ ] **Step 1:** 上述 7 处 `max-w-7xl` → `max-w-[1440px]`（保留各自 px-* 与 container/mx-auto 结构）。首页 `max-w-6xl` 的 section 容器 → `max-w-[1440px]`（hero 5xl / cta 4xl 保留）。

- [ ] **Step 2: Navbar**：
  - 容器（L70）`max-w-7xl` → `max-w-[1440px]`。
  - 桌面 nav（L107）：`hidden md:flex items-center gap-1 text-sm font-medium ml-4` → 加 `whitespace-nowrap shrink-0 min-w-0 overflow-x-auto`，每个链接 `<a>`/`<Link>` class 加 `whitespace-nowrap shrink-0 px-2.5`（原 px 值按现有保留，只追加 nowrap/shrink）。
  - 左品牌组已有 `min-w-0`，右集群已有 `shrink-0`——中间 nav 在 1024-1280px 挤压时允许自身横向滚动而非换行。
- [ ] **Step 3:** `docs/design-system.md` §3：容器规范表更新为「全站主容器 max-w-[1440px]；builder 表单 max-w-4xl；首页 hero max-w-5xl」。
- [ ] **Step 4:** 构建 + 1280/1440/1920 三宽度截图 navbar：菜单单行不换行、与 dashboard 内容对齐。

---

### Task 10: /cffex 移动端适配 + 涨跌幅左移 1px

**Files:**
- Modify: `web/app/cffex/CffexClient.tsx`（Section 1 卡片 L458-475；Section 4 分位表 L649-765）

**Interfaces:** 无跨任务接口；纯样式。

- [ ] **Step 1: TabsList 防折行**（L657 附近）：`className="w-full grid grid-cols-3 sm:grid-cols-5"` → `className="w-full grid grid-cols-5 gap-1"`，TabsTrigger `className="text-[11px] sm:text-xs px-1.5 sm:px-3 whitespace-nowrap"`（375px 下 5 列各 ~70px，「近3年」不折行）。

- [ ] **Step 2: 分位表移动适配**（L671-744）：
  - 该表所有 `TableHead`/`TableCell` 追加 `p-2 sm:p-4 whitespace-nowrap`（twMerge 覆盖基类 p-4 的移动端值）。
  - 品种列（第一列 head+cell）追加 `sticky left-0 bg-card z-10`。
  - 当前分位值的迷你条 `<span className="w-12 h-2 ...">` → `className="hidden sm:inline-block w-12 h-2 rounded-full bg-muted/30 overflow-hidden align-middle"`（手机只留百分比数字）。
  - 断点保持 `hidden md:table-cell` / `hidden lg:table-cell`（p-2 后平板 9 列 ≈ 9×76px < 768px 视口宽，横滚消除；实测若仍溢出则把 10%/90% 分位挪到 lg 档）。

- [ ] **Step 3: 涨跌幅左移 1px（仅手机端）**（L458-475 Section 1 卡片）：涨跌幅 div `pb-0.5` → `pb-0.5 max-sm:mr-px`（justify-between 右贴边元素加 1px 右边距 = 视觉上左移 1px，仅 <640px 生效）。

- [ ] **Step 4:** 构建 + chrome-devtools 375×812 / 768×1024 / 1440 三视口截图：Tabs 单行 5 列、表格无意外整页横滚（卡片内横滚可接受但品种列 sticky）、涨跌幅位置对比。

---

### Task 11: OTC 标题「场外衍生品定价 · Experiment」

**Files:**
- Modify: `web/app/otc-derivatives-pricing/page.tsx:6,11`、`web/app/otc-derivatives-pricing/OtcPricingClient.tsx:827`、`web/components/Navbar.tsx:24`、`web/app/page.tsx:66`
- 不动: `web/content/methodology.mdx`（描述性文字非标题）

- [ ] **Step 1:** metadata `title: "场外衍生品定价 · Experiment — 雪球/凤凰/气囊/障碍"`；OG `title: "场外衍生品定价 · Experiment | Balanced Portfolio"`；H1 文本 `场外衍生品定价 · Experiment`（`· Experiment` 部分可包 `<span className="text-muted-foreground font-normal">· Experiment</span>` 弱化——保持 H1 主体突出）；Navbar label 与首页 CTA 用全角间隔号同款文本 `场外衍生品定价 · Experiment`。
- [ ] **Step 2:** `grep -rn "场外衍生品定价" web/` 确认无遗漏（mdx 除外）；构建 + typecheck；截图 navbar（1440 宽单行不挤）。

---

### Task 12: 全站现代扁平 token 打磨（OpenAI/Next.js 风格）

**Files:**
- Modify: `web/app/globals.css`（token）、`web/app/layout.tsx`（Geist 字体）、`web/components/ui/card.tsx`（阴影）、`web/components/ui/button.tsx`（若含 shadow）
- Modify: `docs/design-system.md`（新增「扁平化规范」小节）

**Interfaces:**
- Consumes: Task 8/9 完成后的组件基类。
- Produces: 更新的 token：`--radius 0.625rem`、卡片平面化（border 为主、无投影）、Geist 西文字体栈。颜色 token 一律不动。

- [ ] **Step 1: Geist 字体**（layout.tsx）：

```tsx
import { Geist, Geist_Mono } from "next/font/google";
const geistSans = Geist({ subsets: ["latin"], variable: "--font-geist-sans", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
// <html className={`${geistSans.variable} ${geistMono.variable}`}>  (与现有 dark class 共存)
```
globals.css `@theme inline` 中：`--font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;`、`--font-mono: var(--font-geist-mono), ui-monospace, "SFMono-Regular", monospace;`（body 已用 font-sans，数字区已用 font-mono，自动生效）。注意：若 Next 16 的 next/font/google 无 Geist（版本差异），退回 `next/font/local` 或跳过字体项并记录。

- [ ] **Step 2: 扁平化 token**：
  - `--radius: 0.75rem` → `0.625rem`（10px；派生 sm/md/lg/xl 自动跟随）。
  - Card（card.tsx L12）：`shadow-sm` → 去掉（`rounded-xl border border-border bg-card text-card-foreground`），靠 border 分隔 = flat。
  - 弹层保留层级阴影：Dialog/AlertDialog/Popover/DropdownMenu/Sheet 内容的 `shadow-lg` 不动（overlay 需要 elevation，OpenAI 亦如此）。
  - button.tsx：若 default/outline variant 带 `shadow-sm`/`shadow`，去掉（grep 确认）。
  - globals.css base 层标题微调：h1/h2 加 `letter-spacing: -0.02em`（OpenAI/Next 标题更紧）；若 base 层已有 tracking 定义则改值不重复加。

- [ ] **Step 3: 全站 shadow 审计**：`grep -rn "shadow-" web/app web/components --include=*.tsx | grep -v ui/` → 业务组件里的 `shadow-md/lg/xl`（非弹层）逐个评估：卡片类去掉或降为 border；确实需要悬浮感的（BackToTop 按钮、sticky 工具条）保留。

- [ ] **Step 4: design-system.md** 增补「扁平化规范」：卡片无投影靠 border、弹层保留 shadow-lg、radius 0.625rem、Geist 西文栈、标题 letter-spacing -0.02em；并注明颜色方案不变。

- [ ] **Step 5:** 构建 + typecheck + 三视口 × light/dark 截图主要页面（首页/dashboard/builder/cffex/crypto/otc/admin）对比打磨前后，确认无对比度/可读性回归。

---

## Phase D：终验

### Task 13: 全链路验收

- [ ] **Step 1: 起本地服务**

```bash
# 后端 (inline 模式, 无需 Redis)
BP_TASK_MODE=inline .venv\Scripts\uvicorn.exe bp_api.main:app --host 127.0.0.1 --port 8000 &
# 前端
cd web && npm run dev &
```
登录凭据：`.env` 的 `BP_ADMIN_EMAIL`；密码若 `BP_ADMIN_INITIAL_PASSWORD` 不在 .env 中且已有管理员账号，向用户索要测试密码（勿重置生产账号）。

- [ ] **Step 2: 后端/前端全量检查**

```bash
python -m pytest bp_api/tests -q          # 全绿 (≥139+新增)
cd web && npm run build && npm run typecheck
```

- [ ] **Step 3: 浏览器模拟用户 E2E**（chrome-devtools 或 playwright MCP）：
  1. 登录 → navbar 1440 宽单行不换行、含「资产管理/用户管理/场外衍生品定价 · Experiment」。
  2. /admin/assets：数据源下拉无 futures_cffex；对 Task 5 Step 6 清单逐源 probe（全部 ok+rows>0）；任选一资产「增量」sync 成功、状态行 row_count/last_clean_date 更新。
  3. /builder：外币指数沉底带币种标签；勾选日经225指数 → AlertDialog → 确认后入象限；四象限卡片顶部 padding 正常、空态居中；编辑已有组合改资产 → 确认变更对话框只列变更行 + 分组资产表（新增/象限调整/移除三组、无重复爆炸输出）、对话框宽度 3xl 正常渲染。
  4. /crypto：BTC 价格与 effective_td 新鲜（对比 Task 5 验证值）、is_synced 徽章正确。
  5. /cffex：375 宽 Tabs 5 列单行、分位表品种列 sticky、无整页横滚、卡片涨跌幅较改前左移 1px；1440 宽无回归。
  6. /otc-derivatives-pricing：H1「场外衍生品定价 · Experiment」、页面功能正常。
  7. 抽查扁平化：卡片无投影有 border、圆角 10px、Geist 西文生效、明暗主题都正常。
- [ ] **Step 4: 生产 DB 终检**：EXPLAIN 两新索引被使用；`bp_crypto_meta` is_synced=true；遗留物清理（backfill 脚本保留在 scripts/ 属维护脚本，不入 git 由用户决定）。
- [ ] **Step 5: 汇报**：变更文件清单 + DDL 40 已应用生产库的确认 + 截图证据 + 未尽事项（如需重启生产 bp-worker/bp-api 使 .env/代码生效的提醒——按惯例 .env 变更需重启 worker）。

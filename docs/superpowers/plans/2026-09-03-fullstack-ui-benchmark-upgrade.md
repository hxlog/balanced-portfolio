# 全站 UI 现代化 + 基准扩展 + 编辑流程升级 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 10 项产品需求 + 内部基准口径修复 + 死配置清理 + 全站设计系统重构与响应式审计，最终本地全量重算 13 个组合并验证前端访问无误（上生产前最后开发）。

**Architecture:** 后端 FastAPI（psycopg3 显式事务）先行：迁移 39、基准注册表、参数快照/免重算保存、限额语义、强制重算端点；前端 Next.js 16 + Tailwind v4 跟进：builder/dashboard/admin 功能、sky 主色 token 体系、图表主题收敛、全站排版间距响应式整改；最后本地数据重算 + chrome-devtools 三视口明暗审计闭环。

**Tech Stack:** Python 3.11+（本地 3.14）/ FastAPI / psycopg3 / PostgreSQL 18 + TimescaleDB / Next.js 16 (Turbopack) / React 19 / Tailwind CSS v4 (CSS-first) / Radix UI / TanStack Query / ECharts / sonner / chrome-devtools MCP。

## Global Constraints

- **禁止 git commit/push**——所有版本操作由用户本人执行；每个任务以「测试/构建通过」为检查点。
- 数据库：`PGHOST=100.75.138.35 PGPORT=5432 PGDATABASE=postgres PGUSER=postgres`，密码取 `D:\balanced-portfolio\.env` 的 `PGPASSWORD`。执行含中文 SQL 必须 `psql -f` UTF-8 文件。
- 提交前必跑：`python -m pytest bp_api/tests -q` 与 `cd web && npm run build`（CI 同口径）。本地后端用 `.venv`（py 3.14）。
- psycopg 约定：`with db.get_conn() as conn:` 取连接，**显式 `conn.commit()`**；所有 `Json()` 实参走 `_json_safe`；权重/小数 `_round`。
- Tailwind v4 CSS-first：配置全部在 `web/app/globals.css`（`@theme inline`），无 tailwind.config；`cn()`=tailwind-merge，**跨 variant 不去重**（传 `sm:max-w-*` 才能覆盖基座 `sm:max-w-lg`）。
- 涨跌色最终口径：**绿涨红跌**；`text-up`/`text-down` 仅限方向性涨跌，非方向语义用 success/warning/destructive。
- 文案中文；百分比显示规则：费率类 ×100 最多 2 位小数去尾零（如 `0.05%`），偏离带 2 位小数（如 `7%`）。
- 不新建文档目录之外的无关文件；不动 `vendor/` 等 gitignored 参考目录。
- 规格文件：`docs/superpowers/specs/2026-09-03-fullstack-ui-benchmark-upgrade-design.md`（冲突时以规格为准）。

---

## Phase P0：基线

### Task 1: 基线验证

**Files:** 无（验证环境）

- [ ] **Step 1: 后端测试基线**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全部通过（记录用例数，后续对比）。

- [ ] **Step 2: 前端构建基线**

```bash
cd D:/balanced-portfolio/web && npm run build
```
Expected: 构建成功。

- [ ] **Step 3: 确认开发服务器可启动**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m uvicorn bp_api.main:app --host 127.0.0.1 --port 8000
# 另开: cd web && npm run dev
```
Expected: 8000 返回 `/api/...` 正常；3000 页面可访问。验证后停止，后续任务按需启动。

---

## Phase P1：后端

### Task 2: 迁移 39 + schema.sql 基线合并

**Files:**
- Create: `ddl/39_benchmarks_edit_flow.sql`
- Modify: `ddl/schema.sql`（合并 34~39 净变化）

**Interfaces:**
- Produces: `bp_user.portfolio_limit` 可空（NULL=无限）；`bp_portfolio.last_run_params` JSONB（由未使用的 `params` 列改名）；全新环境建库基线。

- [ ] **Step 1: 复核 `params` 列存在性**

```bash
psql "host=100.75.138.35 port=5432 dbname=postgres user=postgres" -c "\d bp_portfolio" | grep -E "params|last_run"
```
Expected: 存在 `params | jsonb` 列（探索报告确认）。若不存在，把下面 SQL 中的 `RENAME COLUMN` 换成 `ADD COLUMN last_run_params jsonb`。

- [ ] **Step 2: 写迁移文件 `ddl/39_benchmarks_edit_flow.sql`**

```sql
-- 39: 编辑免重算流程(参数快照) + 组合上限"无限"语义
-- 依赖: 34-38 已应用

-- 1) 组合上限: NULL = 无限 (存量行均有显式值, 不受影响)
ALTER TABLE bp_user ALTER COLUMN portfolio_limit DROP NOT NULL;

-- 2) 复用未使用的 params 列作为"最后一次回测参数快照"
ALTER TABLE bp_portfolio RENAME COLUMN params TO last_run_params;

-- 3) 回填: status=done 的组合, 当前参数即最后一次回测参数 (历史上 PUT 必重算)
UPDATE bp_portfolio p
SET last_run_params = jsonb_build_object(
    'method', p.method,
    'ratio', p.ratio,
    'lookback_days', p.lookback_days,
    'start_date', to_jsonb(p.start_date),
    'benchmark_key', p.benchmark_key,
    'max_weight', round(p.max_weight::numeric, 4),
    'rebalance_band', round(p.rebalance_band::numeric, 4),
    'risk_free_rate', round(p.risk_free_rate::numeric, 4),
    'fee_rate', round(p.fee_rate::numeric, 4),
    'slippage_rate', round(p.slippage_rate::numeric, 4),
    'stamp_duty_rate', round(p.stamp_duty_rate::numeric, 4),
    'assets', (
      SELECT coalesce(jsonb_agg(jsonb_build_array(a.symbol, a.source, a.quadrant)
                                ORDER BY a.symbol, a.source, a.quadrant), '[]'::jsonb)
      FROM bp_portfolio_asset a WHERE a.portfolio_id = p.portfolio_id)
)
WHERE p.status = 'done';
```

- [ ] **Step 3: 本地应用迁移**

```bash
cd D:/balanced-portfolio
PGPASSWORD=$(grep -E '^PGPASSWORD=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//') \
psql -h 100.75.138.35 -U postgres -d postgres -f ddl/39_benchmarks_edit_flow.sql
```
Expected: `ALTER TABLE` ×2 + `UPDATE 13`（done 组合数）。

- [ ] **Step 4: 验证**

```bash
psql ... -c "SELECT count(*) FILTER (WHERE last_run_params IS NOT NULL) AS filled, count(*) FROM bp_portfolio;"
psql ... -c "SELECT email, portfolio_limit FROM bp_user LIMIT 5;"
```
Expected: filled=13；portfolio_limit 均可查（含具体数值）。

- [ ] **Step 5: schema.sql 基线合并**

逐条对照 `ddl/34_*.sql`~`38_*.sql` 与 `39`，把缺失部分合并进 `ddl/schema.sql`（已知缺口：`bp_portfolio.display_order`(36)、`bp_data_source.logical_source/is_backup`(37)、`bp_user.can_manage_assets`(35)、34 的数据源行、38 的推荐 ETF seed、39 的两处结构变化）。原则：
- 已有内容不重复插入（合并前 `grep` 确认）；
- `bp_user.portfolio_limit` 定义改为不带 `NOT NULL`；
- `bp_portfolio` 定义中 `params jsonb` 改写为 `last_run_params jsonb`；
- 文件头注释保持「= 旧编号迁移 01-32」说明，并追加一行「含 34-39 合并」。
验证：`grep -n "last_run_params\|display_order\|logical_source\|can_manage_assets" ddl/schema.sql` 均有命中。

---

### Task 3: 基准注册表 + 多腿合成（含 legs[0] 口径修复）

**Files:**
- Modify: `bp_api/repositories.py`（`BENCHMARKS` ~L134-148、`_compute` ~L613-618、新增两个函数）
- Test: `bp_api/tests/test_benchmarks.py`

**Interfaces:**
- Produces: `_compose_benchmark_series(legs, loader) -> pd.Series`（纯函数，nav 序列起点 1.0；任一腿空 → 空序列）；`BENCHMARKS` 新增 `sp500_etf` / `ndx100_etf` / `n225_etf`；`_compute` 的内部基准改为合成序列。

- [ ] **Step 1: 写失败测试 `bp_api/tests/test_benchmarks.py`**

```python
"""基准注册表与多腿合成测试(不依赖真实 PostgreSQL)。"""
from datetime import date

import pandas as pd

from bp_api.repositories import BENCHMARKS, _compose_benchmark_series


def test_registry_contains_etf_benchmarks():
    for key, sym, name in [
        ("sp500_etf", "513500", "标普500ETF"),
        ("ndx100_etf", "513100", "纳斯达克100ETF"),
        ("n225_etf", "513520", "日经225ETF"),
    ]:
        spec = BENCHMARKS[key]
        assert spec["name"] == name
        assert spec["kind"] == "total_return"
        assert spec["legs"] == [(1.0, sym, "etf_em")]
        assert spec["note"]


def test_compose_two_leg_daily_rebalance():
    idx = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    a = pd.Series([100.0, 110.0, 121.0], index=idx)   # +10%, +10%
    b = pd.Series([100.0, 100.0, 90.0], index=idx)    # 0%, -10%
    table = {("A", "s"): a, ("B", "s"): b}
    out = _compose_benchmark_series(
        [(0.6, "A", "s"), (0.4, "B", "s")], lambda sym, src: table[(sym, src)])
    assert out.iloc[0] == 1.0
    assert abs(out.iloc[1] - 1.06) < 1e-12              # 0.6*10% + 0.4*0%
    assert abs(out.iloc[2] - 1.06 * 1.02) < 1e-12       # 0.6*10% + 0.4*(-10%)


def test_compose_single_leg_equals_normalized_close():
    idx = [date(2024, 1, 2), date(2024, 1, 3)]
    s = pd.Series([200.0, 210.0], index=idx)
    out = _compose_benchmark_series([(1.0, "X", "s")], lambda sym, src: s)
    assert abs(out.iloc[1] - 1.05) < 1e-12


def test_compose_empty_leg_returns_empty():
    idx = [date(2024, 1, 2)]
    out = _compose_benchmark_series(
        [(0.5, "A", "s"), (0.5, "B", "s")],
        lambda sym, src: pd.Series([1.0], index=idx) if sym == "A" else pd.Series(dtype=float))
    assert out.empty
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/Scripts/python -m pytest bp_api/tests/test_benchmarks.py -q
```
Expected: ImportError / AttributeError（`_compose_benchmark_series` 不存在、注册表缺 3 key）。

- [ ] **Step 3: 实现**

`bp_api/repositories.py`，在 `BENCHMARKS` dict 的 `bond6040` 条目后追加：

```python
    "sp500_etf": {
        "name": "标普500ETF", "kind": "total_return",
        "legs": [(1.0, "513500", "etf_em")],
        "note": "人民币计价 QDII（博时513500），后复权含分红拆分，可与组合人民币收益直接比较；含汇率波动与场内折溢价噪声。",
    },
    "ndx100_etf": {
        "name": "纳斯达克100ETF", "kind": "total_return",
        "legs": [(1.0, "513100", "etf_em")],
        "note": "人民币计价 QDII（国泰513100，跟踪纳斯达克100），后复权；含汇率波动与场内折溢价噪声。",
    },
    "n225_etf": {
        "name": "日经225ETF", "kind": "total_return",
        "legs": [(1.0, "513520", "etf_em")],
        "note": "人民币计价 QDII（华夏513520），后复权；2019-06-25 上市，早于该日的回测不显示此基准；含汇率波动与场内折溢价噪声。",
    },
```

同文件新增（放在 `_load_series` 附近）：

```python
def _compose_benchmark_series(
    legs: list[tuple[float, str, str]],
    loader,  # callable(symbol, source) -> pd.Series(close)
) -> pd.Series:
    """多腿按日再平衡合成基准净值(起点=1.0)。任一腿无数据返回空序列。"""
    series: list[tuple[float, pd.Series]] = []
    for w, sym, src in legs:
        s = loader(sym, src)
        if s.empty:
            return pd.Series(dtype=float)
        series.append((w, s))
    idx = series[0][1].index
    for _, s in series[1:]:
        idx = idx.intersection(s.index)
    total = pd.Series(0.0, index=idx)
    for w, s in series:
        total = total.add(s.reindex(idx).pct_change().fillna(0.0) * w, fill_value=0.0)
    total.iloc[0] = 0.0
    return (1.0 + total).cumprod()
```

`_compute`（~L613-618）替换：

```python
    # 回测内部基准 = 注册表全腿合成(多腿按日再平衡), 与展示/归因口径一致
    bkey = _resolve_benchmark_key(pdef.benchmark_key)
    bench = _compose_benchmark_series(
        BENCHMARKS[bkey]["legs"], lambda sym, src: _load_series(conn, sym, src))
    if bench.empty:
        raise ValueError(f"配置基准 {BENCHMARKS[bkey]['name']} 无清洗数据")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest bp_api/tests/test_benchmarks.py bp_api/tests -q
```
Expected: 全绿（注意既有回测测试不受单腿基准影响）。

---

### Task 4: 参数快照与 params_stale

**Files:**
- Modify: `bp_api/repositories.py`（`_read_def`、`run_and_save` ~L567-573、`get_portfolio_dict`、`list_portfolios`、新增函数）
- Test: `bp_api/tests/test_edit_flow.py`

**Interfaces:**
- Produces: `canonical_params(pdef) -> dict`、`is_params_stale(current: dict, snapshot) -> bool`、`read_def(conn, pid)`（`_read_def` 公共别名）；`get_portfolio_dict`/`list_portfolios` 输出新增 `params_stale: bool`。

- [ ] **Step 1: 写失败测试 `bp_api/tests/test_edit_flow.py`**

```python
"""编辑免重算流程测试(不依赖真实 PostgreSQL)。"""
from datetime import date
from types import SimpleNamespace

from bp_api.repositories import canonical_params, is_params_stale


def _pdef(**over):
    base = dict(
        method="quadrant_inner_sharpe_outer_rp", ratio="sharpe", lookback_days=156,
        start_date=date(2018, 1, 1), benchmark_key="bond6040",
        max_weight=0.3333333, rebalance_band=0.07,  # 0.07 -> round4 0.07
        risk_free_rate=0.02, fee_rate=0.00015, slippage_rate=0.00015,
        stamp_duty_rate=0.0005,
        assets=[{"symbol": "510300", "source": "etf_em", "quadrant": "recovery",
                 "display_name": "沪深300ETF"}],
        last_run_params=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_canonical_params_rounds_and_sorts():
    p = _pdef(assets=[
        {"symbol": "B", "source": "s", "quadrant": "recovery", "display_name": ""},
        {"symbol": "A", "source": "s", "quadrant": "overheat", "display_name": ""},
    ])
    c = canonical_params(p)
    assert c["max_weight"] == 0.3333
    assert c["start_date"] == "2018-01-01"
    assert c["assets"] == [["A", "s", "overheat"], ["B", "s", "recovery"]]


def test_stale_when_snapshot_missing():
    assert is_params_stale(canonical_params(_pdef()), None) is True


def test_not_stale_when_equal():
    p = _pdef()
    snap = canonical_params(p)
    assert is_params_stale(canonical_params(p), snap) is False


def test_stale_after_band_change():
    p = _pdef()
    snap = canonical_params(p)
    p2 = _pdef(rebalance_band=0.06)
    assert is_params_stale(canonical_params(p2), snap) is True
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/Scripts/python -m pytest bp_api/tests/test_edit_flow.py -q
```
Expected: ImportError（`canonical_params` 不存在）。

- [ ] **Step 3: 实现**

`bp_api/repositories.py` 新增（`canonical_params` 放在 `asset_key` 附近）：

```python
def _r4(x):
    return None if x is None else round(float(x), 4)


def canonical_params(pdef) -> dict:
    """规范化回测参数快照, 用于对比 last_run_params 判定 stale。"""
    return {
        "method": pdef.method,
        "ratio": pdef.ratio,
        "lookback_days": int(pdef.lookback_days) if pdef.lookback_days is not None else None,
        "start_date": pdef.start_date.isoformat() if pdef.start_date else None,
        "benchmark_key": _resolve_benchmark_key(pdef.benchmark_key),
        "max_weight": _r4(pdef.max_weight),
        "rebalance_band": _r4(pdef.rebalance_band),
        "risk_free_rate": _r4(pdef.risk_free_rate),
        "fee_rate": _r4(pdef.fee_rate),
        "slippage_rate": _r4(pdef.slippage_rate),
        "stamp_duty_rate": _r4(pdef.stamp_duty_rate),
        "assets": sorted([a["symbol"], a["source"], a["quadrant"]] for a in pdef.assets),
    }


def is_params_stale(current: dict, snapshot) -> bool:
    """snapshot 为 None/空(从未回测或历史数据)视为 stale。"""
    if not snapshot:
        return True
    return current != snapshot
```

`PortfolioDef` dataclass 增加字段 `last_run_params`（默认 None），`_read_def` 的 SELECT 增加 `last_run_params` 列并赋值；新增公共别名：

```python
def read_def(conn, pid: int) -> PortfolioDef:
    return _read_def(conn, pid)
```

`run_and_save` 成功落库的 UPDATE（~L567-573）改为同时写快照：

```python
        cur.execute(
            "UPDATE bp_portfolio SET status='done', error=NULL, effective_start_date=%s, "
            "result_version=result_version+1, result_updated_at=now(), data_as_of_date=%s, "
            "last_run_params=%s "
            "WHERE portfolio_id=%s",
            (eff, dates[-1] if dates else eff,
             Json(_json_safe(canonical_params(pdef))), pid),
        )
```

`get_portfolio_dict` 返回 dict 增加：`"params_stale": is_params_stale(canonical_params(pdef), pdef.last_run_params)`（该函数已有 pdef，直接引用）。

`list_portfolios`：先读该函数实现——它的行查询需要追加 `last_run_params` 与计算所需列（method/ratio/lookback_days/start_date/benchmark_key/max_weight/rebalance_band/risk_free_rate/fee_rate/slippage_rate/stamp_duty_rate 以及资产的聚合子查询 `（同迁移 39 回填的 jsonb_agg 子查询）`），然后每行输出 `"params_stale": is_params_stale(current_canonical, snapshot)`。构造 current_canonical 时复用与 `canonical_params` 完全一致的键集（可提取一个 `_canonical_from_row(row_dict)`，或把行组装成与 pdef 同字段的 dict 后调用 `canonical_params`——选后者更 DRY）。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest bp_api/tests/test_edit_flow.py bp_api/tests -q
```
Expected: 全绿。

---

### Task 5: PATCH /meta 扩展为免重算全字段保存

**Files:**
- Modify: `bp_api/schemas.py`（`PortfolioPayloadBase` 数值字段 round4 校验）、`bp_api/repositories.py`（新增 `diff_payload`、`update_portfolio_def_only`、`is_portfolio_stale`）、`bp_api/main.py`（PATCH handler 重写 ~L292-317）
- Test: `bp_api/tests/test_edit_flow.py`（追加）、`bp_api/tests/test_api_routes.py`（追加）

**Interfaces:**
- Consumes: Task 4 的 `read_def` / `canonical_params` / `_r4`。
- Produces: `PATCH /api/portfolios/{id}/meta` 接受 `UpdatePortfolioIn` 全量；仅 name/description 时任何状态可改；含回测字段且组合 running → 409；返回 `{portfolio_id, params_stale}`。

- [ ] **Step 1: schemas 数值取整（先写测试）**

追加到 `bp_api/tests/test_edit_flow.py`：

```python
def test_payload_numeric_round4():
    from bp_api.schemas import UpdatePortfolioIn
    p = UpdatePortfolioIn(
        name="x", assets=[{"symbol": "A", "source": "s", "quadrant": "recovery"}],
        rebalance_band=0.07000000000000001, max_weight=0.33333333,
        fee_rate=0.00015000000001, slippage_rate=0.00015, stamp_duty_rate=0.0005,
        risk_free_rate=0.02,
    )
    assert p.rebalance_band == 0.07
    assert p.max_weight == 0.3333
    assert p.fee_rate == 0.0002 or p.fee_rate == 0.00015  # round(0.00015000000001,4)=0.0002
```

运行确认失败（当前无取整校验，0.07000000000000001 原样保留）。

实现：`bp_api/schemas.py` 的 `PortfolioPayloadBase` 增加：

```python
    @field_validator("max_weight", "rebalance_band", "risk_free_rate",
                     "fee_rate", "slippage_rate", "stamp_duty_rate")
    @classmethod
    def _round4(cls, v):
        return None if v is None else round(float(v), 4)
```

（确认文件已 `from pydantic import field_validator`，否则补 import；risk_free_rate 若为必填则保持必填语义不变，只做取整。）

- [ ] **Step 2: repositories 新增 diff/更新函数（先写测试）**

追加测试：

```python
def test_diff_payload_detects_band_and_name():
    from bp_api.repositories import diff_payload
    p = _pdef()
    snap_like = SimpleNamespace(**{**_pdef().__dict__})
    # 模拟 payload: 仅 band 与 name 变化
    payload = SimpleNamespace(
        name="新名字", description=p.description if hasattr(p, "description") else "",
        method=p.method, ratio=p.ratio, lookback_days=p.lookback_days,
        start_date=p.start_date, benchmark_key=p.benchmark_key,
        max_weight=p.max_weight, rebalance_band=0.06, risk_free_rate=p.risk_free_rate,
        fee_rate=p.fee_rate, slippage_rate=p.slippage_rate, stamp_duty_rate=p.stamp_duty_rate,
        assets=[SimpleNamespace(symbol=a["symbol"], source=a["source"], quadrant=a["quadrant"])
                for a in p.assets],
    )
    p.name = "旧名字"
    p.description = ""
    changed = diff_payload(p, payload)
    assert changed == {"name", "rebalance_band"}
```

注意：`_pdef()` 需要补 `name`/`description` 字段（Step 3 中 `canonical_params` 不消费它们，但 `diff_payload` 需要；给 `_pdef` 的 base 加 `name="旧名字", description=""`，并同步修正 Task 4 测试不受影响）。

实现（`bp_api/repositories.py`）：

```python
META_ONLY_FIELDS = {"name", "description"}


def diff_payload(pdef, payload) -> set[str]:
    """对比当前定义与提交 payload, 返回变化字段名集合(含 name/description/assets)。"""
    new = {
        "method": payload.method,
        "ratio": payload.ratio,
        "lookback_days": int(payload.lookback_days) if payload.lookback_days is not None else None,
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "benchmark_key": _resolve_benchmark_key(payload.benchmark_key),
        "max_weight": _r4(payload.max_weight),
        "rebalance_band": _r4(payload.rebalance_band),
        "risk_free_rate": _r4(payload.risk_free_rate),
        "fee_rate": _r4(payload.fee_rate),
        "slippage_rate": _r4(payload.slippage_rate),
        "stamp_duty_rate": _r4(payload.stamp_duty_rate),
        "assets": sorted([a.symbol, a.source, a.quadrant] for a in payload.assets),
    }
    changed = {k for k in new if canonical_params(pdef)[k] != new[k]}
    if payload.name != (pdef.name or ""):
        changed.add("name")
    if (payload.description or "") != (pdef.description or ""):
        changed.add("description")
    return changed


def update_portfolio_def_only(conn, pid: int, payload) -> None:
    """只更新组合定义与资产, 不改 status、不触发回测。列集与 update_portfolio 对齐。"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_portfolio
               SET name=%s, description=%s, method=%s, ratio=%s, lookback_days=%s,
                   start_date=%s, benchmark_key=%s, max_weight=%s, rebalance_band=%s,
                   risk_free_rate=%s, fee_rate=%s, slippage_rate=%s, stamp_duty_rate=%s,
                   updated_at=now()
               WHERE portfolio_id=%s""",
            (payload.name, payload.description, payload.method, payload.ratio,
             payload.lookback_days, payload.start_date,
             _resolve_benchmark_key(payload.benchmark_key),
             payload.max_weight, payload.rebalance_band, payload.risk_free_rate,
             payload.fee_rate, payload.slippage_rate, payload.stamp_duty_rate, pid),
        )
        cur.execute("DELETE FROM bp_portfolio_asset WHERE portfolio_id=%s", (pid,))
        for i, a in enumerate(payload.assets):
            cur.execute(
                """INSERT INTO bp_portfolio_asset
                     (portfolio_id, symbol, source, quadrant, display_name, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (pid, a.symbol, a.source, a.quadrant, a.display_name, i),
            )


def is_portfolio_stale(conn, pid: int) -> bool:
    pdef = _read_def(conn, pid)
    return is_params_stale(canonical_params(pdef), pdef.last_run_params)
```

（`PortfolioDef` 需含 `name`/`description`——`_read_def` 若未取这两列则补上。）

- [ ] **Step 3: main.py PATCH handler 重写**

将现有 `update_portfolio_meta`（main.py:292-317）替换为（保持装饰器与路由不变）：

```python
@app.patch("/api/portfolios/{portfolio_id}/meta")
def update_portfolio_meta(
    portfolio_id: int, payload: UpdatePortfolioIn, user=Depends(auth.require_user)
):
    with db.get_conn() as conn:
        try:
            st = repo.get_portfolio_status(conn, portfolio_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="组合不存在")
        if not repo.can_edit_portfolio(conn, user, portfolio_id):
            raise HTTPException(status_code=403, detail="无权编辑该组合")
        _validate_portfolio_payload(payload)
        pdef = repo.read_def(conn, portfolio_id)
        changed = repo.diff_payload(pdef, payload)
        non_meta = changed - repo.META_ONLY_FIELDS
        if st["status"] == "running" and non_meta:
            raise HTTPException(status_code=409, detail="回测进行中, 请稍后再编辑")
        if not payload.name or not str(payload.name).strip():
            raise HTTPException(status_code=400, detail="组合名称不能为空")
        if changed:
            repo.update_portfolio_def_only(conn, portfolio_id, payload)
        conn.commit()
        stale = repo.is_portfolio_stale(conn, portfolio_id)
    cache.delete_pattern(f"portfolio_result:{portfolio_id}:*")
    return {"portfolio_id": portfolio_id, "params_stale": stale}
```

（对齐现有代码风格：若现有函数用其他 404/403 写法，保持一致；`_validate_portfolio_payload`、`repo`、`cache` 均为 main.py 现有引用。）

- [ ] **Step 4: 路由 smoke 测试**

追加到 `bp_api/tests/test_api_routes.py`：

```python
def test_recompute_all_route_registered():
    assert "POST" in _route_methods("/api/admin/portfolios/recompute-all")
```

（此断言在 Task 7 实现端点后才通过；若想保持本任务绿，把该测试移到 Task 7。推荐：移到 Task 7。）

- [ ] **Step 5: 全量运行**

```bash
.venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全绿。

---

### Task 6: portfolio_limit NULL=无限 + 建用户参数

**Files:**
- Modify: `bp_api/repositories.py`（`get_user_portfolio_limit` ~L1001-1007）、`bp_api/auth.py`（`create_user` ~L323-341）、`bp_api/schemas.py`（`CreateUserIn` ~L95-97）、`bp_api/main.py`（`create_admin_user`）、`bp_api/main.py`+`bp_api/auth.py`（`update_admin_user`/`update_user` 支持显式 `portfolio_limit: null`）
- Test: `bp_api/tests/test_edit_flow.py`（追加）

**Interfaces:**
- Produces: `get_user_portfolio_limit` 返回 `None`=无限（admin 或显式无限）；`CreateUserIn` 新增 `portfolio_limit: Optional[int]`（默认 3，null=无限）与 `can_manage_assets: bool=False`；`PATCH /api/admin/users/{email}` 接受显式 `portfolio_limit: null`。

- [ ] **Step 1: 写失败测试**

追加到 `bp_api/tests/test_edit_flow.py`：

```python
def test_create_user_in_accepts_unlimited():
    from bp_api.schemas import CreateUserIn
    body = CreateUserIn(email="a@b.c", password="pw123456", portfolio_limit=None,
                        can_manage_assets=True)
    assert body.portfolio_limit is None
    assert body.can_manage_assets is True
    assert CreateUserIn(email="a@b.c", password="x").portfolio_limit == 3
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CreateUserIn(email="a@b.c", password="x", portfolio_limit=-1)


def test_get_user_portfolio_limit_null_means_unlimited():
    from unittest.mock import MagicMock
    from bp_api.repositories import get_user_portfolio_limit
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = ("user", None)
    assert get_user_portfolio_limit(conn, 1) is None
    cur.fetchone.return_value = ("user", 5)
    assert get_user_portfolio_limit(conn, 1) == 5
    cur.fetchone.return_value = ("admin", 3)
    assert get_user_portfolio_limit(conn, 1) is None
```

运行确认失败。

- [ ] **Step 2: 实现**

`bp_api/schemas.py`：

```python
class CreateUserIn(BaseModel):
    email: str
    password: str
    portfolio_limit: Optional[int] = Field(default=3, ge=0)  # null = 无限
    can_manage_assets: bool = False
```

`bp_api/repositories.py`：

```python
def get_user_portfolio_limit(conn, user_id) -> Optional[int]:
    """None = 无限(admin 或显式无限); int = 上限。"""
    with conn.cursor() as cur:
        cur.execute("SELECT role, portfolio_limit FROM bp_user WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
    if not row:
        return 3
    role, limit = row
    if role == "admin":
        return None
    return limit
```

`bp_api/auth.py` `create_user` 签名与 INSERT：

```python
def create_user(conn, email: str, password: str,
                portfolio_limit: Optional[int] = 3,
                can_manage_assets: bool = False):
    ...
    cur.execute(
        """INSERT INTO bp_user (email, password_hash, role, status, portfolio_limit, can_manage_assets)
           VALUES (%s, %s, 'user', 'active', %s, %s)""",
        (email_norm, hash_password(password), portfolio_limit, can_manage_assets),
    )
```

（保持现有重复校验与 `bp_admin_user` legacy 写入逻辑不动。）

`bp_api/main.py` `create_admin_user`：透传 `body.portfolio_limit, body.can_manage_assets`。

`update_admin_user` + `auth.update_user`：支持显式 null——用 `model_fields_set` 判定：

```python
# main.py
if "portfolio_limit" in body.model_fields_set:
    auth.update_user(conn, email, portfolio_limit=body.portfolio_limit, ...)
```

`auth.update_user` 对 portfolio_limit 的 SET 分支改为「字段在调用中被显式传入即写入（含 None）」——实现方式：给 `update_user` 增加哨兵参数 `_UNSET = object()`，`portfolio_limit=_UNSET` 表示不改；显式 `None` 写入 `SET portfolio_limit = NULL`。

- [ ] **Step 3: 全量测试**

```bash
.venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全绿（含 `test_settings_auth.py` 现有 auth 测试）。

---

### Task 7: recompute-all 端点

**Files:**
- Modify: `bp_api/repositories.py`（新增 `list_recomputable_portfolio_ids`）、`bp_api/main.py`（新增端点）
- Test: `bp_api/tests/test_api_routes.py`、`bp_api/tests/test_edit_flow.py`（追加）

**Interfaces:**
- Consumes: 现有 `_enqueue_backtest` / `_dispatch_backtest`（main.py:66-99）、`POST /api/portfolios/{id}/recompute`（main.py:413-434）的内部流程作为参照。
- Produces: `POST /api/admin/portfolios/recompute-all`（require_super_admin）→ `{enqueued: n}`。

- [ ] **Step 1: 写失败测试**

`bp_api/tests/test_api_routes.py` 追加：

```python
def test_recompute_all_route_registered():
    assert "POST" in _route_methods("/api/admin/portfolios/recompute-all")
```

`bp_api/tests/test_edit_flow.py` 追加：

```python
def test_list_recomputable_portfolio_ids():
    from unittest.mock import MagicMock
    from bp_api.repositories import list_recomputable_portfolio_ids
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [(1,), (4,), (7,)]
    assert list_recomputable_portfolio_ids(conn) == [1, 4, 7]
```

运行确认失败。

- [ ] **Step 2: 实现**

`bp_api/repositories.py`：

```python
def list_recomputable_portfolio_ids(conn) -> list[int]:
    """非 running 且有资产的组合(含 demo), 按 id 升序。"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.portfolio_id FROM bp_portfolio p
               WHERE p.status <> 'running'
                 AND EXISTS (SELECT 1 FROM bp_portfolio_asset a
                             WHERE a.portfolio_id = p.portfolio_id)
               ORDER BY p.portfolio_id""")
        return [r[0] for r in cur.fetchall()]
```

`bp_api/main.py`（放在 admin 路由区，参照 `enqueue_ready` 端点位置）：

```python
@app.post("/api/admin/portfolios/recompute-all")
def recompute_all_portfolios(user=Depends(auth.require_super_admin)):
    """强制重算全部组合(含 demo)。逐个走标准回测任务管线。"""
    with db.get_conn() as conn:
        pids = repo.list_recomputable_portfolio_ids(conn)
        enqueued = 0
        for pid in pids:
            # 与单组合 recompute 端点(main.py:413-434)相同的入队方式
            task_id = _enqueue_backtest(conn, pid, kind="recompute_all")
            conn.commit()
            _dispatch_backtest(pid, task_id)
            enqueued += 1
    return {"enqueued": enqueued}
```

（实施时对照单组合 recompute 端点：若 `_enqueue_backtest` 签名/返回不同，或 recompute 端点在入队前有额外状态检查，照抄其入队三行；`kind` 参数名以 `tasking.create_task` 实际签名为准。）

- [ ] **Step 3: 全量测试**

```bash
.venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全绿。

---

### Task 8: 死配置清理 + 过时文案

**Files:**
- Modify: `bp_api/settings.py`（删 3 个死配置）、`.env.example`、`bp_api/main.py:331` 过时文案、`CLAUDE.md`

- [ ] **Step 1: 确认无消费方**

```bash
grep -rn "BP_RISK_FREE\|BP_DEFAULT_LOOKBACK\|BP_REBALANCE_BAND\|risk_free\b.*settings\|settings.default_lookback\|settings.rebalance_band\|settings.risk_free" bp_api/ bp_ingest/ web/ --include="*.py" --include="*.ts"
```
Expected: 仅 `settings.py` 定义处与 `.env.example`（若有其他消费方则改为接线而非删除，并在本任务说明）。

- [ ] **Step 2: 删除**

`bp_api/settings.py` 删除 `BP_RISK_FREE` / `BP_DEFAULT_LOOKBACK` / `BP_REBALANCE_BAND` 的定义、env 读取与 dataclass 字段；`.env.example` 删除对应三行；`main.py:331` 文案中「04_seed_demo_portfolio.sql」改为「schema.sql 的 demo seed」。

- [ ] **Step 3: CLAUDE.md 同步**

把「组合级参数（risk_free/lookback/rebalance_band）存在组合上，环境变量仅作新建兜底」改为「组合级参数（risk_free/lookback/rebalance_band）以组合行为唯一口径，无环境变量兜底（2026-09 已清理死配置）」。

- [ ] **Step 4: 全量测试**

```bash
.venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全绿（`test_settings_auth.py` 若断言了这些字段需同步删除断言）。

---

## Phase P2：前端功能

### Task 9: web/lib/api.ts 常量与类型同步

**Files:**
- Modify: `web/lib/api.ts`（`BENCHMARK_OPTIONS` L49-55、`BENCHMARK_COMPOSITION` L58-82、`PortfolioInfo` 类型、`createUser` L809-812、`updateUser` L815-822、`updatePortfolioMeta` L674-677，新增 `recomputeAllPortfolios`）

- [ ] **Step 1: BENCHMARK_OPTIONS 追加三项**（保持既有对象字段结构）

```ts
{ key: "sp500_etf", name: "标普500ETF", kind: "total_return" },
{ key: "ndx100_etf", name: "纳斯达克100ETF", kind: "total_return" },
{ key: "n225_etf", name: "日经225ETF", kind: "total_return" },
```

- [ ] **Step 2: BENCHMARK_COMPOSITION 追加三条**——先读现有条目结构（L58-82），按同样的 legs/note 字段结构写入，内容：

- `sp500_etf`: legs = 100% 博时标普500ETF（513500，人民币计价 QDII，后复权）；note = 「人民币计价，可与组合收益直接比较；含汇率波动与场内折溢价噪声。」
- `ndx100_etf`: legs = 100% 国泰纳斯达克100ETF（513100）；note 同上。
- `n225_etf`: legs = 100% 华夏日经225ETF（513520）；note = 「2019-06-25 上市，早于该日的回测不显示此基准；人民币计价，含汇率波动与折溢价噪声。」

- [ ] **Step 3: 类型与函数**

`PortfolioInfo` 增加 `params_stale?: boolean;`。

```ts
createUser: (email: string, password: string,
             opts?: { portfolio_limit?: number | null; can_manage_assets?: boolean }) =>
  req<{ email: string }>("/api/admin/users", {
    method: "POST",
    body: JSON.stringify({ email, password, ...(opts ?? {}) }),
  }),

updatePortfolioMeta: (id: number, payload: PortfolioPayload) =>
  req<{ portfolio_id: number; params_stale: boolean }>(
    `/api/portfolios/${id}/meta`,
    { method: "PATCH", body: JSON.stringify(payload) }),

recomputeAllPortfolios: () =>
  req<{ enqueued: number }>("/api/admin/portfolios/recompute-all", { method: "POST" }),
```

（`PortfolioPayload` 若不存在同名类型，用现有 `updatePortfolio` 的入参类型；`updateUser` 的 `portfolio_limit` 类型改为 `number | null`。）

- [ ] **Step 4: 验证**

```bash
cd web && npm run typecheck
```
Expected: 0 错误（调用方类型不匹配会在后续任务修复；此处若报调用方错误，说明需要把调用方改动前置——记录并在对应任务处理）。

---

### Task 10: Builder 三项小修（宽度/文案/取整）

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`（L694、L698、L701、L387、L126、L217）

- [ ] **Step 1: 五处修改**

```tsx
// L694: 弹窗宽度(必须带 sm: 前缀才能覆盖基座 sm:max-w-lg)
<DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-y-auto">

// L698: 内部栅格右栏收窄
// 旧: grid grid-cols-1 md:grid-cols-[1fr_300px] gap-4
// 新:
// grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_260px] gap-4

// L701: 过滤行允许换行兜底
// 旧: flex gap-2   新: flex flex-wrap gap-2

// L387: 文案
// 旧: <h2 className="text-xl font-medium">选择优化方法</h2>
// 新: <h2 className="text-xl font-medium">选择默认的优化方法</h2>

// L126: 预填取整(修复 7.000000000000001)
setBand(+((p.rebalance_band ?? 0.05) * 100).toFixed(2));

// L217: 保存取整(防 epsilon 写回)
rebalance_band: Math.round(band * 100) / 10000,
```

- [ ] **Step 2: 构建验证**

```bash
cd web && npm run typecheck && npm run build
```
Expected: 通过。浏览器手测（npm run dev）：/builder 打开「添加资产」弹窗宽度 ≈896px，左列下拉不挤；编辑已有组合偏离带显示 `7` 而非长尾小数。

---

### Task 11: sonner + ChangeDiffDialog + Builder 编辑流

**Files:**
- Create: `web/components/ui/sonner.tsx`、`web/components/ChangeDiffDialog.tsx`
- Modify: `web/app/layout.tsx`（挂 `<Toaster/>`）、`web/package.json`（+sonner）、`web/app/builder/BuilderClient.tsx`（diff 状态与保存流）

**Interfaces:**
- Consumes: Task 9 的 `updatePortfolioMeta(id, payload)`（返回 params_stale）、`buildPayload()`（BuilderClient.tsx:208-230）。
- Produces: `ChangeDiffDialog` 组件；编辑模式「保存」→ PATCH 全量免重算，「保存并重算」→ PUT（现有）；两者前置 diff 弹窗。

- [ ] **Step 1: 安装 sonner + Toaster**

```bash
cd web && npm install sonner --legacy-peer-deps
```

`web/components/ui/sonner.tsx`：

```tsx
"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

export function Toaster(props: React.ComponentProps<typeof Sonner>) {
  const { theme = "system" } = useTheme();
  return (
    <Sonner
      theme={theme as "light" | "dark" | "system"}
      className="toaster group"
      position="top-center"
      richColors
      closeButton
      {...props}
    />
  );
}
```

`web/app/layout.tsx`：import 并在 `<body>` 末尾加 `<Toaster />`。

- [ ] **Step 2: ChangeDiffDialog 组件**

`web/components/ChangeDiffDialog.tsx`：

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

export function ChangeDiffDialog({
  open, onOpenChange, diffs, assetSummary, canRecompute, busy, onMetaSave, onRecompute,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  diffs: DiffRow[];
  assetSummary: string | null;
  canRecompute: boolean;   // 有回测参数变更时允许重算入口
  busy: boolean;
  onMetaSave: () => void;
  onRecompute: () => void;
}) {
  const rows = assetSummary
    ? [...diffs, { label: "资产构成", before: "", after: assetSummary }]
    : diffs;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>确认变更</DialogTitle>
          <DialogDescription>
            以下为本次修改的参数。可仅保存（不重算回测），或保存并重新计算。
          </DialogDescription>
        </DialogHeader>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">没有检测到参数变更。</p>
        ) : (
          <div className="max-h-[45vh] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[35%]">参数</TableHead>
                  <TableHead className="w-[32%]">变更前</TableHead>
                  <TableHead className="w-[32%]">变更后</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.label}>
                    <TableCell className="text-sm font-medium">{r.label}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.before || "—"}</TableCell>
                    <TableCell className="text-sm">{r.after}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {canRecompute && (
          <p className="text-xs text-warning">
            含回测参数变更：仅保存不会更新回测结果，组合将标记为「待重算」。
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>取消</Button>
          <Button variant="outline" onClick={onMetaSave} disabled={busy || rows.length === 0}>
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

- [ ] **Step 3: BuilderClient 状态与 diff 计算**

在 `BuilderInner` 内新增（紧邻现有 `origSig` 逻辑 ~L197-206）：

```tsx
// 编辑预填完成时, 除锁定 origSig 外, 同时保存原始表单值用于 diff 展示
interface OrigSnapshot {
  name: string; description: string; method: string; benchmarkKey: string;
  ratio: string; lookback: number; band: number; maxWeightPct: number;
  riskFreePct: number; feePct: number; slippagePct: number; stampDutyPct: number;
  startDate: string | null;
  assets: { key: string; label: string; quadrant: string }[];
}
const origSnapRef = useRef<OrigSnapshot | null>(null);
const [diffOpen, setDiffOpen] = useState(false);
```

预填 effect（~L102-157）锁定 `origSig` 的同一处写入 `origSnapRef.current`（assets 从四象限状态摊平：`[{key: symbol@source, label: display_name||symbol, quadrant}]`）。

格式化工具（文件顶层）：

```tsx
const fmtRatePct = (v: number) => `${+(v * 100).toFixed(2)}%`;      // 0.0005 → 0.05%
const fmtBandPct = (v: number) => `${+v.toFixed(2)}%`;               // band 已是百分数
const METHOD_NAME = Object.fromEntries(METHOD_OPTIONS.map(m => [m.value, m.label]));
const BENCH_NAME = Object.fromEntries(BENCHMARK_OPTIONS.map(b => [b.key, b.name]));
```

diff 计算（`useMemo` 或函数 `computeDiffs()`）：

```tsx
function computeDiffs(): { rows: DiffRow[]; assetSummary: string | null; hasBacktestChange: boolean } {
  const o = origSnapRef.current;
  if (!o) return { rows: [], assetSummary: null, hasBacktestChange: false };
  const rows: DiffRow[] = [];
  const add = (label: string, b: string | number, a: string | number) => {
    if (String(b) !== String(a)) rows.push({ label, before: String(b), after: String(a) });
  };
  add("组合名称", o.name, name);
  add("组合描述", o.description || "—", description || "—");
  add("默认优化方法", METHOD_NAME[o.method] ?? o.method, METHOD_NAME[method] ?? method);
  add("对比基准", BENCH_NAME[o.benchmarkKey] ?? o.benchmarkKey, BENCH_NAME[benchmarkKey] ?? benchmarkKey);
  add("回看窗口", `${o.lookback} 天`, `${lookback} 天`);
  if (o.startDate || startDate) add("起始日期", o.startDate ?? "自动", startDate ?? "自动");
  add("单资产上限", `${+o.maxWeightPct.toFixed(2)}%`, `${+maxWeightPct.toFixed(2)}%`);
  add("再平衡偏离带", fmtBandPct(o.band), fmtBandPct(band));
  add("无风险利率", fmtRatePct(o.riskFreePct / 100), fmtRatePct(riskFreePct / 100));
  add("佣金费率", fmtRatePct(o.feePct / 100), fmtRatePct(feePct / 100));
  add("滑点", fmtRatePct(o.slippagePct / 100), fmtRatePct(slippagePct / 100));
  add("印花税（卖出）", fmtRatePct(o.stampDutyPct / 100), fmtRatePct(stampDutyPct / 100));
  // 资产构成
  const cur = quadrants.flatMap(q => q.assets.map(a => ({ key: `${a.symbol}@${a.source}`, label: a.display_name || a.symbol, quadrant: q.key })));
  const oMap = new Map(o.assets.map(a => [a.key, a]));
  const cMap = new Map(cur.map(a => [a.key, a]));
  const added = cur.filter(a => !oMap.has(a.key)).map(a => a.label);
  const removed = o.assets.filter(a => !cMap.has(a.key)).map(a => a.label);
  const moved = cur.filter(a => oMap.has(a.key) && oMap.get(a.key)!.quadrant !== a.quadrant)
    .map(a => `${a.label}（${oMap.get(a.key)!.quadrant}→${a.quadrant}）`);
  const assetSummary = (added.length || removed.length || moved.length)
    ? [added.length && `新增：${added.join("、")}`,
       removed.length && `移除：${removed.join("、")}`,
       moved.length && `调整：${moved.join("、")}`].filter(Boolean).join("；")
    : null;
  const metaOnlyLabels = new Set(["组合名称", "组合描述", "默认优化方法", "对比基准"]);
  const hasBacktestChange = rows.some(r => !metaOnlyLabels.has(r.label)) || assetSummary !== null;
  return { rows, assetSummary, hasBacktestChange };
}
```

（象限状态变量名以实际代码为准：四象限数组与其 key/资产字段——实施时对照 `backtestSig` 的 `assetSig` 构造逻辑（L187-195）取同一来源。象限中文名映射：overheat 过热 / stagflation 滞胀 / recovery 复苏 / recession 衰退。）

- [ ] **Step 4: 按钮与处理器改造**

底部操作栏（~L576-601）编辑模式分支改为：

```tsx
{isEditMode && !isCopyMode ? (
  <>
    <Button variant="outline" disabled={busy || !backtestParamsChanged && origSnapRef.current === null}
            onClick={() => setDiffOpen(true)}>
      保存
    </Button>
    <Button onClick={() => { if (!canMetaOnlySave) handleSubmitClick(); else setDiffOpen(true); }} ... />
  </>
) : ( /* 新建模式原样保留「生成组合」→ ConfirmRecomputeDialog */ )}
```

实际语义（实现时以下述为准，替换上面示意）：
- 「保存」按钮：`setDiffOpen(true)`（无任何变更时禁用，旁边 `text-xs text-muted-foreground` 提示「无待保存变更」——由 `computeDiffs()` 全空判定）。
- 「保存并重算」按钮：同样 `setDiffOpen(true)`（弹窗内再选路径）。
- 新建模式不变。

`ChangeDiffDialog` 挂载（与 ConfirmRecomputeDialog 并列）：

```tsx
<ChangeDiffDialog
  open={diffOpen}
  onOpenChange={setDiffOpen}
  diffs={computeDiffs().rows}
  assetSummary={computeDiffs().assetSummary}
  canRecompute={computeDiffs().hasBacktestChange}
  busy={busy || savingMeta}
  onMetaSave={async () => {
    try {
      const res = await api.updatePortfolioMeta(editId!, buildPayload());
      setDiffOpen(false);
      if (res.params_stale) {
        toast.success("已保存。回测参数有变更，结果将在重算后生效。");
      } else {
        toast.success("已保存。");
      }
      router.push(`/dashboard?id=${editId}`);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setDiffOpen(false);
    }
  }}
  onRecompute={() => { setDiffOpen(false); handleSubmitClick(); }}
/>
```

注意：`handleSubmitClick` 现在会再次打开 `ConfirmRecomputeDialog`——编辑模式走 diff 流时应跳过它：给 `handleSubmitClick` 增加参数 `skipConfirm?: boolean`（diff 弹窗已承担确认职责），`onRecompute` 调 `handleSubmitClick(true)`；`onRecompute` 内直接走 `startBacktest`。409 错误文案经 `setError` banner 展示（保留现状）+ `toast.error`。

- [ ] **Step 5: 验证**

```bash
cd web && npm run typecheck && npm run build
```
浏览器手测：编辑组合→只改名→「保存」→弹窗仅一行变更→仅保存→dashboard 无重算；改印花税→弹窗含该行→「仅保存」→dashboard 出现待重算提示（依赖 Task 12 条幅）；「保存并重算」→进度弹窗。

---

### Task 12: Dashboard TOC + 默认组合 + stale 条幅

**Files:**
- Modify: `web/components/DashboardToc.tsx`（L56、L53-63）、`web/lib/session-server.ts`（新增 claims 解码）、`web/lib/cached-data.ts`（`resolveDefaultPortfolioId` L74-88）、`web/app/dashboard/DashboardClient.tsx`（stale 条幅，顶部信息卡 ~L476-573 之后）

**Interfaces:**
- Consumes: Task 9 的 `params_stale` 字段。
- Produces: 管理员默认第一个公共案例、普通用户先自有后公共；TOC 指针手型 + 13px。

- [ ] **Step 1: TOC 修复**

`web/components/DashboardToc.tsx`：

```tsx
// :43 nav wrapper 保持 text-sm 无妨; :56 按钮类替换为:
className="w-full text-left text-[13px] leading-6 py-1 px-3 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/60 cursor-pointer transition-colors"
// active 项追加: "text-primary font-medium"（现有 active 逻辑保留）
```

- [ ] **Step 2: session claims 助手**

`web/lib/session-server.ts` 新增：

```ts
export function readSessionClaims(): { sub?: string; role?: string } | null {
  const token = readSessionToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    return null;
  }
}
```

- [ ] **Step 3: 默认组合逻辑**

`web/lib/cached-data.ts` `resolveDefaultPortfolioId`（L74-88）整体替换为：

```ts
export async function resolveDefaultPortfolioId(): Promise<number | null> {
  const token = readSessionToken();
  if (!token) return null;
  try {
    const res = await fetch(`${apiBase()}/api/portfolios`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = await res.json();
    const list: { portfolio_id: number; is_demo: boolean }[] = data?.portfolios ?? [];
    const claims = readSessionClaims();
    const firstDemo = list.find((p) => p.is_demo);
    if (claims?.role === "admin") {
      return firstDemo ? firstDemo.portfolio_id : null;   // 管理员默认公共案例第一
    }
    const firstOwn = list.find((p) => !p.is_demo);
    if (firstOwn) return firstOwn.portfolio_id;
    return firstDemo ? firstDemo.portfolio_id : null;
  } catch {
    return null;
  }
}
```

（import `readSessionClaims`。）

- [ ] **Step 4: stale 条幅**

`DashboardClient.tsx` 顶部信息卡之后（~L573 后）插入：

```tsx
{portfolio?.params_stale && !portfolio.is_demo && canEdit && (
  <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm flex flex-wrap items-center gap-3">
    <span className="text-warning font-medium">参数已调整</span>
    <span className="text-muted-foreground">组合参数与当前回测结果不一致，重新计算后生效。</span>
    <Link href={`/builder?id=${portfolio.portfolio_id}`}
          className="ml-auto text-primary hover:underline cursor-pointer">
      去重算 →
    </Link>
  </div>
)}
```

（`portfolio` 变量名以 `DashboardView` 实际 props 为准；`border-warning/40` 等依赖 Task 15 的 warning token——本任务先用 `border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400` 过渡亦可，Task 15 统一替换为 token。）

- [ ] **Step 5: 验证**

```bash
cd web && npm run typecheck && npm run build
```
手测：管理员登录 → /dashboard（无 id）→ 重定向到第一个公共案例；普通用户（无组合）→ 公共案例；有组合 → 自己第一个。TOC hover 出现指针、字号变小。

---

### Task 13: /admin/users 创建表单 + 无限上限

**Files:**
- Modify: `web/app/admin/users/page.tsx`（创建表单 ~L140-150、上限列 ~L205-236）

**Interfaces:**
- Consumes: Task 9 的 `createUser(email, password, opts)`、`updateUser(email, {portfolio_limit: null})`。

- [ ] **Step 1: 创建表单扩展**

在「添加用户」卡片增加两个控件（与现有 Input 同风格）：

```tsx
// state
const [newAssetEdit, setNewAssetEdit] = useState(false);
const [newLimitUnlimited, setNewLimitUnlimited] = useState(false);
const [newLimit, setNewLimit] = useState("3");

// UI（Card 内, 密码输入框下方）
<label className="flex items-center gap-2 text-sm">
  <Switch checked={newAssetEdit} onCheckedChange={setNewAssetEdit} />
  资产编辑权限
  <span className="text-xs text-muted-foreground">（可进 /admin/assets 新增/更新/测试/拉取增量）</span>
</label>
<div className="flex items-center gap-2 text-sm">
  <span>组合上限</span>
  <Input type="number" min={0} step={1} className="w-20 h-8 font-mono"
         value={newLimit} onChange={(e) => setNewLimit(e.target.value)}
         disabled={newLimitUnlimited} />
  <label className="flex items-center gap-1.5">
    <Checkbox checked={newLimitUnlimited} onCheckedChange={(v) => setNewLimitUnlimited(v === true)} />
    无限
  </label>
</div>
```

`onCreate`（~L52-65）改为：

```tsx
const limit = newLimitUnlimited ? null : Math.floor(Number(newLimit));
if (!newLimitUnlimited && (!Number.isFinite(limit!) || limit! < 0)) {
  setError("组合上限须为非负整数或无限");
  return;
}
await api.createUser(email, password, {
  portfolio_limit: limit,
  can_manage_assets: newAssetEdit,
});
// 成功后重置: setEmail/setPassword("")、setNewAssetEdit(false)、setNewLimitUnlimited(false)、setNewLimit("3")
```

- [ ] **Step 2: 列表行支持无限**

上限列（~L205-236）：`portfolio_limit == null` 的普通用户行显示「不限」徽章 + 「设上限」按钮（点击切换为输入框模式，初值 3）；现有输入框+保存保留，另加「设为无限」小按钮 → `api.updateUser(email, { portfolio_limit: null })` 成功后刷新。超管行维持静态「不限」。（后端显式 null 支持已在 Task 6 落地。）

- [ ] **Step 3: 验证**

```bash
cd web && npm run typecheck && npm run build
```
手测：建用户勾选无限 → 列表显示「不限」，且该用户可创建超过 3 个组合（后端限额已按新语义）。

---

### Task 14: /admin/assets 表布局 + 强制重算按钮 + AlertDialog

**Files:**
- Create: `web/components/ui/alert-dialog.tsx`
- Modify: `web/app/admin/assets/page.tsx`（表头 ~L445-468、行 ~L490-535、头部按钮区 ~L379-396）、`web/app/admin/users/page.tsx`（删除确认 L241-248 换 AlertDialog）

- [ ] **Step 1: AlertDialog 原语**

新建 `web/components/ui/alert-dialog.tsx`——标准 shadcn 封装（Radix `@radix-ui/react-alert-dialog`；先 `cd web && npm ls @radix-ui/react-alert-dialog` 确认，缺则 `npm install @radix-ui/react-alert-dialog --legacy-peer-deps`）。导出 `AlertDialog/AlertDialogTrigger/AlertDialogContent/AlertDialogHeader/AlertDialogTitle/AlertDialogDescription/AlertDialogFooter/AlertDialogAction/AlertDialogCancel`，Action/Cancel 复用 `buttonVariants`（与 `web/components/ui/dialog.tsx` 的实现风格保持一致：`cn()` + 前向引用）。

- [ ] **Step 2: 资产表布局重整**（目标 1280px 无横滚）

- 表格 `min-w-[1160px]` → `min-w-[980px]`。
- 列结构调整（表头与单元格同步）：
  1. 名称：`min-w-[140px] max-w-[200px]`，单元格 `truncate` + `title={name}`；
  2. 「Symbol / Source / 复权」三列合并为一列「代码 / 源」：两行等宽小字（`font-mono text-xs`：第一行 `symbol`，第二行 `source · adjust`）；
  3. 「状态」「行数」「新鲜度」保留但 `text-xs tabular-nums` 紧凑化（`px-2`）；
  4. 「清洗截至」并入「新鲜度」单元格（第二行小字），表头删该列；
  5. 「最近错误」列改为 `w-10` 图标列：无错误 `CheckCircle2 className="text-success"`，有错误 `AlertTriangle className="text-warning"`，整格 `title={last_error}`（并保留 max-w 样式删除）；
  6. 操作列：按钮改 `variant="ghost" size="sm"` + 图标 + 两字文案（`测试`/`增量`/`删除`），`className="h-7 px-2 gap-1 text-xs"`，删除保留 `text-destructive hover:text-destructive`；单元格维持 `text-right whitespace-nowrap`。
- 逐个表头核对 `min-w`/`whitespace-nowrap` 残留，删除多余。

- [ ] **Step 3: 强制重算全部组合按钮**

头部超管按钮区（~L379-396）追加（仅 `isSuperAdmin` 渲染）：

```tsx
<AlertDialog>
  <AlertDialogTrigger asChild>
    <Button variant="outline" size="sm"><RefreshCw className="h-4 w-4 mr-1" />强制重算全部组合</Button>
  </AlertDialogTrigger>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>强制重算全部组合？</AlertDialogTitle>
      <AlertDialogDescription>
        将对所有组合（含公共案例）重新执行 4 种方法的回测，单个组合约需 2–10 分钟，期间组合不可编辑。此操作不可撤销。
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel>取消</AlertDialogCancel>
      <AlertDialogAction onClick={async () => {
        try {
          const r = await api.recomputeAllPortfolios();
          toast.success(`已入队 ${r.enqueued} 个组合的重算任务`);
          reload(); // 刷新列表状态的现有函数
        } catch (e) {
          toast.error(String(e instanceof Error ? e.message : e));
        }
      }}>确认重算</AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

- [ ] **Step 4: window.confirm 替换**

`admin/assets/page.tsx` 删除按钮（~L527-531）与 `admin/users/page.tsx` 删除（~L241-248）的 `window.confirm` 换为 AlertDialog（结构同上，文案保留现有语义，确认动作调现有 `remove()`/`onDelete`）。

- [ ] **Step 5: 验证**

```bash
cd web && npm run typecheck && npm run build
```
手测：1440/1280 宽度下操作列完整可见无横滚；错误图标 hover 显示全文；强制重算按钮弹窗→取消正常。

---

## Phase P3：设计系统

### Task 15: globals.css token 重构 + 涨跌色翻转 + 语义净化

**Files:**
- Modify: `web/app/globals.css`（:5-99 token 区、:101-133 @layer base）、`web/app/builder/BuilderClient.tsx`（L27-30 象限色）、`web/app/dashboard/DashboardClient.tsx`（L42 象限色、Task 12 过渡色替换）、`web/components/mdx.tsx`（L55-58）、`web/app/otc-derivatives-pricing/OtcPricingClient.tsx`（L109）、`web/app/cffex/CffexClient.tsx`（L594-604、L717-722）

- [ ] **Step 1: 替换 token 定义**

`globals.css` 的 `:root` 与 `.dark` 中，按下表改值（保留其余变量与结构）：

```css
:root {
  --primary: #0284C7;            /* sky-600 */
  --primary-foreground: #FFFFFF;
  --ring: rgba(14, 165, 233, 0.5);
  --up: #16A34A;                 /* 绿涨 */
  --down: #DC2626;               /* 红跌 */
  --success: #16A34A;
  --warning: #D97706;
}
.dark {
  --primary: #38BDF8;            /* sky-400 */
  --primary-foreground: #082F49;
  --ring: rgba(56, 189, 248, 0.5);
  --up: #4ADE80;
  --down: #F87171;
  --success: #4ADE80;
  --warning: #FBBF24;
}
```

`@theme inline` 区追加映射：

```css
  --color-success: var(--success);
  --color-warning: var(--warning);
```

`@layer base` 中删除 `button { font-size: var(--text-base); }`（若该行与其他属性同在一个规则块，只删 font-size 行，保留字重/行高）。

- [ ] **Step 2: 象限色调语义化**

三处象限映射统一改为：

```ts
// BuilderClient.tsx:27-30 与 DashboardClient.tsx:42 与 mdx.tsx:55-58
overheat: "text-warning",       // 过热=通胀上行, 琥珀
stagflation: "text-destructive",// 滞胀=最差象限, 红
recovery: "text-success",       // 复苏, 绿
recession: "text-weak",         // 衰退, 灰
```

（`recovery`/`overheat` 等 key 位置与现有映射一一对应；`text-weak` 沿用现有弱色。）

- [ ] **Step 3: 误用净化**

- `OtcPricingClient.tsx:109`：`"bg-down/10 text-down border-down/20"` → `"bg-destructive/10 text-destructive border-destructive/20"`（knocked_out 是状态不是涨跌）。
- `CffexClient.tsx:594-604`（basis/premium 着色）：正 → `text-success`，负 → `text-destructive`（替换 text-down/text-up）。
- `CffexClient.tsx:717-722`（持仓占比低警示）：`text-down`→`text-warning`、`bg-down`→`bg-warning`；`text-up`→`text-muted-foreground`（正常值不着色强调）。实施时读 L700-750 上下文，若业务语义不同（如红=警示），按「警示=warning、正常=无强调」原则落地。
- DashboardClient 中 Task 12 的过渡 amber 类替换为 `border-warning/40 bg-warning/10 text-warning`。
- 全站 grep 复查：`grep -rn "text-up\|text-down\|bg-up\|bg-down" web/app web/components` —— 剩余命中必须全部是方向性涨跌场景（首页收益、dashboard 日收益/归因贡献、cffex 涨跌幅）。

- [ ] **Step 4: 验证**

```bash
cd web && npm run typecheck && npm run build
```
手测明暗两态：主按钮/选中态为 sky；涨跌绿红；象限四色；暗色对比自然。

---

### Task 16: chart-theme.ts 收敛图表硬编码

**Files:**
- Create: `web/lib/chart-theme.ts`
- Modify: `web/app/dashboard/DashboardClient.tsx`（~L76-77,246-251,1467-1468 等）、`web/app/cffex/CffexClient.tsx`（~L235-243）、`web/app/crypto/CryptoClient.tsx`（~L44-54,111）、`web/app/otc-derivatives-pricing/OtcPricingClient.tsx`（~L524,769）、`web/components/RiskMatrixSection.tsx`（~L121-123）、`web/components/ChartLightbox.tsx`（~L31）

- [ ] **Step 1: 创建 `web/lib/chart-theme.ts`**

```ts
/** 全站 ECharts 主题: 明暗两套, 收敛各页面硬编码。 */
export interface ChartTheme {
  text: string; subtext: string;
  axisLine: string; splitLine: string;
  tooltipBg: string; tooltipBorder: string;
  up: string; down: string;
  palette: string[];
  cffex: { IF: string; IH: string; IC: string; IM: string };
  crypto: { btc: string; sp500: string; nasdaq: string; gold: string; dxy: string };
  rdBu: string[]; // 相关性热力图发散色(蓝-白-红)
}

const light: ChartTheme = {
  text: "#171717", subtext: "#666666",
  axisLine: "rgba(0,0,0,0.15)", splitLine: "rgba(0,0,0,0.06)",
  tooltipBg: "#FFFFFF", tooltipBorder: "rgba(0,0,0,0.10)",
  up: "#16A34A", down: "#DC2626",
  palette: ["#0284C7", "#16A34A", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#DB2777", "#65A30D"],
  cffex: { IF: "#0284C7", IH: "#D97706", IC: "#DC2626", IM: "#16A34A" },
  crypto: { btc: "#D97706", sp500: "#0284C7", nasdaq: "#7C3AED", gold: "#B45309", dxy: "#0891B2" },
  rdBu: ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#F7F7F7", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"],
};

const dark: ChartTheme = {
  text: "#EDEDED", subtext: "#A1A1A1",
  axisLine: "rgba(255,255,255,0.15)", splitLine: "rgba(255,255,255,0.08)",
  tooltipBg: "#1C1C1E", tooltipBorder: "rgba(255,255,255,0.12)",
  up: "#4ADE80", down: "#F87171",
  palette: ["#38BDF8", "#4ADE80", "#FBBF24", "#F87171", "#A78BFA", "#22D3EE", "#F472B6", "#A3E635"],
  cffex: { IF: "#38BDF8", IH: "#FBBF24", IC: "#F87171", IM: "#4ADE80" },
  crypto: { btc: "#FBBF24", sp500: "#38BDF8", nasdaq: "#A78BFA", gold: "#F59E0B", dxy: "#22D3EE" },
  rdBu: ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#2A2A2A", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"],
};

export function getChartTheme(isDark: boolean): ChartTheme {
  return isDark ? dark : light;
}
```

- [ ] **Step 2: 六个消费方改造**（每文件同一步骤：`const theme = getChartTheme(isDark)`，随后逐一替换本地常量；替换后删除原 isDark 双份 hex 常量）：

| 文件 | 旧常量 → 新引用 |
|---|---|
| DashboardClient.tsx | textCol→theme.text；axis/splitLine/tooltip 同名→theme.*；`UP_COLOR`/`DOWN_COLOR`（L1467-1468）→`theme.up`/`theme.down`；所有硬编码 `#3B82F6`→theme.palette[0] |
| CffexClient.tsx | IF/IH/IC/IM 四色→theme.cffex.*；文字/轴线→theme.* |
| CryptoClient.tsx | gold/sp500/nasdaq/btc/dxy→theme.crypto.* |
| OtcPricingClient.tsx | 8 色分类 palette（L524,769）→theme.palette |
| RiskMatrixSection.tsx | RdBu 数组→theme.rdBu（保留发散语义） |
| ChartLightbox.tsx | 外壳 isDark 分支颜色→theme.tooltipBg/theme.text |

`HomeCryptoSection.tsx`（server 组件）保留 CSS 变量方案不动。

- [ ] **Step 3: 收敛验证**

```bash
grep -rn "#3B82F6\|#30A46C\|#E5484D" web/app web/components | grep -v node_modules
```
Expected: 零命中（或仅注释）。`cd web && npm run build` 通过。明暗手测四个图表页。

---

### Task 17: 全站排版/间距/响应式整改

**Files:** 全部页面与组件（下列为逐项清单，实施时逐条对照修改）

**总标准**（先读 `globals.css` Task 15 结果）：正文 `text-sm leading-6`；卡片 `p-5 sm:p-6`；区块间 `space-y-6`；页面容器 `max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8`；页面标题 `text-lg font-semibold tracking-tight`；表格 `text-sm`、数字 `font-mono tabular-nums`；按钮/输入高度统一 `h-9`（紧凑区 `h-8`）。

- [ ] **Step 1: Navbar**——链接间距 `gap-1`、`text-sm`、active 下划线/底色用 `bg-accent`；移动端菜单（若有折叠）可点开且不溢出；主题切换按钮 `h-8 w-8`。

- [ ] **Step 2: 首页 `/`**——hero 标题层级（`text-3xl sm:text-4xl font-semibold tracking-tight leading-tight`）；卡片栅格 `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`；crypto sparkline 卡窄屏不换行溢出；所有 `text-up/text-down` 场景已在 Task 15 生效。

- [ ] **Step 3: /dashboard**——左 TOC 列 `hidden lg:block w-44 shrink-0`（<1024px 隐藏，主列全宽）；顶部信息卡标题/徽章间距 `gap-2 flex-wrap`；方法切换条 `flex flex-wrap gap-2`；各图表卡 `min-w-0` 防 ECharts 撑破栅格；参数卡字段网格 `grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-x-6 gap-y-3`。

- [ ] **Step 4: /builder**——stepper 三步在窄屏纵排（`flex-col sm:flex-row`）；步骤标题 `text-lg font-semibold`；表单区字段间距统一 `space-y-4`；底部操作栏 `flex-wrap gap-2 py-3`；象限卡 `min-h` 移除或改 `min-h-[360px]` 移动端。

- [ ] **Step 5: /cffex、/crypto、/otc-*、/methodology**——表格容器 `overflow-x-auto` 保留 + 表头 `whitespace-nowrap`；长文页（methodology）`prose` 最大宽 `max-w-3xl`、`leading-7`；OTC 表单区 `grid-cols-1 lg:grid-cols-2 gap-6`；卡片内数字密度统一。

- [ ] **Step 6: /admin/\***——页头 `text-lg font-semibold` + 描述 `text-sm text-muted-foreground`；两表按 Task 14 已调；用户表 `min-w-[900px]` 保持 + 行高 `h-11`。

- [ ] **Step 7: 弹窗与表单原语**——`ui/dialog.tsx` 头部 `space-y-1.5`、body `text-sm`；`ui/input.tsx`/`select`/`switch` 高度与圆角一致（`h-9 rounded-md`）；所有 `window.alert` 残留（若有）清除。

- [ ] **Step 8: 逐页 375px 走查（肉眼）**——`npm run dev` 后浏览器 375px 依次过 10 路由：内容无截断、无横滚（表格容器除外）、按钮可点、文字不重叠。发现问题即改。

- [ ] **Step 9: 构建验证**

```bash
cd web && npm run typecheck && npm run build
```

---

### Task 18: 设计文档 + CLAUDE.md 设计节

**Files:**
- Create: `docs/design-system.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `docs/design-system.md`**——记录：色板（明/暗全 token 表，含 sky 主色、up=绿/down=红、success/warning）、排版标准（字号/行高/字重/数字等宽）、间距与容器标准、组件规范（卡片/按钮/表格/弹窗）、涨跌色使用规范（仅方向性）、图表主题用法（`getChartTheme`）、响应式断点约定。内容从 Task 15-17 的实际落地值摘录，不得写未实现的设想。

- [ ] **Step 2: CLAUDE.md**——前端节追加一行：「设计规范见 `docs/design-system.md`；主色 sky，绿涨红跌，图表色一律经 `web/lib/chart-theme.ts`」。

---

## Phase P4：数据与全量重算

### Task 19: 本地全量重算与数据验收

**Files:** 无新建（可能临时脚本 `scripts/recompute_all_local.py`）

- [ ] **Step 1: 启动新版后端与前端**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m uvicorn bp_api.main:app --host 127.0.0.1 --port 8000
cd D:/balanced-portfolio/web && npm run dev
```

- [ ] **Step 2: 触发强制重算**

优先走新端点（同时验收它）：管理员登录前端 → /admin/assets → 「强制重算全部组合」→ 确认。若登录不便，用 API：

```bash
# 登录取 token(路由路径以 grep "login" bp_api/main.py 为准)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"<管理员邮箱>\",\"password\":\"<密码>\"}" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST http://127.0.0.1:8000/api/admin/portfolios/recompute-all -H "Authorization: Bearer $TOKEN"
```
Expected: `{"enqueued":13}`。

- [ ] **Step 3: 轮询直至全部完成**

```bash
watch -n 30 'psql "host=100.75.138.35 dbname=postgres user=postgres" -c "SELECT status, count(*) FROM bp_portfolio GROUP BY 1;"'
```
Expected: 最终 `done | 13`，`running` 消失。inline 模式下顺序执行，预计 30~90 分钟；若某组合 `error`，`SELECT error FROM bp_portfolio WHERE status='error'` 定位修复后对该组合单独 `POST /api/portfolios/{id}/recompute`。

- [ ] **Step 4: 数据抽查**

```sql
-- 每组合应有最多 8 个基准(序列为空者自动缺省); 起点早于 2017 的组合缺三个 ETF 基准属正常
SELECT portfolio_id, count(DISTINCT benchmark_key) AS bench_cnt
FROM bp_backtest_benchmark GROUP BY 1 ORDER BY 1;

-- 新基准归因落库
SELECT count(*) FROM bp_backtest_attribution WHERE benchmark_key IN ('sp500_etf','ndx100_etf','n225_etf');

-- 快照全量
SELECT count(*) FROM bp_portfolio WHERE last_run_params IS NOT NULL;

-- 60/40 口径: 抽一个 bond6040 demo, benchmark 腿合成后与旧结果 NAV 不同(预期)
```

- [ ] **Step 5: 前端结果验收**

浏览器打开任一重算后的组合：基准下拉出现「标普500ETF / 纳斯达克100ETF / 日经225ETF」，切换后曲线/归因/构成说明正常；60/40 组合对比曲线为合成口径（不再是国债单腿）。

---

## Phase P5：审计闭环

### Task 20: Chrome 三视口×明暗逐页审计

**Files:** 视发现修复任意前端文件

- [ ] **Step 1: 审计矩阵**

路由：`/`、`/dashboard?id=<重算后组合>`、`/builder`、`/builder?id=<组合>`、`/cffex`、`/crypto`、`/otc-pricing`、`/otc-derivatives-pricing`、`/methodology`、`/admin/assets`、`/admin/users`（admin 需登录：用管理员账号，登录入口以实际页面为准）。
视口：375×812、768×1024、1440×900；主题：light、dark。

- [ ] **Step 2: 每格执行**（chrome-devtools MCP）

`new_page`/`navigate_page` → `resize_page` → `take_screenshot` → `list_console_messages`（error 必须为 0）→ `evaluate_script`：

```js
() => ({
  hOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  wideEls: [...document.querySelectorAll("*")].filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > window.innerWidth + 1 && !el.closest("[class*='overflow-x-auto']");
  }).map(el => el.tagName + "." + (typeof el.className === "string" ? el.className.slice(0, 60) : "")).slice(0, 10),
})
```
Expected: `hOverflow=false`、`wideEls=[]`。

- [ ] **Step 3: 交互抽检**——/builder：打开资产弹窗（验证宽度与操作）、走一次「仅保存」改名；/dashboard：切方法/基准、TOC 点击滚动 + 指针；/admin：建用户弹窗、表头按钮；暗色下全部重复一遍关键交互。

- [ ] **Step 4: 修复循环**——每个发现记录（路由/视口/主题/现象），修复后回到 Step 2 复测该行，直至全矩阵干净。

### Task 21: 最终门禁

- [ ] **Step 1: 全量检查**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests -q
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: 全绿。

- [ ] **Step 2: 验收清单**（逐项确认，任何一项不满足则回对应任务）：
  1. /builder 资产弹窗宽度正常、左列不挤；
  2. 步骤二标题「选择默认的优化方法」；
  3. 偏离带显示 2 位小数；
  4. 基准含标普500ETF/纳斯达克100ETF/日经225ETF，全部 13 组合重算完成且新基准可选；
  5. 编辑免重算保存可用、diff 弹窗列出变更（含印花税示例场景）、待重算标记正确；
  6. /admin/users 建用户可设资产编辑权限与组合上限（含无限），无限用户实际不受 3 个限制；
  7. /admin/assets 1440/1280px 操作列完整可见；
  8. 全站 sky 主色、绿涨红跌、明暗完整、三视口无畸变（Task 20 矩阵全绿）；
  9. TOC 指针手型 + 字号与页面匹配；
  10. 默认组合：管理员→第一个公共案例，普通用户→自有优先；
  11. 60/40 内部基准合成口径生效（legs 修复）；
  12. 死配置已删（`grep BP_RISK_FREE` 零命中）；
  13. `docs/design-system.md` 已产出；
  14. 未做任何 git 提交。

---

## 依赖关系图

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8        (P1, 严格串行: 测试互有依赖)
T9 → T10; T9 → T11 → T12; T9 → T13; T9 → T14  (P2, T10/T13 可并行)
T15 → T16 → T17 → T18                          (P3, 串行: token 先行)
(P1∧P2∧P3 完成) → T19 → T20 → T21             (P4/P5)
```

## Self-Review 记录

- 规格覆盖：第 1-10 条 → T10/T10/T10/T3+T19/T5+T11+T12/T6+T13/T14/T15-17/T12/T12；追加任务④ → T3；⑤ → T8；响应式/Chrome 审计 → T17/T20；验收（全量重算+前端无误）→ T19/T21。无遗漏。
- 占位符扫描：除两处「以实际代码为准」的适配说明（象限状态变量名、_enqueue_backtest 签名——均为执行时 2 分钟可验证的事实核对，非设计空白）外无 TBD。
- 类型一致性：`canonical_params`/`is_params_stale`/`read_def`/`diff_payload`/`update_portfolio_def_only`/`is_portfolio_stale`/`list_recomputable_portfolio_ids` 在定义任务与消费任务间名称一致；前端 `params_stale`/`recomputeAllPortfolios`/`createUser(opts)` 一致。

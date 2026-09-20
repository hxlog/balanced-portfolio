# Builder / 调仓 UI 三视口重构 + 调仓计算器功能补全 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Builder 三视口布局坍塌、资产弹窗手机端不可用、调仓 Badge 换行、调仓计算器布局与金额计算缺陷，并补全「最近交易日权重 / 当前持仓列 / 拟投资金额 / ETF 份额 / 交易费用」功能，最终以 Playwright 三视口实测验收后推送 GitHub。

**Architecture:** 后端先行动：`repositories_otc.latest_closes` 批量取清洗收盘价 + 公开端点 `/api/quotes/latest`。前端把计算器的金额算法抽成纯函数模块 `web/lib/rebalance-calc.ts`（新增 vitest 覆盖），组件只负责渲染与输入。UI 改造遵循 `docs/design-system.md`，复用既有原语（Card / Dialog / Tabs / Table / Badge / useIsMobile），不引入新的设计语言。

**Tech Stack:** Python 3.11+（本地 .venv py 3.14）/ FastAPI / psycopg3 / PostgreSQL 18 + TimescaleDB / Next.js 16 (Turbopack) / React 19 / Tailwind CSS v4 (CSS-first) / Radix UI / sonner / vitest（本次新增） / Playwright MCP。

## Global Constraints

- **本波全程不 git commit**（Task 1–24）：每个任务的检查点是「其自身测试/构建通过」，逐任务的 `提交` 步骤一律**跳过**，改动留在工作区。Task 25 做**唯一一次**提交并推送 GitHub（用户本轮明确要求同步）。因此 Task 25 Step 2 的 `git log origin/main..HEAD` 在提交前为空是**预期**的，以 `git status --short` 的文件清单为准。
- **每个任务的改动必须自证不破坏工程**：改了 Python → 跑 `python -m pytest bp_api/tests -q`；改了 `web/` → 跑 `cd web && npm run typecheck`；改了 `web/` 的 `.tsx`/样式 → 再跑 `npm run build`。整套三条在 Task 23 统一再跑一遍（含 `npm test`）。
- **跨 variant 的 tailwind 类不去重**：覆盖基座 `sm:max-w-lg` 必须传 `sm:max-w-*`；传无前缀的 `max-w-*` 会两者并存且 `sm:` 版本在编译产物中更靠后从而胜出（`docs/superpowers/plans/2026-09-03-*.md:860-899` 已记录）。
- **涨跌色口径**：`text-up`/`text-down` 仅限方向性涨跌；仓位动作/状态用 `success`/`warning`/`destructive`。
- **`text-[10px]` 禁用**：Tailwind v4 的任意字号只输出 `font-size`、不输出 `line-height`，会继承 20px 行盒。辅助字号一律 `text-xs`。
- **弹窗宽度**：`w-[calc(100vw-2rem)]` 兜底 + `sm:max-w-*`；高度 `max-h-[85vh]` + `flex flex-col` + 滚动区 `flex-1 min-h-0`。
- **手机断点** = `useIsMobile()`（`web/components/ui/use-mobile.ts`，768px，`< 768` 为手机）。
- **后端**：`with db.get_conn() as conn:` 取连接，**必须显式 `conn.commit()`**；SQL 参数化，禁止 f-string 拼接用户输入。
- **Task 25 提交前必跑（Task 1–24 期间无需跑整套）**：`python -m pytest bp_api/tests -q`、`cd web && npm run typecheck && npm run build`。
- 本地服务：Next.js `:3000`、FastAPI `:8000`。浏览器验收需注入 `bp_session` cookie（见 Task 2 Step 4）。
- 规格文件：`docs/superpowers/specs/2026-09-20-builder-ui-revamp-design.md`（冲突时以规格为准）。

---

## 文件结构

**新建**
| 文件 | 职责 |
|---|---|
| `web/lib/rebalance-calc.ts` | 计算器全部纯金额算法（无 React、无 IO） |
| `web/lib/rebalance-calc.test.ts` | 上述算法的单元测试 |
| `web/vitest.config.ts` | vitest 配置（node 环境，仅覆盖 `lib/`） |

**修改（后端）**
| 文件 | 改动 |
|---|---|
| `bp_api/repositories_otc.py` | 新增 `latest_closes()` |
| `bp_api/otc_api.py` | 新增 `GET /api/quotes/latest` |
| `bp_api/tests/test_otc_pricing.py` | 新增 `latest_closes` 与端点测试 |

**修改（前端）**
| 文件 | 改动 |
|---|---|
| `web/lib/api.ts` | 新增 `quotesLatest()` 客户端方法与类型 |
| `web/components/ui/badge.tsx` | 基类加 `whitespace-nowrap` |
| `web/components/RebalanceCalculatorDialog.tsx` | 全量重写（布局 + 新列 + 费用卡 + 份额） |
| `web/app/dashboard/DashboardClient.tsx` | 日期下拉加「最近交易日」档、传参、Badge 四态、表格宽度、费用摘要 |
| `web/app/builder/BuilderClient.tsx` | 步骤条、三区内容、资产弹窗、推荐侧栏、新建态重置 |

**修改（工程）**
| 文件 | 改动 |
|---|---|
| `web/package.json` | 新增 `test` 脚本与 vitest 依赖 |
| `.github/workflows/ci.yml` | 新增前端单测步骤 |

---

## Phase P0：基线与测试基建

### Task 1: 基线验证

**Files:** 无（验证环境）

**Interfaces:**
- Consumes: 无
- Produces: 基线用例数（后续任务对比）

- [ ] **Step 1: 后端测试基线**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全部通过。**记下用例数**（当前为 195），后续每个任务结束对比。

- [ ] **Step 2: 前端基线**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: 两者 exit 0。

- [ ] **Step 3: 启动本地服务**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m uvicorn bp_api.main:app --host 127.0.0.1 --port 8000
cd D:/balanced-portfolio/web && npm run dev
```
Expected: `:8000` 与 `:3000` 均可访问。

---

### Task 2: 引入 vitest（前端首个测试框架）

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 无
- Produces: `npm test` 可用；后续所有前端纯函数任务用 `import { describe, it, expect } from "vitest"`

- [ ] **Step 1: 安装 vitest**

```bash
cd D:/balanced-portfolio/web && npm install -D vitest@^3 --legacy-peer-deps
```
Expected: 写入 `devDependencies`，无 peer 冲突报错。

- [ ] **Step 2: 加 test 脚本**

修改 `web/package.json` 的 `scripts`（保留其余三项不动）：

```json
  "scripts": {
    "dev": "next dev --turbopack -p 3000",
    "build": "next build --turbopack",
    "start": "next start -p 3000",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  },
```

- [ ] **Step 3: 写 vitest 配置**

创建 `web/vitest.config.ts`：

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
```

> 只覆盖 `lib/` 下的纯函数：组件测试交给 Playwright 三视口验收（Task 24），
> 不引入 jsdom / testing-library，避免不必要的依赖面。

- [ ] **Step 4: 冒烟测试**

创建 `web/lib/rebalance-calc.test.ts`（本任务只放一个占位断言，**Task 5** 会整体替换成真实用例）：

```ts
import { describe, expect, it } from "vitest";

describe("vitest 基建", () => {
  it("能运行 TypeScript 断言", () => {
    expect(1 + 1).toBe(2);
  });
});
```

运行：
```bash
cd D:/balanced-portfolio/web && npm test
```
Expected: `1 passed`。

- [ ] **Step 5: CI 增加前端单测步骤**

修改 `.github/workflows/ci.yml`，在既有的 `npm run build` 步骤**之前**插入：

```yaml
      - name: 前端单元测试
        run: npm test
        working-directory: web
```
（沿用该文件既有的 `working-directory` 风格；若该文件用的是 `cd web && ...`，则写 `run: cd web && npm test`。）

- [ ] **Step 6: 提交**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/lib/rebalance-calc.test.ts .github/workflows/ci.yml
git commit -m "test(web): 引入 vitest 并接入 CI"
```

---

## Phase P1：后端批量取价

### Task 3: `repositories_otc.latest_closes`

**Files:**
- Modify: `bp_api/repositories_otc.py`（在 `spot_on_date` 之后追加）
- Test: `bp_api/tests/test_otc_pricing.py`

**Interfaces:**
- Consumes: 表 `bp_quote_clean(symbol, source, trade_date, close)`
- Produces: `latest_closes(conn, keys: list[tuple[str, str]], on_date: date | None = None) -> list[dict | None]`
  - 返回**与 `keys` 等长、顺序一致**的列表，元素为 `{"symbol": str, "source": str, "date": "YYYY-MM-DD", "close": float}` 或 `None`（该标的无数据）

- [ ] **Step 1: 写失败测试**

在 `bp_api/tests/test_otc_pricing.py` 末尾追加：

```python
def test_latest_closes_batch_and_order(monkeypatch):
    """批量取价: 顺序与入参一致, 缺失项为 None, on_date 生效。"""
    from datetime import date as d

    import bp_api.repositories_otc as rotc

    rows = [
        ("000300", "cn_index_em", d(2026, 9, 17), 4000.5),
        ("000300", "cn_index_em", d(2026, 9, 18), 4010.25),
        ("510300", "etf_em", d(2026, 9, 18), 4.1234),
    ]

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, q, params):
            # on_date 存在时 SQL 会多一个参数
            assert "DISTINCT ON" in q
            assert "bp_quote_clean" in q

        def fetchall(self):
            return rows

    class _Conn:
        def cursor(self):
            return _Cur()

    out = rotc.latest_closes(
        _Conn(),
        [("510300", "etf_em"), ("MISSING", "etf_em"), ("000300", "cn_index_em")],
    )
    assert [x and x["symbol"] for x in out] == ["510300", None, "000300"]
    assert out[0]["close"] == 4.1234
    assert out[0]["date"] == "2026-09-18"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests/test_otc_pricing.py::test_latest_closes_batch_and_order -q
```
Expected: FAIL — `AttributeError: module 'bp_api.repositories_otc' has no attribute 'latest_closes'`。

- [ ] **Step 3: 实现**

在 `bp_api/repositories_otc.py` 的 `spot_on_date` 函数之后追加：

```python
def latest_closes(
    conn: psycopg.Connection,
    keys: list[tuple[str, str]],
    on_date: Optional[date] = None,
) -> list[Optional[dict]]:
    """批量取 (symbol, source) 在 on_date(含)之前最近交易日的清洗收盘价。

    返回与 `keys` **等长且顺序一致**的列表, 缺失项为 None —— 调用方可直接按位对应。
    单条 SQL: VALUES 列表 JOIN bp_quote_clean + DISTINCT ON 取每标的最新一行,
    避免 N 次往返。
    """
    if not keys:
        return []

    pairs = sorted({(s, src) for s, src in keys if s and src})
    if not pairs:
        return [None] * len(keys)

    placeholders = ", ".join(["(%s, %s)"] * len(pairs))
    params: list = []
    for s, src in pairs:
        params.extend([s, src])

    q = (
        "SELECT DISTINCT ON (q.symbol, q.source) "
        "q.symbol, q.source, q.trade_date, q.close "
        "FROM bp_quote_clean q "
        f"JOIN (VALUES {placeholders}) AS k(symbol, source) "
        "  ON k.symbol = q.symbol AND k.source = q.source "
    )
    if on_date is not None:
        q += "WHERE q.trade_date <= %s "
        params.append(on_date)
    q += "ORDER BY q.symbol, q.source, q.trade_date DESC"

    with conn.cursor() as cur:
        cur.execute(q, tuple(params))
        rows = cur.fetchall()

    found: dict[tuple[str, str], dict] = {}
    for r in rows:
        found[(r[0], r[1])] = {
            "symbol": r[0],
            "source": r[1],
            "date": r[2].isoformat(),
            "close": round(float(r[3]), 4),
        }
    return [found.get((s, src)) for s, src in keys]
```

> `DISTINCT ON` 要求 `ORDER BY` 以其表达式开头 —— 已满足。`ON` 子句里的
> `k.symbol = q.symbol` 用的是每组恰好两列的 VALUES 表，故不入 SQL 注入面。

- [ ] **Step 4: 运行确认通过**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests/test_otc_pricing.py -q
```
Expected: PASS。

- [ ] **Step 5: 真实数据库验证（一次性，不入库到测试）**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -c "
import os
from pathlib import Path
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('\"'))
import psycopg
from bp_api import repositories_otc as rotc
# 不要写死主机: 用 os.environ['PGHOST'](本机实测 81.71.158.239; 100.75.138.35 是已失效的旧 Tailscale 地址)
with psycopg.connect(host=os.environ['PGHOST'], port=5432, dbname='postgres', user='postgres') as c:
    print(rotc.latest_closes(c, [('510300','etf_em'), ('159920','etf_em'), ('NOPE','etf_em')]))
"
```
Expected: 前两项有 `close`，第三项 `None`。

- [ ] **Step 6: 提交**

```bash
git add bp_api/repositories_otc.py bp_api/tests/test_otc_pricing.py
git commit -m "feat(otc): 新增批量最新清洗收盘价查询 latest_closes"
```

---

### Task 4: `GET /api/quotes/latest` 端点 + 前端客户端

**Files:**
- Modify: `bp_api/otc_api.py`（在 `otc_spot` 之后；`register_routes` 内）
- Modify: `bp_api/tests/test_otc_pricing.py`
- Modify: `web/lib/api.ts`

**Interfaces:**
- Consumes: `rotc.latest_closes`（Task 3）
- Produces:
  - HTTP `GET /api/quotes/latest?keys=symbol@source,symbol@source[&date=YYYY-MM-DD]`
    → `{"date": "YYYY-MM-DD" | null, "quotes": [{"symbol","source","date","close"} | null, ...]}`
      （顶层 `date` 是本次批量查询的代表日，供 UI 显示「按 YYYY-MM-DD 收盘价折算」；
      逐条的 `date` 才是该标的自己的交易日，两者可能不同——插值/停牌标的会滞后）
  - TS `api.quotesLatest(keys: string[], onDate?: string): Promise<{ date: string | null; quotes: Array<{symbol:string;source:string;date:string;close:number} | null> }>`

- [ ] **Step 1: 写失败测试**

在 `bp_api/tests/test_otc_pricing.py` 末尾追加：

```python
def test_quotes_latest_endpoint_parses_and_rejects(monkeypatch):
    """端点: 合法 keys 返回 quotes; 非法格式 400; date 非法 400; 上限 64。

    注意: 本仓库**不通过 TestClient 测路由** —— starlette 1.3 的 TestClient 需要
    httpx2 包(未在 requirements.txt 里), 且它会在导入期构造 app 并触碰连接池。
    既有测试一律直接取路由的 endpoint 函数调用(见 bp_api/tests/ 其他用例的风格),
    这样既不引入新依赖, 也不需要真库 —— `db.get_conn` 由 monkeypatch 打桩。
    """
    from datetime import date

    from fastapi import HTTPException

    import bp_api.otc_api as otc_api
    from bp_api import main

    routes = {getattr(r, "path", None): r for r in main.app.routes}
    handler = routes["/api/quotes/latest"].endpoint

    with pytest.raises(HTTPException) as bad:
        handler(keys="510300")
    assert bad.value.status_code == 400
    assert "symbol@source" in bad.value.detail

    with pytest.raises(HTTPException) as bad_date:
        handler(keys="510300@etf_em", date_str="2026/09/18")
    assert bad_date.value.status_code == 400

    with pytest.raises(HTTPException) as empty:
        handler(keys=" , ")
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as too_many:
        handler(keys=",".join(f"S{i}@etf_em" for i in range(65)))
    assert too_many.value.status_code == 400
    assert "64" in too_many.value.detail

    # 成功路径: 打桩 db.get_conn 与 latest_closes, 断言解析后的 keys 顺序与 date 透传,
    # 且响应同时带顶层 date 与逐条 quotes。
    seen: dict = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_conn(*a, **k):
        return _Conn()

    def _fake_closes(conn, keys, on_date=None):
        seen["keys"] = keys
        seen["on_date"] = on_date
        return [
            {"symbol": s, "source": src, "date": "2026-09-18", "close": 4.1234}
            for s, src in keys
        ]

    monkeypatch.setattr(otc_api.db, "get_conn", _fake_conn)
    monkeypatch.setattr(otc_api.rotc, "latest_closes", _fake_closes)

    body = handler(keys=" 510300@etf_em , 000300@cn_index_em ", date_str="2026-09-18")
    assert seen["keys"] == [("510300", "etf_em"), ("000300", "cn_index_em")]
    assert seen["on_date"] == date(2026, 9, 18)
    assert body["date"] == "2026-09-18"
    assert [qq and qq["symbol"] for qq in body["quotes"]] == ["510300", "000300"]
```

- [ ] **Step 2: 运行确认失败**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests/test_otc_pricing.py::test_quotes_latest_endpoint_parses_and_rejects -q
```
Expected: FAIL — `KeyError: '/api/quotes/latest'`（该键不在 `main.app.routes` 里，因为路由还没写）。
（注意：不是 404 —— 本仓测试直接取 endpoint 函数，不经过 ASGI 路由匹配，详见 Step 1 的说明。）

- [ ] **Step 3: 实现端点**

在 `bp_api/otc_api.py` 的 `otc_spot` 函数之后插入。同时在文件顶部常量区加
`MAX_QUOTE_KEYS = 64`（放在 `logger = logging.getLogger(__name__)` 下方）：

```python
MAX_QUOTE_KEYS = 64
```

```python
    @app.get("/api/quotes/latest")
    def quotes_latest(
        keys: str = Query(..., description="symbol@source, 逗号分隔, 最多 64 个"),
        date_str: str | None = Query(None, alias="date"),   # 与 otc_spot 同风格
    ) -> dict:
        """批量最新清洗收盘价(CNY 口径, 与回测/换算金额同币种)。

        供前端调仓计算器把买卖金额换算成 ETF 份额使用。公开端点, 与 /api/otc/spot 同级。
        """
        on_date = None
        if date_str:
            try:
                on_date = date.fromisoformat(date_str)
            except ValueError as exc:
                raise HTTPException(400, "date 须为 YYYY-MM-DD") from exc

        parsed: list[tuple[str, str]] = []
        for part in keys.split(","):
            part = part.strip()
            if not part:
                continue
            sym, sep, src = part.rpartition("@")
            if not sep or not sym or not src:
                raise HTTPException(400, f"keys 须为 symbol@source 形式: {part}")
            parsed.append((sym, src))
        if not parsed:
            raise HTTPException(400, "keys 不能为空")
        if len(parsed) > MAX_QUOTE_KEYS:
            raise HTTPException(400, f"一次最多查询 {MAX_QUOTE_KEYS} 个标的")

        with db.get_conn() as conn:
            rows = rotc.latest_closes(conn, parsed, on_date=on_date)
        return {"date": rows[0]["date"] if rows and rows[0] else None, "quotes": rows}
```

- [ ] **Step 4: 运行确认通过**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests/test_otc_pricing.py -q
```
Expected: PASS。

- [ ] **Step 5: 前端客户端方法**

在 `web/lib/api.ts` 中，`otcSpot` 条目之后插入（沿用该对象已有的 `req` 与 `q` 用法）：

```ts
  quotesLatest: (keys: string[], onDate?: string) =>
    req<{
      date: string | null;
      quotes: Array<{ symbol: string; source: string; date: string; close: number } | null>;
    }>(`/api/quotes/latest${q({ keys: keys.join(","), date: onDate })}`),
```

- [ ] **Step 6: 类型检查**

```bash
cd D:/balanced-portfolio/web && npm run typecheck
```
Expected: exit 0。

- [ ] **Step 7: 提交**

```bash
git add bp_api/otc_api.py bp_api/tests/test_otc_pricing.py web/lib/api.ts
git commit -m "feat(api): 新增 GET /api/quotes/latest 批量取价端点"
```

---

## Phase P2：计算器金额算法（纯函数 + 单测）

### Task 5: 行模型与默认「当前持仓」

**Files:**
- Create: `web/lib/rebalance-calc.ts`
- Modify: `web/lib/rebalance-calc.test.ts`（替换 Task 2 的占位）

**Interfaces:**
- Produces:
  - `type CalcRow = { key; name; symbol; source; category?; targetWeight; prevWeight? }`
  - `LOT_SIZE = 100`
  - `defaultCurrentByPrev(rows: CalcRow[], amount: number): Record<string, number>`
    —— 按 `prevWeight × amount` 反推当前持仓（历史调仓日口径）

- [ ] **Step 1: 写失败测试**

用以下内容**整体替换** `web/lib/rebalance-calc.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { defaultCurrentByPrev, type CalcRow } from "./rebalance-calc";

const rows: CalcRow[] = [
  { key: "A@x", name: "甲", symbol: "A", source: "x", category: "index", targetWeight: 0.5, prevWeight: 0.6 },
  { key: "B@x", name: "乙", symbol: "B", source: "x", category: "etf", targetWeight: 0.3, prevWeight: 0.4 },
  { key: "C@x", name: "丙", symbol: "C", source: "x", category: "etf", targetWeight: 0.2, prevWeight: 0 },
];

describe("defaultCurrentByPrev", () => {
  it("按上期权重 × 拟投资金额反推当前持仓", () => {
    const got = defaultCurrentByPrev(rows, 1_000_000);
    expect(got["A@x"]).toBe(600_000);
    expect(got["B@x"]).toBe(400_000);
    expect(got["C@x"]).toBe(0);
  });

  it("prevWeight 缺失时视为 0（新建仓行当前持仓为 0）", () => {
    const noPrev: CalcRow[] = [
      { key: "N@x", name: "新", symbol: "N", source: "x", targetWeight: 1, prevWeight: null },
    ];
    expect(defaultCurrentByPrev(noPrev, 1_000_000)["N@x"]).toBe(0);
  });

  it("金额非法时全部为 0", () => {
    const got = defaultCurrentByPrev(rows, Number.NaN);
    expect(Object.values(got).every((v) => v === 0)).toBe(true);
  });
});
```

- [ ] **Step 2: 运行确认失败**

```bash
cd D:/balanced-portfolio/web && npm test
```
Expected: FAIL — 无法解析 `./rebalance-calc`。

- [ ] **Step 3: 实现**

创建 `web/lib/rebalance-calc.ts`：

```ts
/**
 * 调仓计算器的全部金额算法。
 *
 * 设计: 纯函数、无 React、无 IO —— 便于单测, 且方便在浏览器本地计算时保持
 * 「金额不上传」的隐私承诺(只有标的代码会进请求)。
 *
 * 口径(与后端 backtest.py 的交易成本模型同源):
 *   计划持仓 = 最优权重 × 拟投资金额
 *   买入 = max(0, 计划 − 当前),  卖出 = max(0, 当前 − 计划)
 *   佣金/滑点 = (Σ买 + Σ卖) × 费率,  印花税 = Σ卖 × 费率
 */

/** 场内 ETF 最小交易单位(份)。 */
export const LOT_SIZE = 100;

export type CalcRow = {
  key: string;
  name: string;
  symbol: string;
  source: string;
  /** bp_index_config.category: index/etf/commodity/bond/crypto/forex */
  category?: string;
  /** 目标权重(小数 0~1) */
  targetWeight: number;
  /** 上期权重(小数); null/undefined 表示上期无此标的 */
  prevWeight?: number | null;
};

function safeAmount(amount: number): number {
  return Number.isFinite(amount) && amount > 0 ? amount : 0;
}

/**
 * 历史调仓日的「当前持仓」默认值 = 上期权重 × 拟投资金额。
 *
 * 用上期权重而非 actual_holdings: 对任意历史调仓日恒可算(actual_holdings 只对
 * 数据截止日有意义), 且清仓行会自动得到「上期权重 × 金额」的全额卖出基数。
 */
export function defaultCurrentByPrev(
  rows: CalcRow[],
  amount: number,
): Record<string, number> {
  const base = safeAmount(amount);
  const out: Record<string, number> = {};
  for (const r of rows) {
    const w = Number.isFinite(r.prevWeight as number) ? (r.prevWeight as number) : 0;
    out[r.key] = Math.round(Math.max(0, w) * base);
  }
  return out;
}
```

- [ ] **Step 4: 运行确认通过**

```bash
cd D:/balanced-portfolio/web && npm test
```
Expected: `3 passed`（`defaultCurrentByPrev` 三个用例）。

- [ ] **Step 5: 提交**

```bash
git add web/lib/rebalance-calc.ts web/lib/rebalance-calc.test.ts
git commit -m "feat(calc): 提取调仓金额算法模块, 新增当前持仓默认值"
```

---

### Task 6: 计划持仓、买入卖出、份额取整、交易费用

**Files:**
- Modify: `web/lib/rebalance-calc.ts`
- Modify: `web/lib/rebalance-calc.test.ts`

**Interfaces:**
- Consumes: `CalcRow`、`LOT_SIZE`（Task 5）
- Produces:
  - `targetAmounts(rows, amount): Record<string, number>` —— 最后一行吸收舍入残差使 `Σ === round(amount)`
  - `computeLines(rows, current: Record<string, number>, target: Record<string, number>): CalcLine[]`
  - `applyShares(lines, rows, priceByKey: Record<string, number>): CalcLine[]`
  - `computeTotals(lines): { buyTotal: number; sellTotal: number; turnover: number; remainder: number }`
  - `computeFees(buyTotal, sellTotal, rates: Rates): { commission; slippage; stampDuty; total }`
  - `type CalcLine = { key; targetWeight; currentAmount; targetAmount; buy; sell; buyShares: number|null; sellShares: number|null; buyRemainder; sellRemainder }`
  - `type Rates = { feeRate: number; slippageRate: number; stampDutyRate: number }`

- [ ] **Step 0: 收口 Task 5 审查的两项 Minor（同一文件，顺手做掉）**

(a) `web/lib/rebalance-calc.ts` 里 `defaultCurrentByPrev` 的 JSDoc 末句宣称
「清仓行会自动得到『上期权重 × 金额』的全额卖出基数」，但本函数 `prevWeight=0` 时返回
`current=0`，与新建仓**不可区分**——它并不产生那个基数（全我卖出基数要由 Task 12 传
`actual_holdings` 才成立）。把该句改成准确表述：

```ts
 * 用上期权重而非 actual_holdings: 对任意历史调仓日恒可算(actual_holdings 只对
 * 数据截止日有意义)。
 *
 * 注意: prevWeight=0 与「无上期持仓」都返回 0, 两者不可区分 —— 本函数只提供
 * 「历史调仓日的当前持仓」默认值; 「最近交易日」口径的当前持仓由调用方传入
 * actual_holdings 覆盖(见 Dashboard 的 currentByKey)。
```

(b) `web/lib/rebalance-calc.test.ts` 的「金额非法时全部为 0」断言
`Object.values(got).every((v) => v === 0)` 对 `{}` 恒真，判别力不足。替换为：

```ts
  it("金额非法时全部为 0", () => {
    const got = defaultCurrentByPrev(rows, Number.NaN);
    expect(Object.keys(got).sort()).toEqual(["A@x", "B@x", "C@x"]);
    expect(Object.values(got)).toEqual([0, 0, 0]);
  });
```

- [ ] **Step 1: 写失败测试**

在 `web/lib/rebalance-calc.test.ts` 的 import 里补齐新符号，并在文件末尾追加：

```ts
import {
  applyShares,
  computeFees,
  computeLines,
  computeTotals,
  targetAmounts,
} from "./rebalance-calc";

describe("targetAmounts", () => {
  it("最后一行吸收舍入残差, Σ 严格等于拟投资金额", () => {
    const uneven: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 1 / 3 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 1 / 3 },
      { key: "C", name: "丙", symbol: "C", source: "x", targetWeight: 1 / 3 },
    ];
    const got = targetAmounts(uneven, 1_000_000);
    const sum = got.A + got.B + got.C;
    expect(sum).toBe(1_000_000);
  });

  it("空行集返回空对象", () => {
    expect(targetAmounts([], 1_000_000)).toEqual({});
  });
});

describe("computeLines", () => {
  it("清仓行(计划 0)算出全额卖出 —— 修复原本永远显示 '—' 的缺陷", () => {
    const closeRows: CalcRow[] = [
      { key: "C@x", name: "丙", symbol: "C", source: "x", targetWeight: 0 },
    ];
    const lines = computeLines(closeRows, { "C@x": 59_300 }, { "C@x": 0 });
    expect(lines[0].sell).toBe(59_300);
    expect(lines[0].buy).toBe(0);
  });

  it("减仓行只算卖出, 加仓行只算买入", () => {
    const r: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.5 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 0.5 },
    ];
    const lines = computeLines(r, { A: 400_000, B: 700_000 }, { A: 500_000, B: 500_000 });
    expect([lines[0].buy, lines[0].sell]).toEqual([100_000, 0]);
    expect([lines[1].buy, lines[1].sell]).toEqual([0, 200_000]);
  });

  it("0 是合法金额(不再被当作未填)", () => {
    const r: CalcRow[] = [{ key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 1 }];
    const lines = computeLines(r, { A: 0 }, { A: 1_000_000 });
    expect(lines[0].buy).toBe(1_000_000);
  });
});

describe("applyShares", () => {
  it("仅 ETF 换算份额, 且按 100 份向下取整, 零头单列", () => {
    const r: CalcRow[] = [
      { key: "E@x", name: "ETF", symbol: "E", source: "x", category: "etf", targetWeight: 1 },
      { key: "I@x", name: "指数", symbol: "I", source: "x", category: "index", targetWeight: 0 },
    ];
    const lines = computeLines(r, { "E@x": 0, "I@x": 0 }, { "E@x": 50_000, "I@x": 0 });
    const out = applyShares(lines, r, { "E@x": 4.12, "I@x": 4000 });
    // 50000 / 4.12 = 12135.9 份 → 12100 份
    expect(out[0].buyShares).toBe(12_100);
    expect(out[0].buyRemainder).toBeCloseTo(50_000 - 12_100 * 4.12, 6);
    // 非 ETF 不换算
    expect(out[1].buyShares).toBeNull();
  });

  it("无价格时不换算, 不报错", () => {
    const r: CalcRow[] = [
      { key: "E@x", name: "ETF", symbol: "E", source: "x", category: "etf", targetWeight: 1 },
    ];
    const lines = computeLines(r, { "E@x": 0 }, { "E@x": 10_000 });
    const out = applyShares(lines, r, {});
    expect(out[0].buyShares).toBeNull();
    expect(out[0].buy).toBe(10_000);
  });
});

describe("computeTotals / computeFees", () => {
  it("总额与费用与手工计算一致", () => {
    const r: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.5 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 0.5 },
    ];
    const lines = computeLines(r, { A: 400_000, B: 700_000 }, { A: 500_000, B: 500_000 });
    const t = computeTotals(lines);
    expect(t.buyTotal).toBe(100_000);
    expect(t.sellTotal).toBe(200_000);
    expect(t.turnover).toBe(300_000);

    const f = computeFees(t.buyTotal, t.sellTotal, {
      feeRate: 0.00015,
      slippageRate: 0.00015,
      stampDutyRate: 0.0005,
    });
    expect(f.commission).toBeCloseTo(45, 6); // 300000 × 0.00015
    expect(f.slippage).toBeCloseTo(45, 6);
    expect(f.stampDuty).toBeCloseTo(100, 6); // 200000 × 0.0005
    expect(f.total).toBeCloseTo(190, 6);
  });
});
```

- [ ] **Step 2: 运行确认失败**

```bash
cd D:/balanced-portfolio/web && npm test
```
Expected: FAIL — 导出符号不存在。

- [ ] **Step 3: 实现**

在 `web/lib/rebalance-calc.ts` 末尾追加：

```ts
export type CalcLine = {
  key: string;
  targetWeight: number;
  /** 当前持仓金额(元) */
  currentAmount: number;
  /** 计划持仓金额(元) = 权重 × 拟投资金额 */
  targetAmount: number;
  buy: number;
  sell: number;
  /** ETF 取整后可成交份额(100 的整数倍); 非 ETF 或无价格时为 null */
  buyShares: number | null;
  sellShares: number | null;
  /** 取整后未成交的零头(元); 非 ETF 为 0 */
  buyRemainder: number;
  sellRemainder: number;
};

export type Rates = {
  feeRate: number;
  slippageRate: number;
  stampDutyRate: number;
};

/**
 * 计划持仓金额 = 权重 × 拟投资金额。
 *
 * 逐行四舍五入会让各行之和偏离拟投资金额(后端权重按 6 位小数落库, 往往
 * Σ权重 = 0.999999), 故把残差补到最后一行, 使 Σ 严格等于取整后的拟投资金额 ——
 * 否则「完全按目标权重填」反而会凭空多出一笔调仓额。
 */
export function targetAmounts(rows: CalcRow[], amount: number): Record<string, number> {
  const base = Math.round(safeAmount(amount));
  const out: Record<string, number> = {};
  if (rows.length === 0) return out;
  let acc = 0;
  rows.forEach((r, i) => {
    const v =
      i === rows.length - 1
        ? Math.max(0, base - acc)
        : Math.round(Math.max(0, r.targetWeight) * base);
    out[r.key] = v;
    acc += v;
  });
  return out;
}

/** 逐行算出买入/卖出金额。`0` 是合法金额。 */
export function computeLines(
  rows: CalcRow[],
  current: Record<string, number>,
  target: Record<string, number>,
): CalcLine[] {
  return rows.map((r) => {
    const cur = Number.isFinite(current[r.key]) ? current[r.key] : 0;
    const tgt = Number.isFinite(target[r.key]) ? target[r.key] : 0;
    const diff = tgt - cur;
    return {
      key: r.key,
      targetWeight: r.targetWeight,
      currentAmount: cur,
      targetAmount: tgt,
      buy: diff > 0 ? diff : 0,
      sell: diff < 0 ? -diff : 0,
      buyShares: null,
      sellShares: null,
      buyRemainder: 0,
      sellRemainder: 0,
    };
  });
}

/** 按 100 份/手向下取整, 返回可成交份额、对应金额与未成交零头。 */
export function lotRound(
  amount: number,
  price: number,
): { shares: number; cash: number; remainder: number } {
  if (!Number.isFinite(amount) || amount <= 0) {
    return { shares: 0, cash: 0, remainder: 0 };
  }
  if (!Number.isFinite(price) || price <= 0) {
    return { shares: 0, cash: 0, remainder: amount };
  }
  // +1e-9 抵御浮点误差: amount 恰为整手金额时 floor 不应少算一手
  const lots = Math.floor(amount / (price * LOT_SIZE) + 1e-9);
  const shares = lots * LOT_SIZE;
  const cash = shares * price;
  return { shares, cash, remainder: amount - cash };
}

/**
 * 仅对场内 ETF 换算份额(指数/商品/债券无「份额」概念); 无价格时原样返回,
 * 调用方据此隐藏份额列。
 */
export function applyShares(
  lines: CalcLine[],
  rows: CalcRow[],
  priceByKey: Record<string, number>,
): CalcLine[] {
  const byKey = new Map(rows.map((r) => [r.key, r]));
  return lines.map((l) => {
    const r = byKey.get(l.key);
    const px = priceByKey[l.key];
    if (!r || r.category !== "etf" || !Number.isFinite(px) || px <= 0) return l;
    const b = lotRound(l.buy, px);
    const s = lotRound(l.sell, px);
    return {
      ...l,
      buyShares: b.shares,
      sellShares: s.shares,
      buyRemainder: b.remainder,
      sellRemainder: s.remainder,
    };
  });
}

export function computeTotals(lines: CalcLine[]): {
  buyTotal: number;
  sellTotal: number;
  turnover: number;
  remainder: number;
} {
  let buyTotal = 0;
  let sellTotal = 0;
  let remainder = 0;
  for (const l of lines) {
    buyTotal += l.buy;
    sellTotal += l.sell;
    remainder += l.buyRemainder + l.sellRemainder;
  }
  return { buyTotal, sellTotal, turnover: buyTotal + sellTotal, remainder };
}

/**
 * 交易费用。与后端 backtest.py 同口径:
 *   cost = turnover × (佣金 + 滑点) + sell_turnover × 印花税
 * 费率来自组合自身参数(portfolio.fee_rate / slippage_rate / stamp_duty_rate)。
 */
export function computeFees(
  buyTotal: number,
  sellTotal: number,
  rates: Rates,
): { commission: number; slippage: number; stampDuty: number; total: number } {
  const turnover = (Number.isFinite(buyTotal) ? buyTotal : 0) + (Number.isFinite(sellTotal) ? sellTotal : 0);
  const sell = Number.isFinite(sellTotal) ? sellTotal : 0;
  const commission = turnover * (rates.feeRate || 0);
  const slippage = turnover * (rates.slippageRate || 0);
  const stampDuty = sell * (rates.stampDutyRate || 0);
  return { commission, slippage, stampDuty, total: commission + slippage + stampDuty };
}
```

- [ ] **Step 4: 运行确认通过**

```bash
cd D:/balanced-portfolio/web && npm test
```
Expected: 全部 PASS（`defaultCurrentByPrev` 3 + `targetAmounts` 2 + `computeLines` 3 + `applyShares` 2 + `computeTotals/computeFees` 1 = 11）。
（若你**只**跑了 Step 1 的新测试而没做 Step 0，`defaultCurrentByPrev` 的第 3 个用例会因断言变强而先红后绿——按 Step 0 → Step 1 顺序做即可。）

- [ ] **Step 5: 回归后端测试（确认未受影响）**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 与 Task 1 基线用例数一致（+ Task 3/4 新增的 2 个）。

- [ ] **Step 6: 提交**

```bash
git add web/lib/rebalance-calc.ts web/lib/rebalance-calc.test.ts
git commit -m "feat(calc): 完成计划持仓/买卖/份额取整/交易费用算法与单测"
```

---

## Phase P3：调仓计算器组件

### Task 7: 弹窗骨架（宽度 / 高度 / 关闭）

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: 无
- Produces: 一个 `flex flex-col` 的 `DialogContent`，其子元素按
  `Header(shrink-0) / 工具栏(shrink-0) / 滚动区(flex-1 min-h-0) / 费用卡(shrink-0) / 页脚(shrink-0)` 排列，供后续任务填充

- [ ] **Step 1: 改 DialogContent 类名**

`web/components/RebalanceCalculatorDialog.tsx:142`：

```tsx
      <DialogContent className="w-[calc(100vw-2rem)] sm:max-w-5xl max-h-[85vh] flex flex-col gap-3 overflow-hidden">
```

> `sm:max-w-5xl` 必须带 `sm:` 前缀 —— 基座是 `sm:max-w-lg`，无前缀的 `max-w-*` 不会被
> tailwind-merge 去重，且编译产物中 `sm:` 版本更靠后而胜出，导致弹窗恒为 512px。

- [ ] **Step 2: 给各区块加 shrink/滚动约束**

把现有 `:159` 的工具栏 `<div className="flex flex-wrap items-center justify-between gap-2">` 改为：

```tsx
        <div className="shrink-0 flex flex-wrap items-center justify-between gap-2">
```

把 `:181` 的表格容器改为：

```tsx
        <div className="flex-1 min-h-0 overflow-auto">
```

（原为 `<div className="max-h-[52vh] overflow-auto min-w-0">`；`min-w-0` 由 Table 外层提供，此处不需要双滚动。）

把 `:243` 的页脚改为：

```tsx
        <div className="shrink-0 border-t pt-3">
```

把 `:266` 的说明段改为：

```tsx
        <p className="shrink-0 text-xs text-muted-foreground leading-relaxed">
```

- [ ] **Step 3: 桌面视图关掉 DialogHeader/列表的横向挤压**

`DialogHeader` 与 `DialogTitle` 保持不动，但给 header 加 `shrink-0`：

```tsx
        <DialogHeader className="shrink-0">
```

- [ ] **Step 4: 验证：三视口打开计算器，关闭按钮在所有视口可见**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器（Playwright MCP，`bp_session` cookie 已注入）：
1. 打开 `http://localhost:3000/dashboard?id=20`
2. 把视口依次设为 `1440x900` / `768x1024` / `375x667`
3. 每个视口点击「调仓计算器」按钮
4. 断言：弹窗右上角 Close 按钮的 bounding box 完全落在视口内；弹窗容器高度 ≤ 视口高度

- [ ] **Step 5: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "fix(calc): 弹窗宽度/高度/关闭按钮三视口修复"
```

---

### Task 8: 桌面表格 —— 新增列、标的代码、四态结论

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: `CalcRow`、`CalcLine`、`computeLines`、`applyShares`、`targetAmounts`、`computeTotals`（Task 5/6）
- Produces: 桌面（`!isMobile`）分支渲染 7 列表格：
  标的(名称+代码) / 最优化权重 / 当前持仓 / 计划持仓 / 买入 / 卖出 / 份额

- [ ] **Step 1: 改 `CalcRow` 类型并接入算法模块**

`web/components/RebalanceCalculatorDialog.tsx` 顶部 import 与类型：

```tsx
import { useMemo, useState } from "react";
import { Calculator, Lock, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useIsMobile } from "@/components/ui/use-mobile";
import {
  applyShares,
  computeFees,
  computeLines,
  computeTotals,
  defaultCurrentByPrev,
  targetAmounts,
  type CalcRow,
  type Rates,
} from "@/lib/rebalance-calc";

export type { CalcRow };
```

删除文件原有的本地 `CalcRow` 定义（原 `:17-23`）与 `yuan`/`pct` 之外不再使用的 helper。

保留并复用 `yuan()` 与 `pct()`（原 `:25-36`）。

- [ ] **Step 2: 组件签名扩展**

```tsx
export function RebalanceCalculatorDialog({
  rows,
  asOf,
  defaultAmount = 1_000_000,
  currentByKey,
  priceByKey,
  rates,
  storageKey,
}: {
  rows: CalcRow[];
  /** 目标权重对应的日期, 用于标题与说明 */
  asOf?: string;
  /** 拟投资金额初值 */
  defaultAmount?: number;
  /** 「当前持仓」的预设值(最近交易日模式传入 actual_holdings 市值) */
  currentByKey?: Record<string, number>;
  /** 每标的清洗收盘价(CNY); 缺失则不显示份额 */
  priceByKey: Record<string, number>;
  /** 组合自身的三项费率 */
  rates: Rates;
  /** localStorage 键(按组合区分) */
  storageKey: string;
}) {
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState<number>(() => readStoredAmount(storageKey) ?? defaultAmount);
  const [current, setCurrent] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<Record<string, string>>({});
```

`readStoredAmount` 为模块级 helper（同文件底部）：

```tsx
const AMOUNT_STORAGE_PREFIX = "bp_calc_amount:";

function readStoredAmount(key: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AMOUNT_STORAGE_PREFIX + key);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null; // 隐私模式/存储被禁
  }
}

function writeStoredAmount(key: string, value: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AMOUNT_STORAGE_PREFIX + key, String(value));
  } catch {
    /* 忽略 */
  }
}
```

- [ ] **Step 3: 计算派生数据**

```tsx
  // 打开时(或行集/预设变化时)把「当前持仓」「计划持仓」初始化到默认值
  const initKey = `${rows.map((r) => r.key).join("|")}|${currentByKey ? "actual" : "prev"}|${amount}`;
  const [initSig, setInitSig] = useState<string>("");
  const currentAmounts = useMemo<Record<string, number>>(() => {
    const out: Record<string, number> = {};
    for (const r of rows) {
      const raw = current[r.key];
      out[r.key] = raw == null || raw.trim() === "" ? 0 : Number(raw);
    }
    return out;
  }, [rows, current]);

  const planAmounts = useMemo<Record<string, number>>(() => {
    const out: Record<string, number> = {};
    for (const r of rows) {
      const raw = plan[r.key];
      out[r.key] = raw == null || raw.trim() === "" ? 0 : Number(raw);
    }
    return out;
  }, [rows, plan]);

  const lines = useMemo(
    () => applyShares(computeLines(rows, currentAmounts, planAmounts), rows, priceByKey),
    [rows, currentAmounts, planAmounts, priceByKey],
  );
  const totals = useMemo(() => computeTotals(lines), [lines]);
  const fees = useMemo(
    () => computeFees(totals.buyTotal, totals.sellTotal, rates),
    [totals, rates],
  );
  const hasAnyPrice = Object.values(priceByKey).some((p) => Number.isFinite(p) && p > 0);
```

打开弹窗时应用默认值（一次）：

```tsx
  const applyDefaults = () => {
    const cur = currentByKey ?? defaultCurrentByPrev(rows, amount);
    const tgt = targetAmounts(rows, amount);
    setCurrent(Object.fromEntries(Object.entries(cur).map(([k, v]) => [k, String(v)])));
    setPlan(Object.fromEntries(rows.map((r) => [r.key, String(tgt[r.key] ?? 0)])));
  };
```

在 `<Dialog open={open} onOpenChange={...}>` 的 `onOpenChange` 里：打开时（`v === true` 且 `initSig !== initKey`）调用 `applyDefaults()` 并 `setInitSig(initKey)`；关闭时不清空（保留用户输入以便再次打开）。

- [ ] **Step 4: 桌面表格 JSX**

替换原表格区块为一个按 `isMobile` 分支的渲染。桌面分支：

```tsx
        {isMobile ? (
          <div className="flex-1 min-h-0 overflow-auto space-y-3">{/* Task 9 填充 */}</div>
        ) : (
          <div className="flex-1 min-h-0 overflow-auto">
            <Table className="min-w-[880px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-0">标的</TableHead>
                  <TableHead className="text-right whitespace-nowrap">最优化权重</TableHead>
                  <TableHead className="text-right whitespace-nowrap">当前持仓（元）</TableHead>
                  <TableHead className="text-right whitespace-nowrap">计划持仓（元）</TableHead>
                  <TableHead className="text-right whitespace-nowrap">买入</TableHead>
                  <TableHead className="text-right whitespace-nowrap">卖出</TableHead>
                  {hasAnyPrice && (
                    <TableHead className="text-right pr-0 whitespace-nowrap">份额</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((l) => {
                  const r = rows.find((x) => x.key === l.key)!;
                  return (
                    <TableRow key={l.key}>
                      <TableCell className="pl-0 font-medium">
                        <span className="block truncate max-w-[16rem]">{r.name}</span>
                        <span className="block text-xs text-muted-foreground font-mono">
                          {r.symbol}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono text-muted-foreground">
                        {pct(l.targetWeight)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Input
                          type="number"
                          min={0}
                          step={100}
                          inputMode="numeric"
                          className="ml-auto h-8 w-32 text-right font-mono"
                          placeholder="0"
                          aria-label={`${r.name} 当前持仓金额`}
                          value={current[l.key] ?? ""}
                          onChange={(e) => setCurrent((p) => ({ ...p, [l.key]: e.target.value }))}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Input
                          type="number"
                          min={0}
                          step={100}
                          inputMode="numeric"
                          className="ml-auto h-8 w-32 text-right font-mono"
                          placeholder="0"
                          aria-label={`${r.name} 计划持仓金额`}
                          value={plan[l.key] ?? ""}
                          onChange={(e) => setPlan((p) => ({ ...p, [l.key]: e.target.value }))}
                        />
                      </TableCell>
                      <TableCell className="text-right font-mono whitespace-nowrap">
                        {l.buy > 0.5 ? (
                          <span className="text-success">买入 ¥{yuan(l.buy)}</span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono whitespace-nowrap">
                        {l.sell > 0.5 ? (
                          <span className="text-warning">卖出 ¥{yuan(l.sell)}</span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      {hasAnyPrice && (
                        <TableCell className="text-right pr-0 font-mono text-xs whitespace-nowrap text-muted-foreground">
                          {l.buyShares ? `买 ${l.buyShares.toLocaleString("zh-CN")} 份` : ""}
                          {l.buyShares && l.sellShares ? " / " : ""}
                          {l.sellShares ? `卖 ${l.sellShares.toLocaleString("zh-CN")} 份` : ""}
                          {!l.buyShares && !l.sellShares ? "-" : ""}
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
```

> **配色注意（已按 Global Constraint 修正）**：买入/卖出是**仓位动作**，不是方向性涨跌，
> 故**不得**使用 `text-up`/`text-down`。上半句原写「买入=资金流出=红」，与同页调仓变动表的
> `d > 0 → text-up`（加仓显绿）**口径冲突**，用户会看到同一笔加仓在两张表里颜色相反。
> 统一为：**买入 `text-success`、卖出 `text-warning`**，与 Task 14 四态 Badge
> （新建仓/加仓 `success`、减仓 `warning`、清仓 `destructive`）同源。
> `text-muted-foreground` 的 `-` 占位不变。

- [ ] **Step 5: 工具栏加「按目标权重填充」与清空**

替换原工具栏右侧按钮组：

```tsx
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              拟投资金额
              <Input
                type="number"
                min={0}
                step={10_000}
                inputMode="numeric"
                className="h-8 w-32 text-right font-mono"
                value={amount}
                aria-label="拟投资金额"
                onChange={(e) => {
                  const v = Number(e.target.value);
                  const next = Number.isFinite(v) && v > 0 ? v : 0;
                  setAmount(next);
                  writeStoredAmount(storageKey, next);
                  // 金额变化即自动重算计划持仓
                  const tgt = targetAmounts(rows, next);
                  setPlan(Object.fromEntries(rows.map((r) => [r.key, String(tgt[r.key] ?? 0)])));
                }}
              />
              元
            </label>
            <Button variant="ghost" size="sm" className="gap-1.5" onClick={applyDefaults}>
              按目标权重填充
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                setCurrent({});
                setPlan({});
              }}
              disabled={lines.length === 0}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              清空
            </Button>
          </div>
```

- [ ] **Step 6: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器在 `1440x900` 打开计算器：
- 断言表头含 7 列；某 ETF 行显示「买 N 份」；清仓行（如摩根红利）显示卖出金额而非 `—`
- 断言表格区未产生横向滚动（`scrollWidth <= clientWidth + 1`）

- [ ] **Step 7: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "feat(calc): 新增当前/计划持仓列、标的代码、四态买卖与 ETF 份额"
```

---

### Task 9: 手机端卡片列表

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: `lines`、`rows`、`current`、`plan`、`setCurrent`、`setPlan`（Task 8）
- Produces: `< 768px` 时每标的渲染为一张 `Card`，无横向滚动

- [ ] **Step 1: 实现卡片分支**

把 Task 8 Step 4 里的移动分支占位替换为：

```tsx
          <div className="flex-1 min-h-0 overflow-auto space-y-2">
            {lines.map((l) => {
              const r = rows.find((x) => x.key === l.key)!;
              return (
                <div key={l.key} className="rounded-lg border border-border p-3 space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium truncate">{r.name}</span>
                    <span className="text-xs text-muted-foreground font-mono shrink-0">
                      {r.symbol}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    最优化权重{" "}
                    <span className="font-mono text-foreground">{pct(l.targetWeight)}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">当前持仓（元）</span>
                      <Input
                        type="number"
                        min={0}
                        step={100}
                        inputMode="numeric"
                        className="h-9 w-full text-right font-mono"
                        placeholder="0"
                        aria-label={`${r.name} 当前持仓金额`}
                        value={current[l.key] ?? ""}
                        onChange={(e) => setCurrent((p) => ({ ...p, [l.key]: e.target.value }))}
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">计划持仓（元）</span>
                      <Input
                        type="number"
                        min={0}
                        step={100}
                        inputMode="numeric"
                        className="h-9 w-full text-right font-mono"
                        placeholder="0"
                        aria-label={`${r.name} 计划持仓金额`}
                        value={plan[l.key] ?? ""}
                        onChange={(e) => setPlan((p) => ({ ...p, [l.key]: e.target.value }))}
                      />
                    </label>
                  </div>
                  <div className="flex items-baseline justify-between gap-2 pt-1 border-t border-border text-sm">
                    {l.buy > 0.5 ? (
                      <span className="font-mono text-success">买入 ¥{yuan(l.buy)}</span>
                    ) : l.sell > 0.5 ? (
                      <span className="font-mono text-warning">卖出 ¥{yuan(l.sell)}</span>
                    ) : (
                      <span className="text-muted-foreground">无需调仓</span>
                    )}
                    {l.buyShares != null && l.buyShares > 0 && (
                      <span className="text-xs text-muted-foreground font-mono">
                        {l.buyShares.toLocaleString("zh-CN")} 份
                      </span>
                    )}
                    {l.sellShares != null && l.sellShares > 0 && (
                      <span className="text-xs text-muted-foreground font-mono">
                        {l.sellShares.toLocaleString("zh-CN")} 份
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
```

- [ ] **Step 2: 手机端页脚加常驻「关闭」按钮**

修改页脚（Task 7 改过的那个 `shrink-0 border-t pt-3` div），在末尾加：

```tsx
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            关闭
          </Button>
```

（桌面视口下 close 按钮本来就在右上角可见，此按钮在桌面同样可用，无需条件渲染。）

- [ ] **Step 3: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器在 `375x667` 打开计算器：
- 断言页面无横向滚动：`document.documentElement.scrollWidth <= 375`
- 断言每张卡片可见「买入/卖出」结论与份数字样
- 断言右上角 Close 与页脚「关闭」都可点击

- [ ] **Step 4: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "feat(calc): 手机端卡片列表布局 + 常驻关闭按钮"
```

---

### Task 9b: 取价失败降级（份额列自愈隐藏）

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: `priceByKey`（Task 12 传入，取价失败时为 `{}`）、`hasAnyPrice`（Task 8）
- Produces: 无份额数据时不渲染份额列/份数字样，并在工具栏给出提示

- [ ] **Step 1: 确认 `hasAnyPrice` 已是唯一开关**

核对 Task 8 Step 3 的实现：`hasAnyPrice` 由 `priceByKey` 推导，取价失败 → `{}` → `false` →
桌面分支的份额列不渲染、手机卡片不显示份数。故 `{}` 时无需额外隐藏代码。

- [ ] **Step 2: 加一行降级提示（仅当有 ETF 行但无价格）**

在工具栏左侧 lock 提示之后插入：

```tsx
          {!hasAnyPrice && rows.some((r) => r.category === "etf") && (
            <span className="text-xs text-muted-foreground">（未取到价格，份额暂不可用）</span>
          )}
```

- [ ] **Step 3: 验证降级**

用 Playwright 拦截该请求使其失败，再打开计算器：

```js
async (page) => {
  await page.route("**/api/quotes/latest*", (route) => route.abort());
  await page.goto("http://localhost:3000/dashboard?id=20");
  return "routed";
}
```

断言：计算器仍可打开；表格无「份额」表头；出现「未取到价格，份额暂不可用」；
买入/卖出金额与费用卡照常显示。

- [ ] **Step 4: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "feat(calc): 取价失败降级, 份额列自愈隐藏"
```

---

### Task 10: 交易费用卡片 + 取整剩余

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: `fees`、`totals`、`rates`（Task 6/8）
- Produces: 表格下方独立费用区块，四项各一行

- [ ] **Step 1: 插入费用卡**

在滚动区之后、页脚之前插入：

```tsx
        <div className="shrink-0 rounded-lg border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
            <span className="text-muted-foreground">
              交易费用
              <span className="ml-2 text-xs">
                （佣金 {pct(rates.feeRate, 3)} / 滑点 {pct(rates.slippageRate, 3)} / 印花税{" "}
                {pct(rates.stampDutyRate, 3)}，来自组合参数）
              </span>
            </span>
            <span className="font-mono font-semibold text-foreground">
              合计 ¥{yuan(fees.total)}
            </span>
          </div>
          <dl className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-xs">
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">预计佣金</dt>
              <dd className="font-mono">¥{yuan(fees.commission)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">滑点成本</dt>
              <dd className="font-mono">¥{yuan(fees.slippage)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">印花税</dt>
              <dd className="font-mono">¥{yuan(fees.stampDuty)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">取整剩余现金</dt>
              <dd className="font-mono">¥{yuan(totals.remainder)}</dd>
            </div>
          </dl>
        </div>
```

- [ ] **Step 2: 改页脚汇总与说明文案**

页脚替换为：

```tsx
        <div className="shrink-0 border-t pt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            买入合计{" "}
            <span className="font-mono text-foreground">¥{yuan(totals.buyTotal)}</span>
            <span className="mx-2">·</span>
            卖出合计{" "}
            <span className="font-mono text-foreground">¥{yuan(totals.sellTotal)}</span>
            <span className="mx-2">·</span>
            总调仓金额{" "}
            <span className="font-mono font-semibold text-foreground">¥{yuan(totals.turnover)}</span>
          </span>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            关闭
          </Button>
        </div>
```

说明文案（原 `:266-270`）替换为：

```tsx
        <p className="shrink-0 text-xs text-muted-foreground leading-relaxed">
          说明：计划持仓 = 最优化权重 × 拟投资金额；买入 = max(0, 计划 − 当前)，卖出 =
          max(0, 当前 − 计划)。ETF 份额按 100 份/手向下取整，未成交的零头计入「取整剩余现金」。
          交易费用按组合自身费率参数计算，与回测成本口径一致（佣金/滑点双边、印花税仅卖出）。
          结果仅供执行参考。
        </p>
```

- [ ] **Step 3: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器（1440）打开计算器，手算校验：某组合 `fee_rate=0.00015`、`slippage_rate=0.00015`、
`stamp_duty_rate=0.0005`，若买入合计 ¥X、卖出合计 ¥Y，则佣金应显示 `¥round((X+Y)×0.00015)`。
断言页面数字与手算一致。

- [ ] **Step 4: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "feat(calc): 独立交易费用卡(佣金/滑点/印花税)与取整剩余现金"
```

---

### Task 11: 隐私文案修正

**Files:**
- Modify: `web/components/RebalanceCalculatorDialog.tsx`

**Interfaces:**
- Consumes: 无
- Produces: 与「会按标的代码取价」事实一致的隐私说明

- [ ] **Step 1: 替换工具栏左侧 lock 提示**

原 `:160-163`：

```tsx
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Lock className="h-3.5 w-3.5 shrink-0" />
            金额在您的浏览器本地计算，不会上传服务器；仅按标的代码查询最新收盘价以换算份额。
          </div>
```

- [ ] **Step 2: 确认无遗漏**

```bash
cd D:/balanced-portfolio/web && grep -rn "不会上传服务器\|不上传、不存储" components/ app/ | grep -v node_modules
```
Expected: 仅剩本文件 Step 1 的新文案含「不会上传服务器」这一短语，且**没有任何一处**
仍声称「不进任何请求」。

- [ ] **Step 3: 提交**

```bash
git add web/components/RebalanceCalculatorDialog.tsx
git commit -m "docs(calc): 隐私文案与取价行为对齐"
```

---

### Task 12: Dashboard 接线（日期档位 / 传参 / 费用摘要 / 取价）

**Files:**
- Modify: `web/app/dashboard/DashboardClient.tsx`

**Interfaces:**
- Consumes: `api.quotesLatest`（Task 4）、`RebalanceCalculatorDialog` 新 props（Task 8）
- Produces: 状态 `calcSource: "rebalance" | "latest"`；下拉含「最近交易日 {asOf} 最优化权重」档；
  传给计算器的 `rows/currentByKey/priceByKey/rates/storageKey`

- [ ] **Step 1: 加状态与可选档位**

在 `rbIdx` 附近（原 `:446`）加：

```tsx
  const [calcSource, setCalcSource] = useState<"rebalance" | "latest">("rebalance");
```

在既有的 `useEffect(() => { setRbIdx(...); setShowOptimalHoldings(false); ... }, [data])`
（原 `:464-468`）里补一行重置：

```tsx
    setCalcSource("rebalance");
```

- [ ] **Step 2: 打开时按需取价**

```tsx
  const [calcPriceByKey, setCalcPriceByKey] = useState<Record<string, number>>({});
  const calcKeys = useMemo(
    () => (calcSource === "latest" ? holdingsAtOptimal : rbChangeRows).map((r) => r.key),
    [calcSource, holdingsAtOptimal, rbChangeRows],
  );
  useEffect(() => {
    if (calcKeys.length === 0) {
      setCalcPriceByKey({});
      return;
    }
    let cancelled = false;
    api
      .quotesLatest(calcKeys.slice(0, 64), asOfForCalc)
      .then((res) => {
        if (cancelled) return;
        const out: Record<string, number> = {};
        res.quotes.forEach((qt, i) => {
          if (qt && Number.isFinite(qt.close)) out[calcKeys[i]] = qt.close;
        });
        setCalcPriceByKey(out);
      })
      .catch(() => {
        // 取价失败(含旧后端无此端点)静默降级: 隐藏份额列, 其余功能不受影响
        if (!cancelled) setCalcPriceByKey({});
      });
    return () => {
      cancelled = true;
    };
  }, [calcKeys, asOfForCalc]);
```

其中（放在 `rb` 定义之后）：

```tsx
  const asOfForCalc = (calcSource === "latest" ? optimalAsOf : rb?.trade_date) ?? undefined;
```

- [ ] **Step 3: 行集与当前持仓按模式切换**

```tsx
  const calcRows = useMemo(() => {
    if (calcSource === "latest") {
      return holdingsAtOptimal.map((h) => ({
        key: h.key,
        name: h.name,
        symbol: (h.symbol ?? h.key.split("@")[0]) as string,
        source: (h.source ?? h.key.split("@")[1] ?? "") as string,
        category: assetCategoryByKey[h.key],
        targetWeight: h.weight,
        prevWeight: null,
      }));
    }
    return rbChangeRows.map((r) => ({
      key: r.key,
      name: r.name,
      symbol: (r.key.split("@")[0] ?? "") as string,
      source: (r.key.split("@")[1] ?? "") as string,
      category: assetCategoryByKey[r.key],
      targetWeight: r.next,
      prevWeight: r.prev,
    }));
  }, [calcSource, holdingsAtOptimal, rbChangeRows, assetCategoryByKey]);
```

`assetCategoryByKey` 由既有的 `useAssets()` 构造（该 hook 原为死代码，本次启用）：

```tsx
  const { data: assetList } = useAssets();
  const assetCategoryByKey = useMemo(() => {
    const m: Record<string, string> = {};
    for (const a of assetList ?? []) m[`${a.symbol}@${a.source}`] = a.category ?? "";
    return m;
  }, [assetList]);
```

import 行补：`import { useAssets } from "@/lib/queries";`（若 `useAssets` 未被导出为具名导出则按实际导出名调整）。

- [ ] **Step 4: 最近交易日模式传入漂移后持仓**

> 本步的正文在 **Step 4b**（下方）。Step 4 只负责加模块级常量；
> `calcCurrentByKey` 的**唯一**实现是 Step 4b 那一段——不要按 `CALC_DEFAULT_AMOUNT`
> 缩放「当前持仓」，那会在用户改过拟投资金额后与「计划持仓」列不同尺度。

模块级常量（文件顶部 `ZERO_EPS` 附近）：

```tsx
const CALC_DEFAULT_AMOUNT = 1_000_000;
/**
 * 计算器的拟投资金额按组合持久化（Task 8 的 `bp_calc_amount:{storageKey}`）。
 * 该 storageKey 与挂载点传入的 `storageKey` **必须同源**，否则「当前持仓」预设会按
 * 1,000,000 缩放、而「计划持仓」按记忆金额缩放，两列不同尺度 → 满屏假买卖单。
 */
const CALC_STORAGE_KEY = String(portfolio.portfolio_id ?? "demo");
```

- [ ] **Step 4b: `calcCurrentByKey`（Step 4 交给本步的实现）**

`calcCurrentByKey` 的缩放基数**不是**常量，而是计算器打开时真正采用的那个金额：

```tsx
  // Task 8 的读值口径（模块级 helper 位于 rebalance-calc.ts 之外的组件文件内，
  // 此处按同一 key 规则重算一遍；读不到则回落到 CALC_DEFAULT_AMOUNT）
  const calcAmount = useMemo(
    () => readStoredCalcAmount(CALC_STORAGE_KEY) ?? CALC_DEFAULT_AMOUNT,
    [calcSource],  // 切换日期档位时重读，保证与计算器内 useState 初值同源
  );

  const calcCurrentByKey = useMemo(() => {
    if (calcSource !== "latest" || !actualHoldings) return undefined;
    const totalWeight = actualHoldings.holdings.reduce((s, h) => s + h.weight, 0) || 1;
    const out: Record<string, number> = {};
    for (const h of actualHoldings.holdings) {
      out[h.key] = Math.round((h.weight / totalWeight) * calcAmount);
    }
    return out;
  }, [calcSource, actualHoldings, calcAmount]);
```

`readStoredCalcAmount` 与 Task 8 的 `readStoredAmount` **读同一个 localStorage 键**：

```tsx
const CALC_AMOUNT_STORAGE_PREFIX = "bp_calc_amount:";
function readStoredCalcAmount(key: string): number | null {
  try {
    const raw = window.localStorage.getItem(CALC_AMOUNT_STORAGE_PREFIX + key);
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 5: 替换计算器挂载与下拉**

原 `:1263-1288` 整块替换为（该作用域内组合对象变量名为 `portfolio`，与该文件 `:853`
及费用参数区 `:2267` 的用法一致，已核对）：

```tsx
                      <div className="flex items-center gap-2 flex-wrap">
                        {calcRows.length > 0 && (
                          <RebalanceCalculatorDialog
                            rows={calcRows}
                            asOf={asOfForCalc}
                            defaultAmount={CALC_DEFAULT_AMOUNT}
                            currentByKey={calcCurrentByKey}
                            priceByKey={calcPriceByKey}
                            rates={{
                              feeRate: portfolio.fee_rate ?? 0,
                              slippageRate: portfolio.slippage_rate ?? 0,
                              stampDutyRate: portfolio.stamp_duty_rate ?? 0,
                            }}
                            storageKey={CALC_STORAGE_KEY}
                          />
                        )}
                        <select
                          className="text-sm bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none"
                          value={calcSource === "latest" ? "latest" : String(rbIdx)}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === "latest") setCalcSource("latest");
                            else {
                              setCalcSource("rebalance");
                              setRbIdx(Number(v));
                            }
                          }}
                        >
                          {hasOptimalHoldings && (
                            <option value="latest">
                              最近交易日 {optimalAsOf} 最优化权重
                            </option>
                          )}
                          {rebalancesDesc.map(({ r, idx }) => (
                            <option key={r.trade_date} value={idx}>
                              {r.trade_date}
                              {idx === rebalances.length - 1 ? " (最近调仓)" : ""}
                            </option>
                          ))}
                        </select>
                      </div>
```

> `portfolio` 变量名以该作用域内实际持有的组合对象为准（该文件在 `:2267` 已用
> `portfolio.fee_rate` 等字段渲染费用参数，沿用同一对象）。

- [ ] **Step 6: 加费用摘要行**

在 `<CardContent className="pt-0 sm:pt-0">` 的 `</>` 结尾之前（表格滚动 div 之后）插入：

```tsx
                        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          <span>
                            交易费用估算（费率取组合参数）
                            <span className="ml-1">
                              佣金 {pct(portfolio.fee_rate ?? 0, 3)} / 滑点{" "}
                              {pct(portfolio.slippage_rate ?? 0, 3)} / 印花税{" "}
                              {pct(portfolio.stamp_duty_rate ?? 0, 3)}
                            </span>
                          </span>
                          <span>
                            总调仓金额{" "}
                            <span className="font-mono text-foreground">
                              ¥
                              {yuan(
                                rbChangeRows.reduce(
                                  (s, r) => s + Math.abs((r.next ?? 0) - (r.prev ?? 0)),
                                  0,
                                ) * CALC_DEFAULT_AMOUNT,
                              )}
                            </span>
                            ，展开计算器查看逐项费用
                          </span>
                        </div>
```

（**核实结果：`yuan` 不属于 `DashboardClient.tsx` —— 该文件里只有 `pct`（`:132`），全文件 grep `yuan` 为 0 命中。**
故在 `calcRows` 同层加一个模块级 helper，与计算器内同名函数逐字一致：

```tsx
function yuan(x: number): string {
  return `¥${Math.round(x).toLocaleString("zh-CN")}`;
}
```

计算器侧的 `yuan` 是模块私有，故两处各有一份——**这是刻意的**：把格式化函数提进 `web/lib/` 会同时触碰两个已定稿文件的导出面，收益不抵风险。审查时按「已知重复」放行，不作为 defect。

> 实现前若发现 `DashboardClient.tsx` 已有等价的金额格式化函数（例如另一个名字），**复用已有的**，不要新增第二份。)

- [ ] **Step 7: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器（1440）在 `dashboard?id=20`：
- 断言下拉首项为「最近交易日 … 最优化权重」
- 选该项后断言表格行数等于最优持仓数（≥9），且份额列有值
- 切回某历史调仓日，断言清仓行有卖出金额

- [ ] **Step 8: 提交**

```bash
git add web/app/dashboard/DashboardClient.tsx
git commit -m "feat(dashboard): 计算器接入最近交易日档位/当前持仓/取价/费用摘要"
```

---

## Phase P4：调仓变动表

### Task 13: Badge 原语加 nowrap

**Files:**
- Modify: `web/components/ui/badge.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `Badge` 基类含 `whitespace-nowrap`（全站 17 个消费方共用）

- [ ] **Step 1: 改基类**

`web/components/ui/badge.tsx:7`：

```ts
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
```

- [ ] **Step 2: 构建 + 全站扫一遍徽章未溢出**

```bash
cd D:/balanced-portfolio/web && npm run build
```
Expected: exit 0。

浏览器依次打开 `/`、`/dashboard?id=20`、`/builder`、`/admin/assets`、`/cffex`，
在 375 / 768 / 1440 三个宽度断言：
- 无横向滚动（`document.documentElement.scrollWidth <= innerWidth`）
- 无徽章文字被截断（`el.scrollWidth <= el.clientWidth + 1`）

- [ ] **Step 3: 提交**

```bash
git add web/components/ui/badge.tsx
git commit -m "fix(ui): Badge 基类加 whitespace-nowrap, 禁止 CJK 标签折行"
```

---

### Task 14: 调仓表宽度 + 四态动作标识

**Files:**
- Modify: `web/app/dashboard/DashboardClient.tsx`

**Interfaces:**
- Consumes: `Badge`（Task 13）
- Produces: `rbChangeRows` 每行新增 `isAdd` / `isCut` 布尔；表格 `min-w-[560px]` + nowrap 单元格

- [ ] **Step 1: 行派生加两态**

在 `rbChangeRows` 的 `rows.push` 之前的 `isNew` / `isClose` 计算下方（原 `:509-513`）加：

```tsx
      // 已持有且加/减仓: 用于四态动作标识(新建仓/清仓已由上面两态覆盖)
      const isAdd = (prev ?? 0) > 0 && next > (prev ?? 0);
      const isCut = (prev ?? 0) > 0 && next > 0 && next < (prev ?? 0);
```

并把 `rows.push({ ... })` 改为包含新字段：

```tsx
      rows.push({
        key: k,
        name: nameMap[k] || k,
        prev,
        next,
        delta: d,
        isNew,
        isClose,
        isAdd,
        isCut,
        sortAbs,
      });
```

同时把 rows 数组的类型声明补上 `isAdd: boolean; isCut: boolean;`（原 `:490-500` 的内联类型）。

- [ ] **Step 2: 卡片标题计数补两态**

原 `:1257-1261` 的计数行改为：

```tsx
                            共 {rbChangeRows.length} 项
                            {rbNewCount > 0 && ` · 新建仓 ${rbNewCount}`}
                            {rbAddCount > 0 && ` · 加仓 ${rbAddCount}`}
                            {rbCutCount > 0 && ` · 减仓 ${rbCutCount}`}
                            {rbCloseCount > 0 && ` · 清仓 ${rbCloseCount}`}
```

并在 `rbCloseCount` 定义旁加：

```tsx
  const rbAddCount = rbChangeRows.filter((r) => r.isAdd).length;
  const rbCutCount = rbChangeRows.filter((r) => r.isCut).length;
```

- [ ] **Step 3: 表格宽度与 nowrap**

`:1300` `Table className="min-w-0"` → `Table className="min-w-[560px]"`。

四个表头补 `whitespace-nowrap`：

```tsx
                                <TableHead className="pl-0 whitespace-nowrap">资产</TableHead>
                                <TableHead className="text-right whitespace-nowrap">上期权重</TableHead>
                                <TableHead className="text-right whitespace-nowrap">本期权重</TableHead>
                                <TableHead className="text-right pr-0 whitespace-nowrap">变动</TableHead>
```

权重三个单元格补 `whitespace-nowrap`（`className` 分别为
`"text-right font-mono text-muted-foreground whitespace-nowrap"`、
`"text-right font-mono whitespace-nowrap"`、以及变动列原有的字符串末尾追加 ` whitespace-nowrap`）。

- [ ] **Step 4: 四态 Badge**

替换原 `:1323-1338` 两个条件渲染为：

```tsx
                                        {row.isNew && (
                                          <Badge
                                            variant="outline"
                                            className="border-success/40 bg-success/10 text-success font-normal shrink-0"
                                          >
                                            新建仓
                                          </Badge>
                                        )}
                                        {row.isAdd && (
                                          <Badge
                                            variant="outline"
                                            className="border-success/30 bg-success/5 text-success font-normal shrink-0"
                                          >
                                            加仓
                                          </Badge>
                                        )}
                                        {row.isCut && (
                                          <Badge
                                            variant="outline"
                                            className="border-warning/40 bg-warning/10 text-warning font-normal shrink-0"
                                          >
                                            减仓
                                          </Badge>
                                        )}
                                        {row.isClose && (
                                          <Badge
                                            variant="outline"
                                            className="border-destructive/40 bg-destructive/10 text-destructive font-normal shrink-0"
                                          >
                                            清仓
                                          </Badge>
                                        )}
```

- [ ] **Step 5: 卡片补 min-w-0**

`:1249` `<Card id="rebalance" className="scroll-mt-24">` →
`<Card id="rebalance" className="scroll-mt-24 min-w-0">`

- [ ] **Step 6: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器在 375 / 768 / 1440 打开 `/dashboard?id=20`：
- 断言「清仓」「减仓」徽章 `scrollWidth <= clientWidth`（未折行成两行：
  `el.getBoundingClientRect().height < 28`）
- 断言表格出现横向滚动容器而非压缩（在 375 下 `table.scrollWidth > container.clientWidth`）
- 断言卡片标题计数含四态

- [ ] **Step 7: 提交**

```bash
git add web/app/dashboard/DashboardClient.tsx
git commit -m "feat(dashboard): 调仓表四态标识+nowrap; 修复徽章折行与列压缩"
```

---

## Phase P5：Builder

### Task 15: 步骤条压扁成一行

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: 无
- Produces: 始终单行、`py-3`、`top-14 sm:top-16` 的步骤条

- [ ] **Step 1: 常量与类名**

在 `QUADRANT_COLOR`（原 `:32-37`）附近加：

```tsx
const STEP_SHORT: Record<number, string> = { 1: "四象限", 2: "方法", 3: "参数" };
```

`:430` 改为：

```tsx
        <div className="bg-background border-b border-border py-3 px-4 sm:px-6 sticky top-14 sm:top-16 z-40">
```

`:435` 改为：

```tsx
            <div className="flex items-center justify-between sm:justify-center sm:gap-16 relative">
```

`:436` 连接线去掉 `hidden sm:block`：

```tsx
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-px bg-border -z-10" />
```

`:441` 单步改为：

```tsx
              <div key={s.id} className="flex items-center gap-1.5 sm:gap-2 bg-background px-2 sm:px-4">
```

圆点（原 `:444` 附近的 `w-8 h-8`）改为 `w-6 h-6 sm:w-8 sm:h-8 text-xs sm:text-sm`。

标签文案（原 `:447` 附近）改为：

```tsx
                <span className="text-xs sm:text-sm whitespace-nowrap">
                  <span className="sm:hidden">{STEP_SHORT[s.id]}</span>
                  <span className="hidden sm:inline">{s.title}</span>
                </span>
```

- [ ] **Step 2: 底栏与留白回收**

`:429` `pb-24` → `pb-20 sm:pb-24`。

`:714` 底栏内层改为：

```tsx
          <div className="max-w-4xl mx-auto flex items-center justify-between gap-2">
```

两个按钮加 `flex-1 sm:flex-none`。

- [ ] **Step 3: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 375 / 768 / 1440 打开 `/builder`：
- 断言**内层步骤行**（`:435` 的 `flex items-center` 那个 div，即三个圆点的直接父容器）高度 `<= 60`（原约 96）
  —— 注意：**不要**量外层容器（`:430`），它同时装着 `<h1>` 标题（`text-2xl` + `mb-8`），
  即便 `py-8→py-3` 之后仍有 ~128px，量它必然失败。断言的对象是内层那一行。
- 断言三个步骤在同一行：三者的 `getBoundingClientRect().top` 差值 `< 2`
- 断言 375 下无横向滚动

- [ ] **Step 4: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 步骤条压扁为单行, 修复手机端竖排与顶部穿透"
```

---

### Task 16: 步骤 1 四象限紧凑化

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: `QUADRANT_SHORT`（该文件已存在）、`QUADRANT_COLOR`
- Produces: 无 min-height、手机 2×2 的四象限栅格

- [ ] **Step 1: 栅格与卡片**

`:475` 改为：

```tsx
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
```

`:477` 改为：

```tsx
                    <Card key={q} className="flex flex-col">
```

`:478` 改为：

```tsx
                      <CardContent className="p-3 sm:p-4 flex-1 flex flex-col">
```

- [ ] **Step 2: 标题短标签**

标题（原 `:480`）改为：

```tsx
                        <div className={`text-xs sm:text-sm font-medium ${QUADRANT_COLOR[q]}`}>
                          <span className="lg:hidden">{QUADRANT_SHORT[q]}</span>
                          <span className="hidden lg:inline">{QUADRANT_LABELS[q]}</span>
                        </div>
```

- [ ] **Step 3: 空态与 chip 收紧**

空态文案（原 `:491-493`）字号改 `text-xs`。

已选 chip 容器（原 `:483`）改为：

```tsx
                      <div className={`flex flex-wrap gap-1.5 flex-1 mt-2 ${selected[q].length === 0 ? "items-center content-center" : "content-start"}`}>
```

chip 本身（原 `:484-489` 内）字号改 `text-xs`，`添加资产` 按钮（原 `:873-875`）改 `className="w-full mt-3 border-dashed text-muted-foreground"`（保持 `size="sm"`）。

- [ ] **Step 4: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 375 / 768 / 1440 打开 `/builder?id=20`：
- 断言 375 下四张卡片排成 2×2：`top` 值只有 2 个不同取值
- 断言步骤 1 内容区高度 `< 400`（原 `md:min-h-[500px]` + 每卡 240）
- 断言无横向滚动

- [ ] **Step 5: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 四象限改 2×2 紧凑栅格, 移除固定最小高度"
```

---

### Task 17: 步骤 2 优化方法栅格化

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: `METHOD_OPTIONS`
- Produces: 两列卡片栅格

- [ ] **Step 1: 改栅格与卡片内距**

`:514` `space-y-4` → `grid grid-cols-1 sm:grid-cols-2 gap-3`。

`:520` `CardContent className="p-5 flex items-start gap-4"` → `"p-4 flex items-start gap-3"`。

`:526` 描述 `className="text-sm text-muted-foreground leading-relaxed"` → `"text-xs text-muted-foreground leading-snug"`。

`优化指标` 开关区（原 `:533` 附近）`mt-8 pt-8 border-t` → `mt-5 pt-5 border-t`。

- [ ] **Step 2: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 768 / 1440 打开 `/builder` 并点到第 2 步：
- 断言四张方法卡片排成 2 列（`top` 只有 2 个取值）
- 断言区块总高度比修改前明显下降（记录改前后 `scrollHeight` 对比）

- [ ] **Step 3: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 优化方法改两列栅格并收紧排版"
```

---

### Task 18: 步骤 3 回测参数栅格化

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: 无
- Produces: 无分隔线、多列栅格的参数表单

- [ ] **Step 1: 外层容器**

`:559-560`：

```tsx
          <Card>
            <CardContent className="p-5 sm:p-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-5">
```

- [ ] **Step 2: 拆除全部分隔线**

删除 `:565 / :571 / :580 / :585 / :593 / :604` 六个包裹 div 上的
`border-t border-border pt-8`（保留 `flex`/`items-center`/`gap-*` 等布局类）。
每个字段块改为独立栅格单元：把 `<label>` + 控件包进 `<div className="space-y-1.5">`。

`:613` 费率四项改为：

```tsx
              <div className="sm:col-span-2 lg:col-span-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-5">
```

- [ ] **Step 3: 控件去掉 max-w-xs**

把 `:563 / :568 / :575 / :582 / :597 / :608 / :624 / :639 / :654 / :666` 等处的
`w-full max-w-xs` 一并改为 `w-full`；`font-mono` 保留。

- [ ] **Step 4: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 1024 / 1440 打开 `/builder` 并点到第 3 步：
- 断言参数区宽视口下为 3 列（`top` 取值 ≤ 4 类）
- 断言费率四项在同一行（1440 下 `top` 一致）
- 断言无横向滚动、无字段被截断

- [ ] **Step 5: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 回测参数改多列栅格, 移除堆叠分隔线"
```

---

### Task 19: 资产弹窗手机端骨架（吸底按钮 + Tabs）

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: `useIsMobile`（`@/components/ui/use-mobile`）
- Produces: `AssetPicker` 的 `flex flex-col` 骨架 + 手机端模式切换

- [ ] **Step 1: 引入 hook 与切换状态**

在 `AssetPicker` 内（原 `:771` 附近）加：

```tsx
  const isMobile = useIsMobile();
  const [pane, setPane] = useState<"list" | "recommended">("list");
```

- [ ] **Step 2: 改 DialogContent 与骨架**

`:877` 改为：

```tsx
      <DialogContent className="w-[calc(100vw-2rem)] sm:max-w-4xl max-h-[85vh] flex flex-col gap-3 overflow-hidden">
```

Header（`:878`）加 `className="shrink-0"`。

- [ ] **Step 3: 模式切换器（仅手机）**

在 Header 之后、内容栅格之前插入：

```tsx
        {isMobile && (
          <div className="shrink-0 grid grid-cols-2 gap-1 rounded-md bg-muted p-1 text-sm">
            <button
              type="button"
              onClick={() => setPane("list")}
              className={`rounded px-3 py-1.5 ${pane === "list" ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
            >
              全部资产
            </button>
            <button
              type="button"
              onClick={() => setPane("recommended")}
              className={`rounded px-3 py-1.5 ${pane === "recommended" ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
            >
              推荐 ETF
            </button>
          </div>
        )}
```

- [ ] **Step 4: 内容区改 flex 布局**

`:881` 的栅格改为：

```tsx
        <div className="flex-1 min-h-0 flex flex-col md:grid md:grid-cols-[minmax(0,1fr)_260px] gap-4">
```

左栏（`<div className="min-w-0">`）改为：

```tsx
          <div className={`min-w-0 flex flex-col min-h-0 ${isMobile && pane !== "list" ? "hidden" : ""}`}>
```

其内部列表滚动区（`:905`）改为：

```tsx
            <div className="flex-1 min-h-0 overflow-auto space-y-1 pr-1">
```

右栏（`:960`）改为：

```tsx
          <div className={`min-w-0 flex flex-col min-h-0 md:border-l md:border-border md:pl-4 ${isMobile && pane !== "recommended" ? "hidden" : ""}`}>
```

其内部（`:963`）改为：

```tsx
            <div className="flex-1 min-h-0 overflow-auto space-y-3 pr-1">
```

- [ ] **Step 5: Footer 移出滚动区**

`DialogFooter`（`:1004`）改为：

```tsx
        <DialogFooter className="shrink-0 border-t border-border pt-3 flex-row justify-between items-center gap-2">
```

- [ ] **Step 6: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 375 打开 `/builder` → 点任一象限的「添加资产」：
- 断言「确认添加」按钮 `getBoundingClientRect().bottom <= innerHeight`（无需滚动即可见）
- 断言页面无横向滚动
- 断言切换到「推荐 ETF」页签后推荐内容可见
- 768 / 1440 下断言仍是双栏且行为不变

- [ ] **Step 7: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 资产弹窗吸底按钮+手机端 Tabs, 消除三层嵌套滚动"
```

---

### Task 20: 资产弹窗排版归一

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: `ASSET_CATEGORY_LABELS`（`@/lib/api`，该符号已导出）
- Produces: 无 `text-[10px]`、行内类别显示中文标签

- [ ] **Step 1: 替换 5 处 text-[10px]**

`:932 / :938 / :943 / :945 / :947` 的 `text-[10px]` 全部改为 `text-xs`；同时把 `h-5` 去掉
（改由 `text-xs` 自带的 16px 行高 + `py-0.5` 决定），保留 `px-1.5`。

- [ ] **Step 2: 类别显示中文**

`:950` 附近的行内元信息改为：

```tsx
                      <span className="text-xs text-muted-foreground font-mono">
                        {a.symbol}
                        {a.adjust && a.logical_source !== "etf" ? ` · ${ADJUST_LABEL[a.adjust] ?? a.adjust}` : ""}
                        {a.category ? ` · ${ASSET_CATEGORY_LABELS[a.category] ?? a.category}` : ""}
                      </span>
```

并在 import 中补 `ASSET_CATEGORY_LABELS`。

- [ ] **Step 3: 筛选行手机端改两列栅格**

`:884` 改为：

```tsx
            <div className="grid grid-cols-2 gap-2 mb-3">
              <Input
                placeholder="搜索名称或代码..."
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="col-span-2"
              />
              <Select value={vendor} onValueChange={setVendor}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
```

（第二个 Select 的 `SelectTrigger` 同样改 `w-full`。）

- [ ] **Step 4: 空态字号对齐**

`:1000` 的 `text-sm` → `text-xs`。

- [ ] **Step 5: 验证**

```bash
cd D:/balanced-portfolio/web && npm run build
```
Expected: exit 0。

```bash
cd D:/balanced-portfolio/web && grep -c "text-\[10px\]" app/builder/BuilderClient.tsx
```
Expected: `0`。

浏览器 375 打开弹窗：断言同一行内所有文字的行高一致（`line-height` 计算值相同），
断言类别显示为「ETF」而非「etf」。

- [ ] **Step 6: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 资产弹窗字号归一与类别中文化"
```

---

### Task 21: 推荐侧栏保留已选 + 空分组常显

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: `RECOMMENDED_GROUPS`、`usedSet`
- Produces: `recommended` 不再过滤已选/空分组；条目新增 `picked: boolean`

- [ ] **Step 1: 改 recommended 派生**

`:815-818` 改为：

```tsx
  // 推荐分组: 保留已选条目(置灰标记)与空分组 —— 否则用户把某组标的选进象限后,
  // 该条目乃至整组会从侧栏消失, 表现为「资产库缺了这个标的」。
  const recommended = RECOMMENDED_GROUPS.map((g) => ({
    ...g,
    assets: assets
      .filter((a) => g.symbols.includes(a.symbol))
      .map((a) => ({ asset: a, picked: usedSet.has(keyOf(a)) })),
  }));
```

- [ ] **Step 2: 渲染改为对象形态**

`:962-998` 的 `recommended.map` 内部：把 `g.assets.map((a) => ...)` 改为
`g.assets.map(({ asset: a, picked }) => ...)`，并在条目按钮上：

```tsx
                      <button
                        key={keyOf(a)}
                        type="button"
                        disabled={picked}
                        title={picked ? "已选入该象限，请从象限卡片移除" : undefined}
                        onClick={() => !picked && toggle(a)}
                        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                          picked
                            ? "cursor-not-allowed opacity-40"
                            : "hover:bg-muted"
                        } ${pending.has(keyOf(a)) ? "bg-primary/10 text-primary" : ""}`}
                      >
```

（保留原有的复选框/名称/代码渲染；名称后追加 `picked` 角标：）

```tsx
                        {picked && (
                          <span className="ml-auto text-xs text-muted-foreground shrink-0">已选</span>
                        )}
```

空分组分支（在 `g.assets.map` 之前）：

```tsx
                  {g.assets.length === 0 ? (
                    <p className="text-xs text-muted-foreground">该组标的暂不可用</p>
                  ) : g.assets.every((x) => x.picked) ? (
                    <p className="text-xs text-muted-foreground">该组已全部选入该象限</p>
                  ) : null}
```

- [ ] **Step 3: 「点击整组多选」不再作用于已选条目**

`toggleRecommended`（`:820-828`）改为只切换未选项：

```tsx
  const toggleRecommended = (group: (typeof recommended)[number]) => {
    const ks = group.assets.filter((x) => !x.picked).map((x) => keyOf(x.asset));
    if (ks.length === 0) return;
    setPending((prev) => {
      const next = new Set(prev);
      const allChecked = ks.every((k) => next.has(k));
      ks.forEach((k) => (allChecked ? next.delete(k) : next.add(k)));
      return next;
    });
  };
```

- [ ] **Step 4: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器 1440 打开 `/builder?id=20` → 打开某象限弹窗：
- 断言「国内宽基」分组下能看到 `159915`「创业板ETF（易方达）」与 `510300`「沪深300ETF（华泰柏瑞）」
- 断言「海外投资」分组下能看到 `513500`「标普500ETF（博时）」与 `159920`「恒生指数ETF（华夏）」
- 断言已在该象限的条目呈置灰 + `已选` 且不可点击
- 断言四个分组全部存在（无一因空而消失）

- [ ] **Step 5: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 推荐侧栏保留已选(置灰)与空分组, 修复资产不可见"
```

---

## Phase P6：新建方案状态重置

### Task 22: 强制重建 + 显式重置

**Files:**
- Modify: `web/app/builder/BuilderClient.tsx`

**Interfaces:**
- Consumes: 现有全部表单 state
- Produces: `sourceId == null` 时表单必定是空/默认值

- [ ] **Step 1: 加 key 强制重建**

`useSearchParams()` 在客户端组件里必须位于 `<Suspense>` 之内，因此不能直接在
`BuilderClient` 里调用。改为在既有的 Suspense 内插入一个极薄的中转组件。

`BuilderClient.tsx:84-88` 改为：

```tsx
    <Suspense fallback={<div className="p-12 text-center text-muted-foreground">加载中...</div>}>
      <BuilderKeyed initialAssets={initialAssets} />
    </Suspense>
```

并在 `BuilderClient` 与 `BuilderInner` 之间插入：

```tsx
/** 中转层: 在 Suspense 内读取 searchParams, 把「编辑 / 复制 / 新建」编码成 key,
 *  使同一路由切换 searchParams 时强制重建 BuilderInner(React 会复用同位置的实例)。 */
function BuilderKeyed({ initialAssets = [] }: { initialAssets?: Asset[] }) {
  const searchParams = useSearchParams();
  const idParam = searchParams.get("id");
  const copyParam = searchParams.get("copy");
  const modeKey = idParam ? `edit:${idParam}` : copyParam ? `copy:${copyParam}` : "new";
  return <BuilderInner key={modeKey} initialAssets={initialAssets} />;
}
```

- [ ] **Step 2: effect 补 else 显式重置**

`:150-181` 的 `if (sourceId != null) { ... }` 之后补 `else` 分支：

```tsx
        } else {
          // 新建/复制进入无 id 模式时必须回到空白态。整站跨路由导航本会重新挂载,
          // 但同路由 searchParams 变化不会 —— 两道保险避免残留上一个组合的配置。
          setStep(1);
          setSelected(emptySelection);
          setPortfolioName("我的组合");
          setPortfolioDescription(DEFAULT_DESCRIPTION);
          setMethod(METHOD_OPTIONS[0].value);
          setRatio("sharpe");
          setLookback(156);
          setBenchmarkKey(DEFAULT_BENCHMARK_KEY);
          setBand(5);
          setMaxWeightPct(DEFAULT_MAX_WEIGHT_PCT);
          setRiskFreePct(0);
          setFeePct(0.015);
          setSlippagePct(0.015);
          setStampDutyPct(0.05);
          setStartDate(defaultStartDate());
          setOrigSig(null);
        }
```

把 `:110-122` 里 `startDate` 的初始化函数抽成模块级函数 `defaultStartDate()`：

```tsx
/** 回测默认起始日: 今天往前 3 年。 */
function defaultStartDate(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 3);
  return d.toISOString().slice(0, 10);
}
```

并把 `useState(() => {...})` 改为 `useState(defaultStartDate)`。

- [ ] **Step 3: 验证**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm run build
```
Expected: exit 0。

浏览器：
1. 打开 `/builder?id=20`，断言「已配置 30 项」
2. 前进到第 3 步
3. 断言仍停留第 3 步（不重建，因为是同一 id）
4. 用 `history.pushState` + `popstate` 切到 `/builder`（同路由换参数）
5. 断言：「已配置 0 项 · 0 个品种」、步骤回到第 1 步、组合名称为「我的组合」

- [ ] **Step 4: 提交**

```bash
git add web/app/builder/BuilderClient.tsx
git commit -m "fix(builder): 新建方案强制重建+显式重置, 消除跨组合状态残留"
```

---

## Phase P7：验证与交付

### Task 23: 全量自动化测试

**Files:** 无（验证）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 通过记录

- [ ] **Step 1: 后端**

```bash
cd D:/balanced-portfolio && .venv/Scripts/python -m pytest bp_api/tests -q
```
Expected: 全部通过，用例数 = Task 1 基线 + 2（`latest_closes` 的 2 个新用例）。

- [ ] **Step 2: 前端类型与单测**

```bash
cd D:/balanced-portfolio/web && npm run typecheck && npm test
```
Expected: typecheck exit 0；vitest 11 passed。

- [ ] **Step 3: 前端构建**

```bash
cd D:/balanced-portfolio/web && npm run build
```
Expected: exit 0，无 lint 阻断。

- [ ] **Step 4: 若任何失败，修复后重跑本任务全部步骤**

---

### Task 24: 三视口浏览器验收矩阵

**Files:**
- Create: `docs/superpowers/reports/2026-09-20-builder-ui-verification.md`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 逐面截图结论 + 全站同类偏差清单

- [ ] **Step 1: 注入登录态**

用 Playwright MCP 打开 `http://localhost:3000`，然后：

```js
async (page) => {
  const token = "<用 .venv/Scripts/python 从 .env 的 BP_JWT_SECRET 签发的 admin JWT>";
  await page.context().addCookies([
    { name: "bp_session", value: token, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax" },
  ]);
  return (await page.goto("http://localhost:3000/api/session")).status();
}
```
Expected: `200`。

- [ ] **Step 2: 逐视口逐面检查**

对每个视口 `1440x900` / `768x1024` / `375x667`，逐面执行并在报告中记录结论：

| # | 面 | 断言 |
|---|---|---|
| 1 | `/builder` 步骤 1 | 步骤条单行；四象限栅格（1440=4 列 / 768=2 列 / 375=2×2）；无横滚 |
| 2 | `/builder` 步骤 2 | 780+ 两列；区块高度显著下降 |
| 3 | `/builder` 步骤 3 | 1440 三列、费率四项同行；无字段截断 |
| 4 | 资产弹窗 | 375：Tabs 可用、「确认添加」无需滚动即可点；768/1440：双栏不变；推荐四组全在 |
| 5 | `/dashboard?id=20` 调仓变动 | 「清仓」「减仓」徽章单行；375 表格横滚而非压缩 |
| 6 | 调仓计算器 | 三视口关闭按钮均可见；375 卡片列表；1440 七列表格；清仓行有卖出金额；ETF 有份额；费用四项与手算一致 |
| 7 | 新建态 | `/builder?id=20` → 同路由切 `/builder` → 全空 + 回第 1 步 |

每面每视口各存一张截图（`fullPage: false`，仅视口），并在报告中贴出断言脚本的实际返回值。

- [ ] **Step 3: 明暗主题**

对第 1、4、6 面在 `1440` 与 `375` 各跑一次暗色（通过 `emulate` 的 `colorScheme: "dark"`），
断言无对比度异常。

- [ ] **Step 4: Console 无错误**

每个页面断言 `browser_console_messages(level="error")` 为空。

- [ ] **Step 5: 产出全站同类偏差清单**

扫描并记录（**只报告不修**）：

```bash
cd D:/balanced-portfolio/web && grep -rn "text-\[10px\]" app/ components/ | grep -v node_modules
grep -rn "max-w-\(sm\|md\|lg\)\"" app/ components/ | grep -v node_modules | grep -v "sm:max-w"
```

把命中项与 `ConfirmRecomputeDialog.tsx:26`（`max-w-md` 与基座 `sm:max-w-lg` 的
twMerge 宽度 bug）一并写入报告的「同类偏差清单」章节。

- [ ] **Step 6: 提交报告**

```bash
git add docs/superpowers/reports/2026-09-20-builder-ui-verification.md
git commit -m "docs: 三视口验收报告与全站同类偏差清单"
```

---

### Task 25: 同步 GitHub

**Files:** 无

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 远端 `main` 包含全部改动

- [ ] **Step 1: 确认工作区状态**

```bash
cd D:/balanced-portfolio && git status --short
```
Expected: 仅剩 `.playwright-mcp/` 下的验收产物（未跟踪，**不入库** —— 该目录是本地工件）。
若该目录未被 `.gitignore` 忽略，则**不要** `git add .`，逐文件 add。

- [ ] **Step 2: 逐次核验提交历史**

```bash
git log --oneline origin/main..HEAD
```
Expected: 只包含本计划的提交，无夹带。

- [ ] **Step 3: 推送**

```bash
git push origin main
```
Expected: 推送成功。若被拒（远端有新提交），先 `git pull --rebase origin main`，解决冲突后重跑
Task 23 全部步骤再推送。

- [ ] **Step 4: 确认远端一致**

```bash
git fetch origin && git rev-parse HEAD origin/main
```
Expected: 两个 hash 相同。

---

## 自检

**规格覆盖**

| 规格章节 | 对应任务 |
|---|---|
| §1.1 步骤条 | Task 15 |
| §1.2 四象限 | Task 16 |
| §1.3 优化方法 | Task 17 |
| §1.4 回测参数 | Task 18 |
| §1.5 lg 层级 | Task 16/17/18（各任务内的 `lg:` 类） |
| §1.6 底栏回收 | Task 15 |
| §2 资产弹窗 | Task 19 + Task 20 |
| §3 推荐侧栏 | Task 21 |
| §4 Badge + 表格 | Task 13 + Task 14 |
| §5.1 三个 UI bug | Task 7 |
| §5.2 金额缺陷 | Task 6（算法）+ Task 8（渲染） |
| §5.3 日期档位 | Task 12 |
| §5.3 当前持仓 | Task 5（默认值）+ Task 12（接 actual_holdings） |
| §5.3 拟投资金额 | Task 8 |
| §5.3 ETF 份额 | Task 3/4（取价）+ Task 6（取整）+ Task 8（渲染）+ Task 9b（降级） |
| §5.3 标的代码 | Task 8（桌面）+ Task 9（手机） |
| §5.3 费用卡片 | Task 6（算法）+ Task 10（渲染）+ Task 12（Dashboard 摘要） |
| §5.4 隐私文案 | Task 11 |
| §5.5 后端端点 | Task 3 + Task 4 |
| §6 全站偏差清单 | Task 24 Step 5 |
| §7 验收 | Task 23 + Task 24 |
| 新建方案残留 | Task 22 |

**已知取舍**

- 「单只标的查询」按钮**不在本计划内** —— 该需求仅出现在我的早期提问中，未获用户确认。若需要，
  可在 Task 8 的基础上加一个按行触发 `api.quotesLatest([key])` 的按钮，属独立增量。
- 全站同类偏差**只出报告不修**（用户选择「全站差异报告」口径），故 Task 24 Step 5 不产生代码改动。

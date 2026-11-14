# bpdata — 对外数据 API Python SDK

`bpdata` 是 Balanced Portfolio 已上线 `/api/v1` 接口的轻量 Python 客户端：

- 统一处理 `{"data", "meta", "error"}` 响应信封；
- `429` / `5xx` 指数退避重试（最多 3 次，尊重 `Retry-After`），`401` / `403` 不重试；
- 无第三方硬依赖：`requests` 可选，缺失时自动回退 `urllib`；
- `pandas` 可选：`daily_frame()` / `valuation_frame()` 需要它；
- SDK 始终请求 JSON（不使用 `?format=csv`）。

> API 契约与口径见仓库根目录 `docs/API.md`。Base URL 默认 `https://xushilu.com`。

---

## 1. 安装

要求 **Python 3.10+**（代码使用了 `X | Y` 类型语法）。

本目录当前只包含源码包 `bpdata/`，没有 `pyproject.toml` / `setup.py`，因此**不能**
`pip install -e sdk`。任选一种方式让 Python 找到它：

### 方式 A：加入 `PYTHONPATH`（推荐，仓库内使用）

```bash
# macOS / Linux（在仓库根目录执行）
export PYTHONPATH="$PWD/sdk:$PYTHONPATH"
python -c "from bpdata import Client; print(Client)"
```

```powershell
# Windows PowerShell（在仓库根目录执行）
$env:PYTHONPATH = "$PWD\sdk;$env:PYTHONPATH"
python -c "from bpdata import Client; print(Client)"
```

### 方式 B：复制包目录

把 `sdk/bpdata/` 整个目录复制到你的项目根目录或 Python `site-packages` 下，
然后 `from bpdata import Client`。

### 可选依赖

```bash
pip install requests   # 可选：更成熟的连接池/代理支持；缺失时走 urllib
pip install pandas     # 可选：只在用 *_frame() 时需要
```

---

## 2. 快速开始

```python
import os
from bpdata import Client

client = Client(os.environ["BP_API_TOKEN"])  # 不要硬编码 token

rows = client.valuation(
    ["930641"],
    start="2024-01-01",
    end="2024-12-31",
    fields=["pe_ttm", "pb"],
)
print(rows[-1])
print("as_of:", client.last_meta.get("as_of"))
print("truncated:", client.last_meta.get("truncated"))
```

`Client` 构造参数：

```python
Client(token, base_url="https://xushilu.com", timeout=30)
```

Token 需要对应端点的 scope：`daily` 需要 `quotes`；`valuation` / `detail` /
`bond_yield` 需要 `valuation`；`percentile` 需要 `percentile`。

---

## 3. 方法

| 方法 | HTTP 端点 | 返回 |
|---|---|---|
| `daily(codes, start=None, end=None, adjust="hfq")` | `GET /api/v1/market/daily` | `list[dict]` |
| `valuation(codes, start=None, end=None, fields=None)` | `GET /api/v1/index/valuation` | `list[dict]` |
| `percentile(codes, metrics=None, windows=None)` | `GET /api/v1/index/percentile` | `list[dict]` |
| `detail(code)` | `GET /api/v1/index/detail` | `dict` |
| `bond_yield(start=None, end=None)` | `GET /api/v1/market/bond-yield` | `list[dict]` |
| `daily_frame(...)` | 同 `daily` | `pandas.DataFrame` |
| `valuation_frame(...)` | 同 `valuation` | `pandas.DataFrame` |

参数说明：

- `codes`：`"000300,600036"` 或 `["000300", "600036"]`，最多 50 个。
- `start` / `end`：`"YYYY-MM-DD"`、`datetime.date` 或 `datetime.datetime`；闭区间。
- `adjust`：`bfq` / `qfq` / `hfq`，SDK 默认 `hfq`（服务端默认 `bfq`）。
- `fields`：`pe_ttm`、`pb`、`dividend_yield_ttm`、`erp`。
- `metrics`：`pe_ttm`、`pe_static`、`pb`、`dividend_yield_ttm`、`dividend_yield_lyr`、`erp`。
- `windows`：`5y`、`10y`、`all`。

列表参数既可以是逗号分隔字符串，也可以是 `list` / `tuple`。

### 响应 meta

每次请求成功后，最近一次响应的 `meta` 会保存在 `client.last_meta`：

```python
rows = client.daily("000300", start="2015-01-01")
if client.last_meta.get("truncated"):
    raise RuntimeError("结果被 50000 行上限截断，请缩小日期范围")
print(client.last_meta.get("rows"), client.last_meta.get("as_of"))
```

> `last_meta` 是实例状态，因此一个 `Client` 实例不要跨线程共享；多线程场景请每个线程创建独立实例。

---

## 4. 错误与重试

```python
from bpdata import BpApiError, BpAuthError, BpRateLimitError

try:
    rows = client.daily("999999")
except BpAuthError as exc:          # 401 / 403，不重试
    print("鉴权失败:", exc.status, exc.code, exc.message)
except BpRateLimitError as exc:     # 429，且 3 次重试已耗尽
    print("限频:", exc.retry_after, exc.code)
except BpApiError as exc:           # 其它 4xx / 5xx / 信封错误
    print("API 错误:", exc.status, exc.code, exc.message, exc.payload)
```

- `BpAuthError`、`BpRateLimitError` 都继承自 `BpApiError`，捕获时请把具体类型放在前面。
- `429` 与 `5xx`：最多重试 3 次（总计最多 4 次请求），默认退避 `1s → 2s → 4s`；
  若响应带 `Retry-After`，优先按该值等待。
- `401` / `403` / `404` / `422`：不重试，直接抛出。
- 判断错误请使用 `exc.code`（稳定），不要依赖 `exc.message` 文本。
- `exc.payload` 保留完整错误信封，例如 `required_scope`、`codes` 等上下文。

### DataFrame

```python
df = client.daily_frame("000300", start="2024-01-01", end="2024-12-31")
print(df.tail())
```

未安装 pandas 时会抛出带安装提示的 `ImportError`，不会先发 HTTP 请求。

---

## 5. 三段可直接运行的示例

### 示例 1：Excel Power Query 拉 521 行估值

Excel →「数据」→「获取数据」→「来自其他源」→「空查询」→「高级编辑器」，
粘贴下面的 M 查询（把 `Token` 换成你的 `bp_live_...`）：

```m
let
    BaseUrl   = "https://xushilu.com",
    Token     = "bp_live_REPLACE_WITH_YOUR_TOKEN",
    IndexCode = "930641",
    EndDate   = Date.From(DateTime.LocalNow()),
    StartDate = Date.AddYears(EndDate, -3),
    Response = Web.Contents(
        BaseUrl & "/api/v1/index/valuation",
        [
            Headers = [
                #"Authorization" = "Bearer " & Token,
                #"Accept" = "application/json"
            ],
            Query = [
                codes  = IndexCode,
                start  = Date.ToText(StartDate, "yyyy-MM-dd"),
                end    = Date.ToText(EndDate, "yyyy-MM-dd"),
                fields = "pe_ttm,pb,dividend_yield_ttm,erp"
            ],
            ManualStatusHandling = {400, 401, 403, 404, 422, 429, 500, 502, 503, 504}
        ]
    ),
    Json = Json.Document(Response),
    Data = Json[data],
    Table0 = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(
        Table0, "Column1",
        {"code", "date", "pe_ttm", "pb", "dividend_yield_ttm", "erp"}
    ),
    Typed = Table.TransformColumnTypes(
        Expanded,
        {
            {"code", type text}, {"date", type date},
            {"pe_ttm", type number}, {"pb", type number},
            {"dividend_yield_ttm", type number}, {"erp", type number}
        }
    ),
    Latest521 = Table.FirstN(Table.Sort(Typed, {{"date", Order.Descending}}), 521),
    Result = Table.Sort(Latest521, {{"date", Order.Ascending}})
in
    Result
```

「关闭并上载」后应得到 521 行、6 列的数据。可在编辑器里新增一步
`Table.RowCount(Result)` 验证行数。含完整信封错误检查的版本见
`sdk/excel/bp_valuation.pq`，分步说明见 `sdk/excel/README.md`。

> Excel 询问凭据时选择「匿名」，因为 Token 已放在 `Authorization` 请求头里；
> 若出现 Formula.Firewall，请在「数据源设置」中忽略隐私级别。

### 示例 2：Python 拉某指数 5 年 PE 序列

```python
from datetime import date, timedelta

from bpdata import Client

client = Client("bp_live_REPLACE_WITH_YOUR_TOKEN")

start = date.today() - timedelta(days=365 * 5 + 2)
rows = client.valuation(
    "930641",
    start=start,
    end=date.today(),
    fields=["pe_ttm"],
)

print(f"rows={len(rows)}, as_of={client.last_meta.get('as_of')}")
for row in rows[-5:]:
    print(row["date"], row["pe_ttm"])
```

行按 `date` 升序返回；`rows[-1]` 是区间内最新一条。

### 示例 3：Python 算分位

```python
from datetime import date, timedelta

from bpdata import Client

client = Client("bp_live_REPLACE_WITH_YOUR_TOKEN")

rows = client.valuation(
    "930641",
    start=date.today() - timedelta(days=365 * 5 + 2),
    end=date.today(),
    fields=["pe_ttm"],
)
series = [float(row["pe_ttm"]) for row in rows if row.get("pe_ttm") is not None]
if not series:
    raise SystemExit("区间内没有 pe_ttm 数据")

latest = series[-1]
pct = sum(1 for value in series if value <= latest) / len(series)
print(f"当前 PE={latest:.2f}，5 年历史分位={pct * 100:.2f}%")

# 也可以直接读服务端预计算分位（pct 为 0~100 百分数）：
precomputed = client.percentile(
    "930641", metrics=["pe_ttm"], windows=["5y"]
)[0]
print(precomputed["as_of"], f"{precomputed['pct']:.2f}%", precomputed["sample_size"])
```

> 手工分位按「窗口内 ≤ 当前值的样本占比」计算，与看板口径一致；
> 预计算分位受 `sample_size` 和计算批次影响，两者可能有细微差异。

---

## 6. 字段速查

| 端点 | 返回字段 |
|---|---|
| `daily` | `code, source, date, open, high, low, close, ret` |
| `valuation` | `code, date` + 请求的 `fields` |
| `percentile` | `code, as_of, metric, window, calc_src, pct, mean, sd, p20, p50, p80, min_value, max_value, sample_size` |
| `detail` | 指数主数据 + 最新估值 + `percentiles[]` + `constituents[]` + `tracker_funds[]` |
| `bond_yield` | `date, value, unit, source` |

---

## 7. 运行测试

```bash
python -m pytest sdk/tests/test_client.py -q
```

测试全部离线：通过 monkeypatch 替换底层 HTTP，覆盖成功、401、403、404、422、
429 退避、5xx 重试、信封解析、参数拼接、DataFrame 与 urllib 兜底。

---

## 8. 安全建议

- Token 只放在环境变量 / 密钥管理器中，**不要提交到 git**，也不要写进分发的 Excel 工作簿。
- Token 泄露后请让管理员立即撤销并重新签发。
- 大批量历史数据尽量缩小日期范围或走 CSV（Excel 侧），避免触发 50000 行截断。

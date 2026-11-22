# 对外数据 API（`/api/v1`）

> 面向 Excel / Power Query / Python / BI 的只读数据接口。所有端点**只读预计算或清洗后的表**，
> 请求路径不做指标计算；行情口径、清洗与复权规则见 `docs/data-sources.md` 与
> `docs/index-valuation/06-data-model-v3.md`。

- **Base URL**：`https://<your-host>/api/v1`（反向代理将 `/api/v1/*` 转发到 FastAPI `:8000`）
- **协议**：HTTPS + JSON（可选 CSV）
- **版本策略**：`/v1` 内只增字段、不改语义；破坏性变更另开 `/v2` 并行至少 6 个月。
- **实现**：`bp_api/public_api.py`（`register_routes(app)`）。

---

## 1. 鉴权

所有 `/api/v1/*` 端点都必须携带 API Token（由超级管理员通过 `/api/admin/api-tokens` 签发；
Token 只在创建时返回一次明文，库中仅保存 `sha256(secret + pepper)`）。

支持两种请求头（二选一）：

```http
Authorization: Bearer bp_live_0123456789abcdef0123456789abcdef
```

```http
X-API-Key: bp_live_0123456789abcdef0123456789abcdef
```

### 1.1 Scope（权限范围）

`bp_api_token.scopes` 是 `TEXT[]`，端点要求的 scope 如下：

| 端点 | 必需 scope |
|---|---|
| `GET /market/daily` | `quotes` |
| `GET /index/valuation` | `valuation` |
| `GET /index/percentile` | `percentile` |
| `GET /index/detail` | `valuation` |
| `GET /market/bond-yield` | `valuation` |

- 缺失 / 非法 / 过期 / 已撤销 Token → **401**
- Token 合法但缺少端点所需 scope → **403**（响应 `error.required_scope` 给出所需 scope）

> `crypto` / `portfolio` scope 为后续端点预留，当前 `/api/v1` 五个端点不使用。

---

## 2. 响应信封

### 2.1 成功（JSON）

```json
{
  "data": [
    {"code": "000300", "date": "2024-01-02", "open": 3400.0, "high": 3450.0,
     "low": 3380.0, "close": 3430.5, "ret": 0.0123}
  ],
  "meta": {
    "rows": 1,
    "cached": false,
    "as_of": "2024-01-02",
    "codes": ["000300"],
    "adjust": "hfq",
    "truncated": false
  },
  "error": null
}
```

- `data`：数组或对象；无数据时为 `[]`（未知代码除外，见错误码）。
- `meta`：`rows`（返回行数）、`as_of`（数据截止日）、`truncated`（是否因 `limit` 截断）、
  以及各端点自己的参数回显。
- `error`：成功时恒为 `null`。

### 2.2 失败（JSON）

```json
{
  "data": null,
  "meta": {"codes": ["999999"]},
  "error": {
    "code": "unknown_code",
    "message": "以下代码不存在或没有该复权口径数据: 999999",
    "codes": ["999999"]
  }
}
```

错误对象的 `code` 是稳定的机器可读标识；`message` 仅供人阅读，可能调整。
`error` 中还会带上与错误相关的上下文（如 `codes`、`required_scope`、`invalid`）。

---

## 3. 端点总览

| 方法 | 路径 | 说明 | 主要参数 |
|---|---|---|---|
| GET | `/api/v1/market/daily` | 日行情 OHLC + 收益 | `codes`(必填)、`start`、`end`、`adjust`、`limit`、`format` |
| GET | `/api/v1/index/valuation` | 指数日频估值（仅主口径） | `codes`(必填)、`start`、`end`、`fields`、`limit`、`format` |
| GET | `/api/v1/index/percentile` | 指数估值分位（预计算） | `codes`(必填)、`metrics`、`windows`、`limit`、`format` |
| GET | `/api/v1/index/detail` | 指数画像 + 成分 + 跟踪基金 | `code`(必填)、`format` |
| GET | `/api/v1/market/bond-yield` | 10Y 国债收益率 | `start`、`end`、`limit`、`format` |
| GET | `/api/v1/market/last` | 最新已确认收盘价（A股/港股/ETF/指数，DB-only） | `codes`(必填)、`adjust`、`format` |
| GET | `/api/v1/market/history` | 跨市场历史日线（原币，可选复权） | `codes`(必填)、`start`、`end`、`adjust`、`limit`、`format` |
| GET | `/api/v1/market/fx` | 汇率（人民币腿 + 交叉汇率） | `pairs`(必填)、`start`、`end`、`format` |
| GET | `/api/v1/fund/nav` | 场外基金净值 | `codes`(必填)、`start`、`end`、`latest`、`limit`、`format` |

通用限制：

- `codes` 逗号分隔，**最多 50 个**（自动去重、去空格）。
- `limit` 默认 `50000`，允许范围 `1..50000`；单次响应最多 50000 行。
- 日期一律严格 ISO `YYYY-MM-DD`（`20240101`、`2024/01/01` 会被拒绝）。
- 时间范围是**闭区间**：`start <= trade_date <= end`。

---

## 4. 端点详情

### 4.1 `GET /market/daily`

读取 `bp_quote_clean`（清洗、汇率折算、复权后的行情）。**不直接读原始表，不实时计算收益**，
`ret` 是清洗阶段落库的日收益率。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔代码，最多 50 个，如 `000300,600036` |
| `start` | 否 | — | 起始日期（ISO） |
| `end` | 否 | — | 结束日期（ISO） |
| `adjust` | 否 | `bfq` | `bfq`（不复权）/ `qfq`（前复权）/ `hfq`（后复权） |
| `limit` | 否 | `50000` | 最大返回行数，`1..50000` |
| `format` | 否 | `json` | `json` 或 `csv` |

返回行字段：`code`、`source`、`date`、`open`、`high`、`low`、`close`、`ret`。
同一代码若存在多个数据源，会按 `source` 区分（建议消费方按需筛选）。

```bash
curl -H "Authorization: Bearer $BP_TOKEN" \
  "https://example.com/api/v1/market/daily?codes=000300,600036&start=2024-01-01&end=2024-12-31&adjust=hfq"
```

- 未知代码（或该代码没有所请求复权口径的数据）→ **404 `unknown_code`**。
- 已知代码但区间内无数据 → **200**，`data: []`。
- 返回行数达到 `limit` 且仍有更多数据 → `meta.truncated = true`，请缩小日期范围或提高 `limit`。

### 4.2 `GET /index/valuation`

读取 `bp_index_valuation_daily` 中 `is_primary = TRUE` 的唯一主口径，避免多源重复。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔指数代码，最多 50 个 |
| `start` | 否 | — | 起始日期（ISO） |
| `end` | 否 | — | 结束日期（ISO） |
| `fields` | 否 | `pe_ttm,pb,dividend_yield_ttm,erp` | 逗号分隔，可选：`pe_ttm`、`pb`、`dividend_yield_ttm`、`erp` |
| `limit` | 否 | `50000` | 最大返回行数 |
| `format` | 否 | `json` | `json` 或 `csv` |

返回行字段：`code`、`date` + 所请求的 `fields`。

```bash
curl -H "X-API-Key: $BP_TOKEN" \
  "https://example.com/api/v1/index/valuation?codes=000300&start=2024-01-01&end=2024-12-31&fields=pb,erp"
```

### 4.3 `GET /index/percentile`

读取预计算表 `bp_index_percentile`，每个 `(code, metric, window)` 返回**最新 `as_of_date`** 的一行。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔指数代码，最多 50 个 |
| `metrics` | 否 | `pe_ttm` | 逗号分隔：`pe_ttm`、`pe_static`、`pb`、`dividend_yield_ttm`、`dividend_yield_lyr`、`erp` |
| `windows` | 否 | `5y` | 逗号分隔：`5y`、`10y`、`all` |
| `limit` | 否 | `50000` | 最大返回行数 |
| `format` | 否 | `json` | `json` 或 `csv` |

返回行字段：`code`、`as_of`、`metric`、`window`、`calc_src`、`pct`、`mean`、`sd`、
`p20`、`p50`、`p80`、`min_value`、`max_value`、`sample_size`。

```bash
curl -H "Authorization: Bearer $BP_TOKEN" \
  "https://example.com/api/v1/index/percentile?codes=000300&metrics=pe_ttm,pb&windows=5y,10y"
```

> `pct` 为 0~1 的小数（如 `0.1737` 表示 17.37% 分位），与看板展示口径一致。

### 4.4 `GET /index/detail`

复用 `bp_api.repositories_valuation` 的详情读路径，返回：

- 指数主数据（`index_code`、`name`、`market`、`index_type`、`publisher`、`base_date` 等）
- 最新主口径估值（`pe_ttm`、`pb`、`dividend_yield_ttm`、`erp`、`level_*` 等）
- 最新分位（`percentiles[]`）
- 最新成分股（`constituents[]`）
- 最新跟踪基金（`tracker_funds[]`）

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `code` | 是 | — | 单个指数代码，如 `930641` |
| `format` | 否 | `json` | `json` 或 `csv` |

```bash
curl -H "Authorization: Bearer $BP_TOKEN" \
  "https://example.com/api/v1/index/detail?code=930641"
```

- 未知指数 → **404 `index_not_found`**。
- CSV 模式下，`constituents` / `tracker_funds` 等嵌套字段会序列化为 JSON 字符串放在单元格中。

### 4.5 `GET /market/bond-yield`

读取 `bp_macro_series` 中 `series_code = 'cn_10y_yield'` 的 10 年期国债收益率。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `start` | 否 | — | 起始日期（ISO） |
| `end` | 否 | — | 结束日期（ISO） |
| `limit` | 否 | `50000` | 最大返回行数 |
| `format` | 否 | `json` | `json` 或 `csv` |

返回行字段：`date`、`value`、`unit`、`source`。

```bash
curl -H "Authorization: Bearer $BP_TOKEN" \
  "https://example.com/api/v1/market/bond-yield?start=2024-01-01&end=2024-12-31"
```

### 4.6 `GET /market/last`

读取 `bp_stock_quote_daily` / `bp_etf_quote_daily` / `bp_index_quote_daily` 的最新一条日线，
**只读库内已确认收盘价，不做实时行情兜底**（与回测/清洗口径一致；Excel 现价专用）。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔，最多 50 个；`601318.SH` / `02020.HK` / `159915` 皆可，指数可用 `IDX:000300` 强制 |
| `adjust` | 否 | `bfq` | `bfq`（现价用）/ `qfq` / `hfq` |
| `format` | 否 | `json` | `json` / `csv` |

返回行字段：`code, market, currency, kind, name, date, close, prev_close, pct, adjust, source, status`。

- `date`：该代码的数据日期（Excel 侧必须展示，用于判断是否为最新交易日）。
- `status`：`ok`（库内有数据）/ `unknown`（库内无该代码）。
- `meta.latest_trade_date`：覆盖快照中的全市场最新交易日；`meta.price_basis = "last_confirmed_close"`。
- 无法解析的代码不报错，返回 `200` 并在 `meta.invalid` 中列出，便于 Excel 局部刷新。

### 4.7 `GET /market/history`

跨市场历史日线（A 股 / 港股 / ETF/LOF / 指数），**原币计价**，默认不复权。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔，最多 50 个 |
| `start` / `end` | 否 | — | ISO 日期（闭区间） |
| `adjust` | 否 | `bfq` | `bfq` / `qfq` / `hfq` |
| `limit` | 否 | 50000 | 1..50000 |
| `format` | 否 | `json` | `json` / `csv` |

返回行字段：`code, kind, market, currency, date, open, high, low, close, volume, amount, pct_change, source, adjust`。

> 同一 `(code, date, adjust)` 若在库内有多个来源，按优先级去重（腾讯/中证/东财 > 其他 > 新浪），
> 保证每行唯一；`volume` 统一为「股」，`amount` 单位「元」（K 线源可能为空）。

### 4.8 `GET /market/fx`

人民币汇率与交叉汇率。人民币腿来自 `fx_sina`（`bp_index_quote_daily`，source=`fx_sina`），
交叉汇率按「A/CNY ÷ B/CNY」由**同一交易日**的两条人民币腿计算。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `pairs` | 是 | — | 逗号分隔，如 `USD/CNY,HKD/CNY,USD/HKD,USD/SGD`（也接受 `USDCNY`），最多 20 个 |
| `start` / `end` | 否 | — | 省略则返回最新快照；给定则为区间序列 |
| `format` | 否 | `json` | `json` / `csv` |

返回行字段：`pair, base, quote, date, price, source`。缺失人民币腿时在 `meta.missing_legs` 中列出。

### 4.9 `GET /fund/nav`

场外基金净值（`bp_fund_nav_daily`），与股票代码命名空间隔离（基金与股票代码可能重号）。

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `codes` | 是 | — | 逗号分隔基金代码，最多 50 个 |
| `start` / `end` | 否 | — | ISO 日期（闭区间） |
| `latest` | 否 | `false` | `true` 时每只基金只返回最新一条 |
| `limit` | 否 | 50000 | 1..50000 |
| `format` | 否 | `json` | `json` / `csv` |

返回行字段：`code, name, date, nav, acc_nav, source`。

---

## 5. CSV 导出

两种触发方式（等价的任意一种）：

1. 查询参数：`?format=csv`
2. 请求头：`Accept: text/csv`

响应特征：

- `Content-Type: text/csv; charset=utf-8`
- 文件以 **UTF-8 BOM**（`EF BB BF`）开头，Excel / Power Query 双击打开中文不乱码。
- `Content-Disposition: attachment; filename="..."`。
- CSV 不包含 JSON 信封；`meta` 信息（行数、截断状态）请以不传 `format=csv` 的 JSON 请求获取，
  或观察返回行数是否达到 `limit`。
- 错误响应始终是 JSON 信封（HTTP 状态码不变），便于客户端统一处理。

```bash
curl -H "Authorization: Bearer $BP_TOKEN" -H "Accept: text/csv" \
  "https://example.com/api/v1/market/daily?codes=000300&start=2024-01-01&end=2024-12-31" \
  -o market_daily.csv
```

---

## 6. 错误码

| HTTP | `error.code` | 场景 |
|---|---|---|
| 400 | `missing_parameter` | 缺少必填参数（`codes` / `code`） |
| 400 | `too_many_codes` | `codes` 超过 50 个 |
| 400 | `invalid_parameter` | `adjust` / `fields` / `metrics` / `windows` / `format` 非法 |
| 401 | `unauthorized` | 缺少、非法、过期或已撤销 Token |
| 403 | `forbidden` | Token 缺少端点所需 scope（见 `error.required_scope`） |
| 404 | `unknown_code` | 行情/估值/分位请求的代码不存在（`error.codes` 列出未知代码） |
| 404 | `index_not_found` | 指数详情代码不存在 |
| 422 | `invalid_date` | 日期不是严格 ISO `YYYY-MM-DD` |
| 422 | `invalid_range` | `start > end` |
| 422 | `invalid_limit` | `limit` 不在 `1..50000` |
| 422 | `validation_error` | 参数类型错误（如 `limit=abc`），`error.details` 给出 FastAPI 原始校验信息 |
| 429 | — | **建议**：未来由网关/限流中间件返回，见下一节 |

> 不要依赖 `message` 文本编程；请使用 `error.code`。

---

## 7. 限频与容量建议

当前 `/api/v1` 端点不内置限流。生产部署建议在 FastAPI 前或反向代理层实现：

- **默认配额**：每个 Token **60 请求/分钟**，burst 10。
- 超限返回 **429**，并带 `Retry-After: <秒>`；客户端应指数退避（1s、2s、4s…，上限 60s）。
- 单次最多 `50` 个代码、`50000` 行；请优先缩小日期范围，而不是反复请求被截断的大结果。
- 数据按日更新：行情/估值通常每日收盘确认后更新，分位为预计算批次更新；
  同一参数在分钟级重复请求没有收益，建议客户端缓存 5~30 分钟（按 `meta.as_of` 判新旧）。
- 批量拉取多个代码时，尽量一次请求传多个 `codes`（≤50），避免 N 次单代码请求。
- 大盘全量历史建议走 CSV，并在我方低峰时段（收盘后至次日开盘前）执行。

> 若需要更高配额，请由管理员为该 Token 单独配置网关策略；`bp_api_token` 本身不承载限频字段。

---

## 8. Excel / Power Query 示例

> Power Query 是**表级**取数，不能像 Wind/iFinD 那样在单个单元格写 `=WSD(...)`。
> 若需要单格函数，需要 VBA UDF 或 Office 加载项，不在本 API 范围内。

1. Excel →「数据」→「获取数据」→「来自其他源」→「空查询」。
2. 在高级编辑器中粘贴：

```m
let
    BaseUrl = "https://example.com/api/v1/market/daily",
    Token   = "bp_live_0123456789abcdef0123456789abcdef",
    Url     = BaseUrl
        & "?codes=000300,600036"
        & "&start=2024-01-01&end=2024-12-31&adjust=hfq&format=json",
    Resp = Web.Contents(
        Url,
        [
            Headers = [
                #"Authorization" = "Bearer " & Token,
                #"Accept" = "application/json"
            ]
        ]
    ),
    Json = Json.Document(Resp),
    Data = Json[data],
    AsTable = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(
        AsTable,
        "Column1",
        {"code", "source", "date", "open", "high", "low", "close", "ret"}
    ),
    Typed = Table.TransformColumnTypes(
        Expanded,
        {
            {"code", type text}, {"source", type text}, {"date", type date},
            {"open", type number}, {"high", type number}, {"low", type number},
            {"close", type number}, {"ret", type number}
        }
    )
in
    Typed
```

3. 若希望直接得到 CSV：把 URL 中的 `format=json` 改为 `format=csv`，并用
   `Csv.Document(Web.Contents(...), [Delimiter=",", Encoding=65001])` 读取。
4. Token 建议放在 Power Query 参数或 Windows 凭据中，不要硬编码进工作簿后分发。

---

## 9. Python 示例

```python
from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://example.com/api/v1"
TOKEN = "bp_live_0123456789abcdef0123456789abcdef"


def get_json(path: str, **params: Any) -> dict:
    """带 401/403/429 处理的 GET；返回完整信封。"""
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    for attempt in range(5):
        resp = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=30)
        if resp.status_code == 429:
            delay = int(resp.headers.get("Retry-After", "2"))
            time.sleep(delay)
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (401, 403):
            raise RuntimeError(f"鉴权失败: {resp.status_code} {resp.text}")
        if resp.status_code >= 400:
            raise RuntimeError(f"{resp.status_code}: {resp.json()['error']}")
        return resp.json()
    raise RuntimeError("请求重试耗尽")


def load_market_daily(codes: list[str], start: str, end: str, adjust: str = "hfq") -> pd.DataFrame:
    payload = get_json(
        "/market/daily",
        codes=",".join(codes),
        start=start,
        end=end,
        adjust=adjust,
        limit=50000,
    )
    if payload["meta"].get("truncated"):
        raise RuntimeError("结果被截断，请缩小日期范围或分批请求")
    return pd.DataFrame(payload["data"])


df = load_market_daily(["000300", "600036"], "2024-01-01", "2024-12-31")
print(df.head())
```

CSV + pandas 的等价写法（适合大结果）：

```python
url = f"{BASE_URL}/market/daily"
params = {"codes": "000300,600036", "start": "2024-01-01", "end": "2024-12-31",
          "adjust": "hfq", "format": "csv"}
resp = requests.get(url, params=params,
                    headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
resp.raise_for_status()
from io import StringIO
df = pd.read_csv(StringIO(resp.content.decode("utf-8-sig")))
```

---

## 10. 数据口径与注意事项

- `/market/daily` 只读 `bp_quote_clean`；非 CNY 资产已按新浪汇率折算为人民币（`fx_rate` 审计列），
  插值行 `fill_flag = interp`，**插值价不是可成交价**。
- `/index/valuation` 只返回 `is_primary = TRUE` 的主口径；同一指数同日多源数据不会重复返回。
- `/index/percentile` 返回预计算分位，不在请求路径重算；`sample_size` 为窗口内有效样本数。
- `/market/bond-yield` 返回 `cn_10y_yield` 原始值（通常单位为 `%`），ERP 口径已在估值表中计算。
- `meta.as_of` 是该次响应中最新的一条数据日期；无数据时为 `null`。
- 该 API 不暴露组合/回测/OTC 数据；如需组合结果，请使用站内登录接口（JWT），不要复用 API Token。

# P0 模块接口契约（供并行开发对齐）

> 三个模块分别由不同 agent 实现，必须严格按本契约的函数名/参数/返回结构，否则集成会返工。

## 1. `bp_ingest/valuation_pingan.py`（已完成）

已实现并测试：`fetch_index_universe` / `fetch_index_detail(codes)` / `fetch_index_description` / `fetch_index_valuation_meta` / `fetch_index_performance` / `fetch_bond10_history` / `fetch_tracker_funds(codes)` / `parse_series` / `parse_stock_list` / `parse_trace` / `normalize_index_row` / `fetch_all`。**不要修改该文件**。

`rows` 统一为 `dict`，字段用 snake_case：
```python
# 指数主数据行
{"index_code": "930641", "market": "CSI", "name": "中证中药", "index_type": "主题",
 "pe_ttm": 23.27, "pb": 2.02, "dividend_yield_ttm": 3.68, "erp": 2.07,
 "pe_basis": "vendor_default", "level_pe": "低估", "trade_date": date(2026,11,13)}
```

## 2. `bp_api/repositories_valuation.py`（由 ingest-agent 实现）

全部函数签名为 `(conn, ...)`，使用 `conn.cursor()`，不自己 commit（由调用方提交）。返回原生类型。

```python
def upsert_index_master(conn, rows: list[dict]) -> int: ...          # ON CONFLICT (index_code) DO UPDATE
def upsert_valuation_daily(conn, rows: list[dict]) -> int: ...      # ON CONFLICT (index_code,trade_date,calc_src)
def upsert_valuation_series(conn, rows: list[dict]) -> int: ...     # ON CONFLICT (index_code,trade_date,metric,calc_src)
def upsert_percentiles(conn, rows: list[dict]) -> int: ...          # ON CONFLICT (index_code,as_of_date,metric,window_key,calc_src)
def fetch_series(conn, index_code: str, metric: str, calc_src: str,
                 start: date | None, end: date | None) -> list[tuple[date, float]]: ...
def get_market_overview(conn, as_of: date) -> list[dict]: ...       # 各板块 PE/PB/分位
def get_index_list(conn, *, query: str | None, index_type: str | None,
                   only_with_etf: bool, only_with_valuation: bool,
                   limit: int, offset: int) -> tuple[list[dict], int]: ...  # (rows, total)
def get_index_detail(conn, index_code: str) -> dict | None: ...
def get_index_history(conn, index_code: str, metric: str, window: str) -> list[dict]: ...
```

**性能要求**：`get_index_list` 单次查询（JOIN `bp_index_master` + 最新 `is_primary` 估值 + 最新分位），禁止 N+1；必须能被 `EXPLAIN` 证明走索引。

## 3. `bp_ingest/valuation_ingest.py`（由 ingest-agent 实现）

```python
def run_valuation_ingest(conn, as_of: date | None = None,
                         fetch=valuation_pingan.fetch_all) -> dict:
    """抓取 → 归一化 → 落库 → 重算分位。返回摘要：
    {"as_of": date, "indices": int, "valuation_rows": int, "series_rows": int,
     "percentile_rows": int, "errors": list[str], "duration_ms": int}"""
```
- 分位重算：对每个指数 × metric(pe_ttm/pb/dividend_yield_ttm/erp) × window(5y/10y/all)，用 `bp_api/quant/valuation.py` 的 `window_slice` + `summarize`。
- 只重算「当日有主口径数据」的指数；失败标的记入 errors 不中断。
- 幂等：同一天重复跑结果一致（upsert）。

## 4. `bp_api/valuation.py`（由 api-agent 实现）

```python
def register_routes(app): ...
# 全部 GET，前缀 /api/valuation，依赖 optional_user（页面只读公开）
# 统一响应信封：{"data": ..., "meta": {"as_of": "2026-11-13", "rows": N, "cached": bool}}
```

| 端点 | 参数 | 返回 |
|---|---|---|
| `/api/valuation/overview` | — | 4 个板块估值卡 |
| `/api/valuation/indices` | q, type, with_etf, with_val, limit(≤500), offset | 列表 + total |
| `/api/valuation/{code}` | — | 详情（画像 + 最新估值 + 分位 + 成分 + 跟踪基金） |
| `/api/valuation/{code}/history` | metric, window | 序列 + 区间统计 |

- 错误：未知代码 404 `{"detail":"index_not_found"}`；参数非法 422。
- 禁止在请求路径做重计算（只读预计算表）。

## 5. 测试要求

| 模块 | 测试文件 | 最少用例 |
|---|---|---|
| repositories_valuation | `bp_api/tests/test_repositories_valuation.py` | 8（含 upsert 幂等、列表分页、N+1 反例） |
| valuation_ingest | `bp_api/tests/test_valuation_ingest.py` | 6（用 fake fetch + 测试 PG 或 mock conn） |
| valuation API | `bp_api/tests/test_valuation_api.py` | 8（200/404/422/分页/缓存头） |

连接真实测试库时可用 `81.71.158.239:5432` 的 `bp_mig_test`（已含 schema+51+52），但**必须自行清理**或使用独立库名。
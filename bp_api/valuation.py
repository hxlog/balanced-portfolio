"""指数估值看板 — API 端点。

四个只读接口(契约 docs/index-valuation/15-p0-contracts.md 第 4 节):
  GET /api/valuation/overview          4 个板块估值卡
  GET /api/valuation/indices           指数列表(q/type/with_etf/with_val/limit/offset)
  GET /api/valuation/{code}            指数详情(画像 + 最新估值 + 分位 + 成分 + 跟踪基金)
  GET /api/valuation/{code}/history    估值序列 + 区间统计

响应统一信封 ``{"data": ..., "meta": {"as_of", "rows", "cached", ...}}``。
页面只读公开, 鉴权依赖 ``optional_user``(带 token 时解析用户, 匿名亦可访问)。

请求路径永不重算: 路由只读 ``repositories_valuation`` 的预计算表; Redis 缓存
60 秒, 缓存不可用时由 ``bp_api.cache`` 静默降级为 miss。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from importlib.util import find_spec
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query

from . import auth, cache, db
from .repositories import _json_safe

# repositories_valuation 由 ingest-agent 并行交付。尚未合并时保持本模块可导入
# (main.py 的路由注册冒烟测试不能被拖垮), 运行期调用会得到 500。
if find_spec(f"{__package__}.repositories_valuation") is None:  # pragma: no cover
    # 并行开发期该模块可能尚未合并; 只吞「模块不存在」, 模块内部错误照常抛出。
    repositories_valuation = None  # type: ignore[assignment]
else:
    from . import repositories_valuation

logger = logging.getLogger(__name__)

CACHE_PREFIX = "api:valuation:"
CACHE_TTL_SECONDS = 60

# bp_index_valuation_series.ck_series_metric 的全部合法值
SeriesMetric = Literal[
    "pe_ttm",
    "pe_static",
    "pb",
    "dividend_yield_ttm",
    "dividend_yield_lyr",
    "erp",
]
WindowKey = Literal["5y", "10y", "all"]

# 详情里的默认窗口分位字段(与前端 ValuationDetail 的 *_stats 同名)。
_STATS_FIELD: dict[str, str] = {
    "pe_ttm": "pe_stats",
    "pb": "pb_stats",
    "dividend_yield_ttm": "dividend_stats",
    "erp": "erp_stats",
}


# ---------------------------------------------------------------------------
# 响应与缓存辅助
# ---------------------------------------------------------------------------

def _api_safe(obj: Any) -> Any:
    """把 DB 原生类型转成可缓存、可 JSON 序列化的结构。

    NaN/Inf 走 repositories._json_safe(与写库同一口径); date/datetime 提前转 ISO,
    保证首次响应与 Redis 回读后的字段类型完全一致。
    """
    if isinstance(obj, dict):
        return {k: _api_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_api_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return _json_safe(obj)


def _iso(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _latest_as_of(rows: list[dict]) -> str:
    """列表/详情里最新的数据截止日; 无数据时回退到今天。"""
    candidates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("as_of", "trade_date", "date"):
            value = row.get(key)
            if value:
                candidates.append(_iso(value))
                break
    return max(candidates) if candidates else date.today().isoformat()


def _cache_key(kind: str, **params: Any) -> str:
    """缓存键包含全部参数, 防止不同筛选条件串结果。"""
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}{kind}:{digest}"


def _get_cached(key: str) -> Optional[dict]:
    cached = cache.get_json(key)
    if isinstance(cached, dict):
        meta = cached.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["cached"] = True
        return cached
    return None


def _envelope(data: Any, *, as_of: str, rows: int, **extra: Any) -> dict:
    return _api_safe({
        "data": data,
        "meta": {"as_of": as_of, "rows": rows, "cached": False, **extra},
    })


def _history_stats(detail: dict, metric: str, window: str) -> Optional[dict]:
    """区间统计直接取详情里的预计算分位, 不在请求路径重算。"""
    field = _STATS_FIELD.get(metric)
    stats = detail.get(field) if field else None
    if isinstance(stats, dict):
        return stats
    percentiles = detail.get("percentiles")
    if isinstance(percentiles, list):
        for item in percentiles:
            if (
                isinstance(item, dict)
                and item.get("metric") == metric
                and item.get("window_key") == window
            ):
                return item
    return None


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

def register_routes(app: FastAPI) -> None:

    # 静态路径必须先于 /{code} 注册, 否则 "overview"/"indices" 会被当成代码。
    @app.get("/api/valuation/overview")
    def valuation_overview(
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("overview")
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            rows = repositories_valuation.get_market_overview(conn, date.today())
        payload = _envelope(rows, as_of=_latest_as_of(rows), rows=len(rows))
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/indices")
    def valuation_indices(
        q: str | None = Query(None, max_length=100, description="名称或代码搜索"),
        index_type: str | None = Query(None, alias="type", max_length=20, description="指数类别"),
        with_etf: bool = Query(False, description="仅看有跟踪 ETF 的指数"),
        with_val: bool = Query(False, description="仅看有估值的指数"),
        limit: int = Query(100, ge=1, le=1000, description="每页条数, 上限 500"),
        offset: int = Query(0, ge=0, description="偏移量"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key(
            "indices",
            q=q,
            type=index_type,
            with_etf=with_etf,
            with_val=with_val,
            limit=limit,
            offset=offset,
        )
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            rows, total = repositories_valuation.get_index_list(
                conn,
                query=q,
                index_type=index_type,
                only_with_etf=with_etf,
                only_with_valuation=with_val,
                limit=limit,
                offset=offset,
            )
        payload = _envelope(
            rows,
            as_of=_latest_as_of(rows),
            rows=len(rows),
            total=total,
            limit=limit,
            offset=offset,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/{code}")
    def valuation_detail(
        code: str,
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("detail", code=code)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            detail = repositories_valuation.get_index_detail(conn, code)
        if detail is None:
            raise HTTPException(404, "index_not_found")
        payload = _envelope(detail, as_of=_latest_as_of([detail]), rows=1)
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/{code}/history")
    def valuation_history(
        code: str,
        metric: SeriesMetric = Query("pe_ttm", description="估值指标"),
        window: WindowKey = Query("5y", description="分位窗口"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("history", code=code, metric=metric, window=window)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            detail = repositories_valuation.get_index_detail(conn, code)
            if detail is None:
                raise HTTPException(404, "index_not_found")
            series = repositories_valuation.get_index_history(
                conn, code, metric, window
            )
        payload = _envelope(
            {"series": series, "stats": _history_stats(detail, metric, window)},
            as_of=_latest_as_of(series) if series else _latest_as_of([detail]),
            rows=len(series),
            metric=metric,
            window=window,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

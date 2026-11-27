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
WindowKey = Literal["1y", "3y", "5y", "10y", "all"]

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

# 首页全市场估值卡片使用的代表性宽基（有完整估值历史，可算真实分位）
# 说明：中证全指 000985 暂无可用估值序列（平安未覆盖），用上证50/沪深300/中证A500/中证500/中证1000
# 覆盖大中小盘作为全市场代理，页面上会注明「宽基组合代理」。
_BROAD_PROXY_CODES = ["000016", "000300", "000510", "000905", "000852"]

# MVI overlay 支持的 4 只宽基（需求 3；与 repositories_valuation.OVERLAY_INDEX_CODES 保持一致）
_MVI_OVERLAY_CODES = ("000300", "000510", "000016", "000985")
# MVI 序列可用区间（与 repositories_valuation.MVI_RANGES 保持一致）
_MVI_RANGE_KEYS = ("1y", "3y", "5y", "10y", "all")


def register_routes(app: FastAPI) -> None:

    # POST-REDESIGN: /api/v1 快速只读端点（首页估值页 / MVI 卡）。
    # 与 /api/v1 public_api 的 API token 端点不同：这些是页面公开数据，走
    # optional_user（匿名可读），由 Next rewrite 直接代理；gzip/TTL 由 root 的
    # FastAPI 中间件统一接入，本模块只保证 SQL 走小表/快照表。
    @app.get("/api/v1/valuation/indices")
    def valuation_indices_fast(
        window: WindowKey = Query("5y", description="分位窗口"),
        metric: str = Query("pe_ttm", description="兼容参数（4 指标始终全部返回）"),
        limit: Optional[int] = Query(None, ge=1, le=1000, description="可选分页；默认全部"),
        offset: int = Query(0, ge=0),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """读 bp_index_valuation_latest 快照：全部跟踪指数 4 指标当前值/分位/涨跌（<50ms）。"""
        key = _cache_key(
            "v1_indices", window=window, metric=metric, limit=limit, offset=offset
        )
        hit = _get_cached(key)
        if hit is not None:
            return hit
        if repositories_valuation is None:  # pragma: no cover - 并行开发期保护
            raise HTTPException(503, "valuation_repository_unavailable")
        with db.get_conn() as conn:
            rows = repositories_valuation.get_valuation_latest_list(conn, window=window)
        total = len(rows)
        if limit is not None:
            rows = rows[offset : offset + limit]
        elif offset:
            rows = rows[offset:]
        updated_values = [
            _iso(row.get("updated_at"))
            for row in rows
            if isinstance(row, dict) and row.get("updated_at") is not None
        ]
        payload = _envelope(
            rows,
            as_of=_latest_as_of(rows),
            rows=len(rows),
            total=total,
            window=window,
            metric=metric,
            updated_at=max(updated_values) if updated_values else None,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/v1/market/mvi")
    def market_mvi(
        range: str = Query("5y", description="1y/3y/5y/10y/all"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """MVI 最新值 + 区间周频序列 + 因子贡献（读 bp_market_valuation_index）。"""
        range_key = range if range in _MVI_RANGE_KEYS else "5y"
        key = _cache_key("v1_mvi", range=range_key)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            data = repositories_valuation.get_market_valuation_index_range(
                conn, range=range_key
            )
        latest = data.get("latest") or {}
        history = data.get("history") or []
        payload = _envelope(
            {"latest": latest, "history": history},
            as_of=latest.get("as_of"),
            rows=len(history),
            range=range_key,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/v1/market/mvi/overlay")
    def market_mvi_overlay(
        index: str = Query("000985", description="000300/000510/000016/000985"),
        range: str = Query("5y", description="1y/3y/5y/10y/all"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """MVI 周频序列 + 指定指数收盘价序列（双轴 overlay；无价格返回空+reason，不造数）。"""
        code = str(index or "").strip()
        if code not in _MVI_OVERLAY_CODES:
            raise HTTPException(404, "index_not_supported")
        range_key = range if range in _MVI_RANGE_KEYS else "5y"
        key = _cache_key("v1_mvi_overlay", index=code, range=range_key)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            data = repositories_valuation.get_market_mvi_overlay(
                conn, code, range=range_key
            )
        series = data.get("series") or []
        as_of = None
        if series:
            as_of = _iso(series[-1].get("trade_date"))
        elif data.get("mvi_end"):
            as_of = data["mvi_end"]
        # P2：无价格且无 MVI 时不得用 date.today() 伪造 as_of（会让前端误以为数据
        # 更新到今天）；如实返回 None，由 missing/reason 表达「无数据」。
        payload = _envelope(
            data,
            as_of=as_of,
            rows=len(series),
            range=range_key,
            source="bp_index_quote_daily",
            missing=bool(data.get("missing")),
            reason=data.get("reason"),
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    # 静态路径必须先于 /{code} 注册, 否则 "overview"/"indices" 会被当成代码。
    @app.get("/api/valuation/overview")
    def valuation_overview(
        window: WindowKey = Query("5y", description="分位窗口"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("overview", window=window)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            rows = repositories_valuation.get_market_overview(conn, date.today())
            proxies = repositories_valuation.get_broad_proxies(
                conn, _BROAD_PROXY_CODES, window
            )
            try:
                mvi = repositories_valuation.get_market_valuation_index(conn)
            except Exception:  # noqa: BLE001
                mvi = {"latest": None, "history": []}
        payload = _envelope(
            rows,
            as_of=_latest_as_of(rows),
            rows=len(rows),
            window=window,
            proxies=proxies,
            proxy_codes=list(_BROAD_PROXY_CODES),
            mvi=mvi,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/indices")
    def valuation_indices(
        q: str | None = Query(None, max_length=100, description="名称或代码搜索"),
        index_type: str | None = Query(None, alias="type", max_length=20, description="指数类别"),
        industry: str | None = Query(None, max_length=20, description="申万一级行业"),
        window: WindowKey = Query("5y", description="分位窗口"),
        metric: str = Query("pe_ttm", description="所选分位指标"),
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
            industry=industry,
            window=window,
            metric=metric,
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
                industry=industry,
                window=window,
                metric=metric,
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
            window=window,
            metric=metric,
            industry=industry,
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/funds/compare")
    def valuation_funds_compare(
        codes: str = Query(..., description="逗号分隔的基金代码（可带 SH/SZ 前缀）"),
        start: str | None = Query(None, description="开始日期 YYYY-MM-DD，默认年初"),
        end: str | None = Query(None, description="结束日期 YYYY-MM-DD，默认今天"),
        benchmark: str = Query("000300", description="基准指数代码"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        fund_codes = [item.strip() for item in codes.split(",") if item.strip()][:10]
        if not fund_codes:
            raise HTTPException(status_code=400, detail="codes 不能为空")
        try:
            start_date = date.fromisoformat(start) if start else None
            end_date = date.fromisoformat(end) if end else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
        key = _cache_key("funds_compare", codes=",".join(fund_codes), start=start, end=end, benchmark=benchmark)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            payload = repositories_valuation.compare_funds(
                conn, fund_codes, start=start_date, end=end_date, benchmark_code=benchmark
            )
        payload["meta"] = {"as_of": date.today().isoformat(), "cached": False}
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/valuation/{code}/benchmark-stats")
    def valuation_benchmark_stats(
        code: str,
        benchmark: str = Query("000300", description="基准指数代码"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        key = _cache_key("benchmark_stats", code=code, benchmark=benchmark)
        hit = _get_cached(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn:
            stats = repositories_valuation.get_index_benchmark_stats(conn, code, benchmark)
        payload = _envelope(stats, as_of=stats.get("as_of"), rows=1, benchmark=benchmark, cached=False)
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
            if detail is not None:
                detail = dict(detail)
                detail["constituents"] = repositories_valuation.get_index_constituents(
                    conn, code
                )
                detail["tracker_funds"] = repositories_valuation.get_index_tracker_funds(
                    conn, code
                )
                detail["risk"] = repositories_valuation.get_index_risk_stats(conn, code)
                # 需求 7/8：HSI 详情估值-点位双轴图（bfq 近 10 年）与跟踪基金数据截止/更新时间
                detail["price_series"] = repositories_valuation.get_index_price_series(
                    conn, code
                )
                detail["tracker_funds_meta"] = (
                    repositories_valuation.get_index_tracker_funds_meta(conn, code)
                )
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

    @app.get("/api/v1/valuation/{code}/history")
    def valuation_history_v1(
        code: str,
        metric: SeriesMetric = Query("pe_ttm", description="估值指标"),
        window: WindowKey = Query("5y", description="分位窗口"),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """v1 别名：前端估值带历史序列的新接口兜底口（与 legacy 同实现/同缓存）。"""
        return valuation_history(code=code, metric=metric, window=window, _user=_user)
"""场外衍生品定价 — API 端点 (register_routes 模式, 仿 cffex.py)。

公开: 交易日历 / 挂钩指数 / 历史波动率 / 观察日递延 / 定价(计算器) / 任务轮询 / 示例簿记
登录: 新建/编辑/删除/重估 自己的簿记
超管: 设为示例 / 手动刷新日历
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query

from . import auth, cache, db, repositories as repo, repositories_otc as rotc, tasking, tasks
from .quant.otc.calendar import gen_ko_observation_dates, roll_dates
from .schemas_otc import (
    ObservationDatesIn,
    OtcDealCreateIn,
    OtcDealUpdateIn,
    OtcPriceIn,
    ReorderOtcDealsIn,
    SetExampleIn,
)

logger = logging.getLogger(__name__)

MAX_QUOTE_KEYS = 64


def _dispatch_otc(task_id: str, spec: dict, deal_id: int | None, background_tasks: BackgroundTasks) -> None:
    """事务提交后派发: 优先 Celery, 否则 BackgroundTasks 降级。"""
    celery_id = tasking.enqueue_task(
        "bp_api.price_otc", {"task_id": task_id, "spec": spec, "deal_id": deal_id}
    )
    if celery_id:
        with db.get_conn() as conn:
            tasking.set_celery_id(conn, task_id, celery_id)
            conn.commit()
    else:
        background_tasks.add_task(tasks.run_otc_price_background, spec, deal_id, task_id)


def register_routes(app: FastAPI) -> None:

    # ---------------------------------------------------------------
    # 挂钩指数 (用指数, 不用股指期货)
    # ---------------------------------------------------------------
    @app.get("/api/otc/underlyings")
    def otc_underlyings() -> dict:
        cached = cache.get_json("otc:underlyings")
        if cached is not None:
            return cached
        with db.get_conn() as conn:
            items = rotc.list_underlyings(conn)
        result = {"underlyings": items}
        if items:
            cache.set_json("otc:underlyings", result, ttl_seconds=3600)
        return result

    # ---------------------------------------------------------------
    # 交易日历
    # ---------------------------------------------------------------
    @app.get("/api/otc/calendar")
    def otc_calendar(
        dfrom: str = Query(..., description="起始日 YYYY-MM-DD"),
        dto: str = Query(..., description="截止日 YYYY-MM-DD"),
    ) -> dict:
        try:
            f = date.fromisoformat(dfrom)
            t = date.fromisoformat(dto)
        except ValueError as exc:
            raise HTTPException(400, "日期格式须为 YYYY-MM-DD") from exc
        if (t - f).days > 366 * 4:
            raise HTTPException(400, "日期范围过大(最多约4年)")
        cache_key = f"otc:calendar:{dfrom}:{dto}"
        cached = cache.get_json(cache_key)
        if cached is not None:
            return cached
        with db.get_conn() as conn:
            days = rotc.get_calendar(conn, f, t)
        result = {"market": "CN", "days": days}
        if days:
            cache.set_json(cache_key, result, ttl_seconds=3600)
        return result

    @app.post("/api/otc/calendar/refresh")
    def otc_calendar_refresh(_: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
        with db.get_conn() as conn:
            info = rotc.refresh_trading_calendar(conn)
            conn.commit()
        cache.delete_pattern("otc:calendar:*")
        return info

    # ---------------------------------------------------------------
    # 观察日递延 (非交易日 following 顺延)
    # ---------------------------------------------------------------
    @app.post("/api/otc/observation-dates")
    def otc_observation_dates(payload: ObservationDatesIn) -> dict:
        with db.get_conn() as conn:
            cal = rotc.load_calendar_view(conn, payload.start_date, payload.maturity_date)
        if payload.dates:
            return {"dates": roll_dates(payload.dates, cal)}
        dates = gen_ko_observation_dates(
            payload.start_date, payload.maturity_date, cal,
            freq_months=payload.freq_months, lock_term_months=payload.lock_term_months,
        )
        return {"dates": [{"requested": d.isoformat(), "effective": d.isoformat(), "rolled": False} for d in dates]}

    # ---------------------------------------------------------------
    # 历史波动率 (指数)
    # ---------------------------------------------------------------
    @app.get("/api/otc/volatility")
    def otc_volatility(
        symbols: str = Query(..., description="逗号分隔指数代码"),
        windows: str = Query("90,120,180,365"),
        source: str | None = Query(None),
    ) -> dict:
        syms = [s.strip() for s in symbols.split(",") if s.strip()][:8]
        try:
            wins = [int(w) for w in windows.split(",") if w.strip()][:6]
        except ValueError as exc:
            raise HTTPException(400, "windows 须为逗号分隔整数") from exc
        if not syms or not wins:
            raise HTTPException(400, "需提供 symbols 与 windows")
        cache_key = f"otc:vol:{','.join(syms)}:{','.join(map(str, wins))}:{source or ''}"
        cached = cache.get_json(cache_key)
        if cached is not None:
            return cached
        with db.get_conn() as conn:
            data = rotc.historical_volatility(conn, syms, wins, source=source)
        result = {"series": data}
        if data:
            cache.set_json(cache_key, result, ttl_seconds=1800)
        return result

    @app.get("/api/otc/vol-suggest")
    def otc_vol_suggest(
        symbol: str = Query(...),
        window: int = Query(90, ge=5, le=1000),
        source: str | None = Query(None),
    ) -> dict:
        with db.get_conn() as conn:
            src = source or rotc.resolve_source(conn, symbol, None)
            vol = rotc.realized_vol_estimate(conn, symbol, src, window) if src else None
        return {"symbol": symbol, "source": src, "window": window, "vol": vol}

    @app.get("/api/otc/spot")
    def otc_spot(
        symbol: str = Query(...),
        source: str | None = Query(None),
        date_str: str | None = Query(None, alias="date"),
    ) -> dict:
        on_date = None
        if date_str:
            try:
                on_date = date.fromisoformat(date_str)
            except ValueError as exc:
                raise HTTPException(400, "date 须为 YYYY-MM-DD") from exc
        with db.get_conn() as conn:
            row = rotc.spot_on_date(conn, symbol, source=source, on_date=on_date)
        if not row:
            raise HTTPException(404, "未找到该日行情")
        return row

    # ---------------------------------------------------------------
    # 批量最新收盘价 (公开; 供调仓计算器把金额换算成份额)
    # ---------------------------------------------------------------
    @app.get("/api/quotes/latest")
    def quotes_latest(
        keys: str = Query(..., description="symbol@source, 逗号分隔, 最多 64 个"),
        # alias 与 otc_spot 同风格; 用 Annotated 是为了让直接调用 endpoint 函数
        # (本仓测路由的既有约定, 不走 ASGI) 时拿到真值而非 Query 对象。
        date_str: Annotated[str | None, Query(alias="date")] = None,
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

    # ---------------------------------------------------------------
    # 定价 (异步; 需登录)
    # ---------------------------------------------------------------
    @app.post("/api/otc/price")
    def otc_price(
        payload: OtcPriceIn,
        background_tasks: BackgroundTasks,
        user: auth.UserContext = Depends(auth.require_user),
        deal_id: int | None = Query(None, description="若指定则定价后写入该簿记"),
    ) -> dict:
        spec = payload.to_terms()
        with db.get_conn() as conn:
            if deal_id is not None:
                if not rotc.can_edit_otc_deal(conn, deal_id, user.user_id, user.is_admin):
                    raise HTTPException(403, "无权限编辑该簿记")
            task_id = tasking.create_task(
                conn, "otc_price",
                owner_user_id=user.user_id,
                progress_total=7, message="定价已排队",
            )
            conn.commit()
        _dispatch_otc(task_id, spec, deal_id, background_tasks)
        return {"task_id": task_id}

    @app.get("/api/otc/tasks/{task_id}")
    def otc_task(task_id: str, _: auth.UserContext | None = Depends(auth.optional_user)) -> dict:
        with db.get_conn() as conn:
            try:
                t = tasking.get_task(conn, task_id)
            except KeyError as exc:
                raise HTTPException(404, "任务不存在") from exc
        if t.get("task_type") != "otc_price":
            raise HTTPException(404, "任务不存在")
        return t

    # ---------------------------------------------------------------
    # 簿记 CRUD
    # ---------------------------------------------------------------
    @app.get("/api/otc/deals")
    def otc_list_deals(user: auth.UserContext | None = Depends(auth.optional_user)) -> dict:
        with db.get_conn() as conn:
            deals = rotc.list_otc_deals(
                conn, user.user_id if user else None, user.is_admin if user else False
            )
        return {"deals": deals}

    @app.patch("/api/otc/deals/order")
    def otc_reorder_deals(
        payload: ReorderOtcDealsIn,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        with db.get_conn() as conn:
            rotc.reorder_otc_deals(conn, user.user_id, payload.ordered_ids)
            conn.commit()
        return {"ok": True}

    @app.get("/api/otc/deals/{deal_id}")
    def otc_get_deal(deal_id: int, user: auth.UserContext | None = Depends(auth.optional_user)) -> dict:
        uid = user.user_id if user else None
        adm = user.is_admin if user else False
        with db.get_conn() as conn:
            if not rotc.can_view_otc_deal(conn, deal_id, uid, adm):
                raise HTTPException(404, "簿记不存在或无权限")
            deal = rotc.get_otc_deal(conn, deal_id)
        return deal

    @app.post("/api/otc/deals")
    def otc_create_deal(
        payload: OtcDealCreateIn,
        background_tasks: BackgroundTasks,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        with db.get_conn() as conn:
            if not user.is_admin:
                limit = repo.get_user_portfolio_limit(conn, user.user_id)
                if limit is not None and rotc.count_user_deals(conn, user.user_id) >= limit:
                    raise HTTPException(403, f"簿记数量已达上限({limit}), 请删除后再新增")
            deal_id = rotc.create_otc_deal(
                conn,
                {
                    "name": payload.name,
                    "product_type": payload.params.product_type,
                    "engine": payload.params.engine,
                    "underlying_symbol": payload.params.underlying_symbol,
                    "underlying_source": payload.params.underlying_source,
                    "terms": payload.params.to_terms(),
                },
                user.user_id,
            )
            task_id = tasking.create_task(
                conn, "otc_price", owner_user_id=user.user_id, progress_total=7, message="定价已排队"
            )
            conn.commit()
        spec = payload.params.to_terms()
        _dispatch_otc(task_id, spec, deal_id, background_tasks)
        return {"deal_id": deal_id, "task_id": task_id}

    @app.put("/api/otc/deals/{deal_id}")
    def otc_update_deal(
        deal_id: int, payload: OtcDealUpdateIn, user: auth.UserContext = Depends(auth.require_user)
    ) -> dict:
        with db.get_conn() as conn:
            if not rotc.can_edit_otc_deal(conn, deal_id, user.user_id, user.is_admin):
                raise HTTPException(403, "无权限编辑该簿记")
            rotc.update_otc_deal(
                conn, deal_id,
                {
                    "name": payload.name,
                    "product_type": payload.params.product_type,
                    "engine": payload.params.engine,
                    "underlying_symbol": payload.params.underlying_symbol,
                    "underlying_source": payload.params.underlying_source,
                    "terms": payload.params.to_terms(),
                },
            )
            conn.commit()
        return {"deal_id": deal_id, "ok": True}

    @app.delete("/api/otc/deals/{deal_id}")
    def otc_delete_deal(deal_id: int, user: auth.UserContext = Depends(auth.require_user)) -> dict:
        with db.get_conn() as conn:
            if not rotc.can_edit_otc_deal(conn, deal_id, user.user_id, user.is_admin):
                raise HTTPException(403, "无权限删除该簿记")
            rotc.delete_otc_deal(conn, deal_id)
            conn.commit()
        return {"ok": True}

    @app.patch("/api/otc/deals/{deal_id}/example")
    def otc_set_example(
        deal_id: int, payload: SetExampleIn, _: auth.UserContext = Depends(auth.require_super_admin)
    ) -> dict:
        with db.get_conn() as conn:
            rotc.set_otc_example(conn, deal_id, payload.is_example)
            conn.commit()
        return {"deal_id": deal_id, "is_example": payload.is_example}

    @app.post("/api/otc/deals/{deal_id}/reprice")
    def otc_reprice_deal(
        deal_id: int,
        background_tasks: BackgroundTasks,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        with db.get_conn() as conn:
            if not rotc.can_edit_otc_deal(conn, deal_id, user.user_id, user.is_admin):
                raise HTTPException(403, "无权限重估该簿记")
            deal = rotc.get_otc_deal(conn, deal_id)
            task_id = tasking.create_task(
                conn, "otc_price", owner_user_id=user.user_id, progress_total=7, message="定价已排队"
            )
            conn.commit()
        spec = dict(deal["terms"] or {})
        spec.setdefault("underlying_symbol", deal["underlying_symbol"])
        spec.setdefault("underlying_source", deal["underlying_source"])
        _dispatch_otc(task_id, spec, deal_id, background_tasks)
        return {"task_id": task_id}

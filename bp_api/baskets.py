"""一篮子资产（basket）持久化 API：保存 / 列表 / 详情 / 编辑 / 复制 / 删除 / 服务端重算。

与象限组合（bp_portfolio）平级：/dashboard 同时展示两类组合。

ddl/78 起引入「示例篮子」（bp_basket.is_demo / display_order），鉴权语义与
bp_portfolio 的 demo 组合一致：

- 读列表：匿名只返回示例；登录用户返回 示例 + 自己的；管理员返回全部；
  支持 "?scope=demo|mine" 显式筛选（旧客户端不传 scope，行为见上）。
- 读详情：示例对所有人开放；非示例仅 owner 或管理员。
- 编辑/删除：示例仅管理员（普通用户即使 owner 也不行，应复制后编辑自己的副本）；
  非示例仅 owner 或管理员。
- 复制：必须登录；可复制任何可见篮子（示例 -> 自己的非示例副本）。
- 服务端重算：仅管理员 POST /api/baskets/{id}/recompute，写 latest_result。
  示例篮子的 latest_result 只能由该接口生成，PATCH 带 latest_result 会 400（防伪造）；
  POST 创建时客户端传入的 latest_result 一律忽略（创建即伪造结果没有意义），
  示例篮子 PATCH 变更定义（assets/method/params）时 latest_result 置 NULL（旧结果已失效）。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from psycopg.types.json import Jsonb

from . import auth, db, repositories as repo
from .basket import build_latest_result
from .quant.basket import METHODS
from .repositories import _json_safe
from .schemas import BasketCopyIn, BasketSaveIn, BasketUpdateIn
from .settings import load_settings

_BASKET_COLUMNS = (
    "basket_id, owner_user_id, name, description, method, assets, params,"
    " latest_result, is_demo, display_order, created_at, updated_at"
)
_DEMO_ORDER = "ORDER BY display_order ASC NULLS LAST, basket_id ASC"
_ALL_ORDER = (
    "ORDER BY is_demo DESC,"
    " CASE WHEN is_demo THEN display_order END ASC NULLS LAST,"
    " updated_at DESC"
)
_SCOPES = ("demo", "mine")


def _basket_row(row, columns) -> dict:
    item = dict(zip(columns, row))
    return _json_safe(item)


def _fetch_basket(cur, basket_id: int) -> Optional[dict]:
    cur.execute(
        f"SELECT {_BASKET_COLUMNS} FROM bp_basket WHERE basket_id = %s",
        (basket_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _basket_row(row, [d.name for d in cur.description])


def _can_view(basket: dict, user: auth.UserContext | None) -> bool:
    """示例对所有人开放；非示例仅 owner / 管理员。"""
    if basket.get("is_demo"):
        return True
    if user is None or user.user_id is None:
        return False
    if user.is_admin:
        return True
    return basket.get("owner_user_id") == user.user_id


def _can_edit(basket: dict, user: auth.UserContext | None) -> bool:
    """示例仅管理员；非示例 owner 或管理员。"""
    if user is None or user.user_id is None:
        return False
    if user.is_admin:
        return True
    if basket.get("is_demo"):
        return False
    return basket.get("owner_user_id") == user.user_id


def _validate_scope(scope: Optional[str]) -> Optional[str]:
    if scope is None or scope == "":
        return None
    value = str(scope).strip().lower()
    if value not in _SCOPES:
        raise HTTPException(400, f"未知 scope={scope!r}（可选: demo / mine）")
    return value


def _parse_iso_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise HTTPException(400, f"非法日期: {value!r}") from exc


def _recompute_params(raw: Any) -> dict:
    """从 bp_basket.params 解析回测参数（与 /api/basket/backtest 同口径）。"""
    data = raw if isinstance(raw, dict) else {}
    try:
        lookback = int(data.get("lookback_days", 156))
    except (TypeError, ValueError):
        lookback = 156
    lookback = max(2, lookback)
    try:
        band = float(data.get("rebalance_band", 0.05))
    except (TypeError, ValueError):
        band = 0.05
    band = min(1.0, max(0.0, band))
    try:
        risk_free = float(data.get("risk_free", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk_free = 0.0
    budget = data.get("risk_budget")
    risk_budget = budget if isinstance(budget, dict) and budget else None
    start = _parse_iso_date(data.get("start"))
    end = _parse_iso_date(data.get("end"))
    if start is not None and end is not None and start > end:
        raise HTTPException(400, "start 不能晚于 end")
    return {
        "lookback_days": lookback,
        "rebalance_band": band,
        "risk_free": risk_free,
        "risk_budget": risk_budget,
        "start": start,
        "end": end,
    }


def register_routes(app: FastAPI) -> None:
    settings = load_settings()

    @app.get("/api/baskets")
    def list_baskets(
        scope: Optional[str] = None,
        user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        scope = _validate_scope(scope)
        with db.get_conn() as conn, conn.cursor() as cur:
            if user is None or user.user_id is None:
                # 匿名：仅示例；scope=mine 视为空（读操作不 401，前端可并行拉取后合并）
                if scope == "mine":
                    rows: list[dict] = []
                else:
                    cur.execute(
                        f"SELECT {_BASKET_COLUMNS} FROM bp_basket"
                        f" WHERE is_demo = TRUE {_DEMO_ORDER}"
                    )
                    rows = [
                        _basket_row(r, [d.name for d in cur.description])
                        for r in cur.fetchall()
                    ]
            elif scope == "demo":
                cur.execute(
                    f"SELECT {_BASKET_COLUMNS} FROM bp_basket"
                    f" WHERE is_demo = TRUE {_DEMO_ORDER}"
                )
                rows = [
                    _basket_row(r, [d.name for d in cur.description])
                    for r in cur.fetchall()
                ]
            elif scope == "mine":
                cur.execute(
                    f"SELECT {_BASKET_COLUMNS} FROM bp_basket"
                    " WHERE owner_user_id = %s AND is_demo = FALSE"
                    " ORDER BY updated_at DESC, basket_id DESC",
                    (user.user_id,),
                )
                rows = [
                    _basket_row(r, [d.name for d in cur.description])
                    for r in cur.fetchall()
                ]
            elif user.is_admin:
                cur.execute(f"SELECT {_BASKET_COLUMNS} FROM bp_basket {_ALL_ORDER}")
                rows = [
                    _basket_row(r, [d.name for d in cur.description])
                    for r in cur.fetchall()
                ]
            else:
                cur.execute(
                    f"SELECT {_BASKET_COLUMNS} FROM bp_basket"
                    " WHERE is_demo = TRUE OR owner_user_id = %s"
                    f" {_ALL_ORDER}",
                    (user.user_id,),
                )
                rows = [
                    _basket_row(r, [d.name for d in cur.description])
                    for r in cur.fetchall()
                ]
        return {"data": rows, "meta": {"rows": len(rows), "scope": scope}}

    @app.get("/api/baskets/{basket_id}")
    def get_basket(
        basket_id: int,
        user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        with db.get_conn() as conn, conn.cursor() as cur:
            basket = _fetch_basket(cur, basket_id)
        if basket is None:
            raise HTTPException(404, "篮子不存在")
        if not _can_view(basket, user):
            raise HTTPException(403, "无权查看该篮子")
        return {"data": basket}

    @app.post("/api/baskets")
    def create_basket(
        payload: BasketSaveIn,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        if user.user_id is None:
            raise HTTPException(401, "需要登录")
        assets = [{"symbol": a.symbol, "source": a.source} for a in payload.assets]
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bp_basket (owner_user_id, name, description, method, assets, params, latest_result)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
                " RETURNING basket_id, created_at, updated_at",
                (
                    user.user_id,
                    payload.name,
                    payload.description,
                    payload.method,
                    Jsonb(_json_safe(assets)),
                    Jsonb(_json_safe(payload.params or {})),
                    # 创建时忽略客户端 latest_result（防伪造）：新篮子的结果只能由
                    # 前端回测或管理员 recompute 生成。
                    None,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        return {"data": {"basket_id": row[0], "created_at": row[1], "updated_at": row[2]}}

    @app.patch("/api/baskets/{basket_id}")
    def update_basket(
        basket_id: int,
        payload: BasketUpdateIn,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        with db.get_conn() as conn, conn.cursor() as cur:
            basket = _fetch_basket(cur, basket_id)
            if basket is None:
                raise HTTPException(404, "篮子不存在")
            if not _can_edit(basket, user):
                raise HTTPException(403, "无权编辑该篮子")
            if basket.get("is_demo") and payload.latest_result is not None:
                raise HTTPException(
                    400,
                    "示例篮子的 latest_result 只能由 POST /api/baskets/{id}/recompute 生成",
                )
            # 示例篮子定义（资产/方法/参数）变更后旧的计算结果已失效：清空 latest_result，
            # 避免前端把旧结果当成新定义的结果展示（结果只能由 recompute 重新生成）。
            demo_definition_changed = bool(basket.get("is_demo")) and (
                payload.method is not None
                or payload.assets is not None
                or payload.params is not None
            )
            sets = []
            values = []
            if payload.name is not None:
                sets.append("name = %s")
                values.append(payload.name)
            if payload.description is not None:
                sets.append("description = %s")
                values.append(payload.description)
            if payload.method is not None:
                sets.append("method = %s")
                values.append(payload.method)
            if payload.assets is not None:
                sets.append("assets = %s::jsonb")
                values.append(
                    Jsonb(
                        _json_safe(
                            [{"symbol": a.symbol, "source": a.source} for a in payload.assets]
                        )
                    )
                )
            if payload.params is not None:
                sets.append("params = %s::jsonb")
                values.append(Jsonb(_json_safe(payload.params)))
            if payload.latest_result is not None:
                sets.append("latest_result = %s::jsonb")
                values.append(Jsonb(_json_safe(payload.latest_result)))
            elif demo_definition_changed:
                sets.append("latest_result = %s::jsonb")
                values.append(None)
            if not sets:
                return {"data": basket}
            sets.append("updated_at = now()")
            cur.execute(
                "UPDATE bp_basket SET " + ", ".join(sets) + " WHERE basket_id = %s RETURNING updated_at",
                (*values, basket_id),
            )
            row = cur.fetchone()
            conn.commit()
        return {"data": {"basket_id": basket_id, "updated_at": row[0]}}

    @app.post("/api/baskets/{basket_id}/copy")
    def copy_basket(
        basket_id: int,
        payload: BasketCopyIn | None = None,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        if user.user_id is None:
            raise HTTPException(401, "需要登录")
        with db.get_conn() as conn, conn.cursor() as cur:
            basket = _fetch_basket(cur, basket_id)
            if basket is None:
                raise HTTPException(404, "篮子不存在")
            if not _can_view(basket, user):
                raise HTTPException(403, "无权复制该篮子")
            new_name = (payload.name if payload else None) or (basket["name"] + " 副本")
            cur.execute(
                "INSERT INTO bp_basket (owner_user_id, name, description, method, assets, params, latest_result)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb) RETURNING basket_id",
                (
                    user.user_id,
                    new_name,
                    basket.get("description"),
                    basket.get("method"),
                    Jsonb(_json_safe(basket.get("assets"))),
                    Jsonb(_json_safe(basket.get("params"))),
                    Jsonb(_json_safe(basket.get("latest_result"))) if basket.get("latest_result") else None,
                ),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
        return {"data": {"basket_id": new_id}}

    @app.delete("/api/baskets/{basket_id}")
    def delete_basket(
        basket_id: int,
        user: auth.UserContext = Depends(auth.require_user),
    ) -> dict:
        with db.get_conn() as conn, conn.cursor() as cur:
            basket = _fetch_basket(cur, basket_id)
            if basket is None:
                raise HTTPException(404, "篮子不存在")
            if not _can_edit(basket, user):
                raise HTTPException(403, "无权删除该篮子")
            cur.execute("DELETE FROM bp_basket WHERE basket_id = %s", (basket_id,))
            conn.commit()
        return {"data": {"basket_id": basket_id, "deleted": True}}

    @app.post("/api/baskets/{basket_id}/recompute")
    def recompute_basket(
        basket_id: int,
        user: auth.UserContext = Depends(auth.require_super_admin),
    ) -> dict:
        """管理员服务端重算示例篮子 latest_result（同步；不落任务队列）。

        数据只读 bp_quote_clean（经 repositories.load_price_panel），参数取
        bp_basket.method / params；失败不写库、不伪造结果。
        """
        with db.get_conn() as conn, conn.cursor() as cur:
            basket = _fetch_basket(cur, basket_id)
            if basket is None:
                raise HTTPException(404, "篮子不存在")
            method = str(basket.get("method") or "")
            if method not in METHODS:
                raise HTTPException(400, f"未知优化方法 method={method!r}")
            pairs: list[tuple[str, str]] = []
            for asset in basket.get("assets") or []:
                if not isinstance(asset, dict):
                    continue
                symbol = str(asset.get("symbol") or "").strip()
                source = str(asset.get("source") or "").strip()
                if symbol and source:
                    pairs.append((symbol, source))
            if not pairs:
                raise HTTPException(400, "篮子没有有效资产")
            params = _recompute_params(basket.get("params"))
            try:
                panel = repo.load_price_panel(conn, pairs)
            except ValueError as exc:
                message = str(exc)
                status = 404 if "无清洗行情数据" in message else 400
                raise HTTPException(status, message) from exc
            if panel is None or panel.empty:
                raise HTTPException(400, "所选区间无清洗行情数据")
            try:
                summary = build_latest_result(
                    panel,
                    method=method,
                    lookback_days=params["lookback_days"],
                    rebalance_band=params["rebalance_band"],
                    risk_free=params["risk_free"],
                    risk_budget=params["risk_budget"],
                    start=params["start"],
                    end=params["end"],
                    trading_days=settings.trading_days,
                    min_window=settings.min_window,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            cur.execute(
                "UPDATE bp_basket SET latest_result = %s::jsonb, updated_at = now()"
                " WHERE basket_id = %s",
                (Jsonb(_json_safe(summary)), basket_id),
            )
            conn.commit()
        return {"data": {"basket_id": basket_id, "latest_result": summary}}

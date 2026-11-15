"""一篮子资产（basket）持久化 API：保存 / 列表 / 详情 / 编辑 / 复制 / 删除。

与象限组合（bp_portfolio）平级：/dashboard 同时展示两类组合。
鉴权：写操作需登录；读列表匿名返回空。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from psycopg.types.json import Jsonb

from . import auth, db
from .repositories import _json_safe
from .schemas import BasketCopyIn, BasketSaveIn, BasketUpdateIn


def _basket_row(row, columns) -> dict:
    item = dict(zip(columns, row))
    return _json_safe(item)


def _fetch_basket(cur, basket_id: int) -> Optional[dict]:
    cur.execute(
        "SELECT basket_id, owner_user_id, name, description, method, assets, params,"
        " latest_result, created_at, updated_at FROM bp_basket WHERE basket_id = %s",
        (basket_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _basket_row(row, [d.name for d in cur.description])


def _can_view(basket: dict, user: auth.UserContext | None) -> bool:
    if user is None:
        return False
    if user.is_admin:
        return True
    return basket.get("owner_user_id") == user.user_id


def _can_edit(basket: dict, user: auth.UserContext | None) -> bool:
    if user is None:
        return False
    return user.is_admin or basket.get("owner_user_id") == user.user_id


def register_routes(app: FastAPI) -> None:
    @app.get("/api/baskets")
    def list_baskets(
        user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        if user is None or user.user_id is None:
            return {"data": [], "meta": {"rows": 0}}
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT basket_id, owner_user_id, name, description, method, assets, params,"
                " latest_result, created_at, updated_at FROM bp_basket"
                " WHERE owner_user_id = %s ORDER BY updated_at DESC",
                (user.user_id,),
            )
            rows = [_basket_row(r, [d.name for d in cur.description]) for r in cur.fetchall()]
        return {"data": rows, "meta": {"rows": len(rows)}}

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
                    Jsonb(_json_safe(payload.latest_result)) if payload.latest_result else None,
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
                values.append(Jsonb(_json_safe([{"symbol": a.symbol, "source": a.source} for a in payload.assets])))
            if payload.params is not None:
                sets.append("params = %s::jsonb")
                values.append(Jsonb(_json_safe(payload.params)))
            if payload.latest_result is not None:
                sets.append("latest_result = %s::jsonb")
                values.append(Jsonb(_json_safe(payload.latest_result)))
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

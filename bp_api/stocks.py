"""个股搜索：全 A 股票主数据查询（供 /builder 与详情页选股用）。"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, Query

from . import auth, db


def register_routes(app: FastAPI) -> None:
    @app.get("/api/stocks/search")
    def stock_search(
        q: Optional[str] = Query(None, description="代码前缀或名称关键字"),
        industry: Optional[str] = Query(None, description="申万一级行业名"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        conditions = ["is_delisted = FALSE"]
        params: list = []
        if q:
            conditions.append("(stock_code LIKE %s OR name ILIKE %s)")
            params.extend([f"{q}%", f"%{q}%"])
        if industry:
            conditions.append("industry_l1 = %s")
            params.append(industry)
        where = " AND ".join(conditions)
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM bp_stock_master WHERE {where}", params)
            total = int(cur.fetchone()[0])
            cur.execute(
                f"SELECT stock_code, name, market, industry_l1, is_st FROM bp_stock_master "
                f"WHERE {where} ORDER BY stock_code LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            items = [
                {
                    "stock_code": row[0],
                    "name": row[1],
                    "market": row[2],
                    "industry_l1": row[3],
                    "is_st": row[4],
                    "sources": ["stock_sina", "stock_tx"],
                }
                for row in cur.fetchall()
            ]
        return {"data": items, "meta": {"total": total, "limit": limit, "offset": offset}}

    @app.get("/api/stocks/industries")
    def stock_industries(
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT industry_l1, count(*) FROM bp_stock_master "
                "WHERE industry_l1 IS NOT NULL AND is_delisted = FALSE "
                "GROUP BY industry_l1 ORDER BY count(*) DESC"
            )
            rows = cur.fetchall()
        return {
            "data": [{"industry": row[0], "count": int(row[1])} for row in rows],
            "meta": {"industries": len(rows)}
        }

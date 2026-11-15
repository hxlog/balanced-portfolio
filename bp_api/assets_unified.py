"""统一资产池 API：股票 / 指数 / 基金(ETF) 搜索 + 行情覆盖与三口径复权状态。"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Query

from . import auth, cache, db

CACHE_TTL_SECONDS = 60
ADJUST_LABELS = {"bfq": "不复权", "qfq": "前复权", "hfq": "后复权"}

def _envelope(data, **meta):
    return {"data": data, "meta": meta, "error": None}

def register_routes(app: FastAPI) -> None:
    @app.get("/api/assets/unified")
    def unified_assets(
        q: str | None = Query(None, max_length=50, description="代码/名称/拼音搜索"),
        type: str | None = Query(None, alias="type", max_length=10, description="stock/index/fund/etf"),
        market: str | None = Query(None, max_length=10, description="SH/SZ/BJ/CSI/HK/US"),
        adjust: str = Query("bfq", description="行情口径 bfq/qfq/hfq"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        _user: auth.UserContext = Depends(auth.require_asset_editor),
    ) -> dict:
        if adjust not in ADJUST_LABELS:
            adjust = "bfq"
        keyword = (q or "").strip()
        like = "%" + keyword + "%"
        kind = (type or "").strip() or None
        market_filter = (market or "").strip().upper() or None
        key = "assets_unified:" + "|".join([keyword, kind or "", market_filter or "", adjust, str(limit), str(offset)])
        hit = cache.get_json(key)
        if hit is not None:
            return hit
        params = {
            "like": like,
            "keyword": keyword,
            "adjust": adjust,
            "market": market_filter,
            "limit": limit,
            "offset": offset,
        }
        stock_union = """
            SELECT 'stock' AS type, m.stock_code AS code, m.name,
                   COALESCE(m.market, '') AS market, '' AS category,
                   c.last_date AS last_date, 3 AS adjust_count
            FROM bp_stock_master m
            LEFT JOIN bp_asset_coverage c
              ON c.kind = 'stock' AND c.code = m.stock_code AND c.adjust = %(adjust)s
            WHERE (%(keyword)s::text = '' OR m.stock_code LIKE %(like)s OR m.name ILIKE %(like)s)
              AND (%(market)s::text IS NULL OR upper(COALESCE(m.market, '')) = %(market)s::text)
        """
        index_union = """
            SELECT 'index' AS type, m.index_code AS code, m.name,
                   COALESCE(m.market, '') AS market, COALESCE(m.index_type, '') AS category,
                   c.last_date AS last_date, 1 AS adjust_count
            FROM bp_index_master m
            LEFT JOIN bp_asset_coverage c
              ON c.kind = 'index' AND c.code = m.index_code AND c.adjust = 'bfq'
            WHERE m.is_active AND m.is_tracked
              AND (%(keyword)s::text = '' OR m.index_code LIKE %(like)s OR m.name ILIKE %(like)s)
              AND (%(market)s::text IS NULL OR upper(COALESCE(m.market, '')) = %(market)s::text)
        """
        fund_union = """
            SELECT 'fund' AS type, f.fund_code AS code, f.name,
                   'CN' AS market, '' AS category,
                   c.last_date AS last_date, 1 AS adjust_count
            FROM bp_fund_master f
            LEFT JOIN bp_asset_coverage c
              ON c.kind = 'fund' AND c.code = f.fund_code AND c.adjust = ''
            WHERE (%(keyword)s::text = '' OR f.fund_code LIKE %(like)s OR f.name ILIKE %(like)s)
        """
        etf_union = """
            SELECT 'etf' AS type, f.fund_code AS code, f.name,
                   'CN' AS market, '' AS category,
                   c.last_date AS last_date, 1 AS adjust_count
            FROM bp_fund_master f
            LEFT JOIN bp_asset_coverage c
              ON c.kind = 'fund' AND c.code = f.fund_code AND c.adjust = ''
            WHERE f.is_etf AND (%(keyword)s::text = '' OR f.fund_code LIKE %(like)s OR f.name ILIKE %(like)s)
        """
        parts = []
        if kind in (None, "stock"):
            parts.append(stock_union)
        if kind in (None, "index"):
            parts.append(index_union)
        if kind in (None, "fund"):
            parts.append(fund_union)
        if kind in (None, "etf"):
            parts.append(etf_union)
        if not parts:
            return _envelope([], rows=0, total=0, limit=limit, offset=offset)
        union_sql = " UNION ALL ".join(parts)
        query = (
            "SELECT * FROM (" + union_sql + ") u ORDER BY u.last_date DESC NULLS LAST, u.code"
            " LIMIT %(limit)s OFFSET %(offset)s"
        )
        count_query = "SELECT count(*) FROM (" + union_sql + ") u"
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
            cur.execute(count_query, params)
            total = int(cur.fetchone()[0])
        items = []
        for row in rows:
            items.append({
                "type": row["type"],
                "code": row["code"],
                "name": row["name"],
                "market": row["market"],
                "category": row["category"],
                "last_date": row["last_date"].isoformat() if row["last_date"] else None,
                "adjust_available": row["type"] != "stock" or (row["adjust_count"] or 0) >= 1,
                "adjustments": [
                    {"value": "bfq", "label": "不复权"},
                    {"value": "qfq", "label": "前复权"},
                    {"value": "hfq", "label": "后复权"},
                ] if row["type"] == "stock" else [{"value": "bfq", "label": "不复权"}],
                "type_label": {"stock": "股票", "index": "指数", "fund": "基金", "etf": "ETF"}.get(row["type"], row["type"]),
            })
        payload = _envelope(
            items,
            rows=len(items),
            total=total,
            limit=limit,
            offset=offset,
            adjust=adjust,
            adjust_label=ADJUST_LABELS[adjust],
            backtest_adjust="hfq",
            backtest_adjust_label="后复权",
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

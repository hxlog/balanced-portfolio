"""加密合约看板 API（P5）：只读预计算表，请求路径不做计算。

数据由本机采集脚本（scripts/crypto_futures_collector.ps1，5 分钟一次）写入
bp_crypto_contract / bp_crypto_futures_snapshot_5m / bp_crypto_futures_percentile。
生产服务器不访问 Binance。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query

from . import auth, cache, db

CACHE_TTL_SECONDS = 60


def _json_safe(value):
    from .repositories import _json_safe as impl

    return impl(value)


def _envelope(data, **meta) -> dict:
    return {"data": _json_safe(data), "meta": meta, "error": None}


def _latest_snapshot_sql() -> str:
    return """
        SELECT DISTINCT ON (s.contract_code)
               s.contract_code, c.base_asset, c.oi_notional_rank,
               s.captured_at, s.mark_price, s.index_price, s.oi_contracts,
               s.oi_notional, s.long_short_ratio, s.taker_buy_sell_ratio, s.basis_pct
        FROM bp_crypto_futures_snapshot_5m s
        JOIN bp_crypto_contract c USING (contract_code)
        WHERE c.is_active AND c.oi_notional_rank IS NOT NULL
        ORDER BY s.contract_code, s.captured_at DESC
    """


def register_routes(app: FastAPI) -> None:
    @app.get("/api/crypto/futures/contracts")
    def crypto_futures_contracts(
        limit: int = Query(30, ge=1, le=60),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """合约榜：最新快照 + 30/90/180 日分位。"""
        key = f"crypto_futures:contracts:{limit}"
        hit = cache.get_json(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM (" + _latest_snapshot_sql() + ") t ORDER BY t.oi_notional DESC NULLS LAST LIMIT %s",
                (limit,),
            )
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT p.contract_code, p.metric, p.window_days, p.pct, p.sample_size, p.as_of
                FROM bp_crypto_futures_percentile p
                JOIN (
                    SELECT contract_code, metric, window_days, max(as_of) AS as_of
                    FROM bp_crypto_futures_percentile GROUP BY 1,2,3
                ) latest
                  ON latest.contract_code = p.contract_code
                 AND latest.metric = p.metric
                 AND latest.window_days = p.window_days
                 AND latest.as_of = p.as_of
                """
            )
            pct: dict[str, dict] = {}
            for code, metric, window, value, sample, as_of in cur.fetchall():
                pct.setdefault(code, {})[f"{metric}:{window}"] = {
                    "pct": float(value) if value is not None else None,
                    "sample_size": int(sample or 0),
                    "as_of": as_of.isoformat() if as_of else None,
                }
        for row in rows:
            row["percentiles"] = pct.get(row["contract_code"], {})
        payload = _envelope(rows, rows=len(rows), limit=limit)
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/crypto/futures/summary")
    def crypto_futures_summary(
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """汇总：总 OI 名义值、加权多空比、主动买卖比中位数、最近快照时间。"""
        key = "crypto_futures:summary"
        hit = cache.get_json(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM (" + _latest_snapshot_sql() + ") t")
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        total_oi = sum(r["oi_notional"] or 0 for r in rows)
        weighted_ls = None
        if total_oi > 0:
            weighted = sum((r["oi_notional"] or 0) * (r["long_short_ratio"] or 0) for r in rows)
            weighted_ls = weighted / total_oi
        taker_values = sorted(r["taker_buy_sell_ratio"] for r in rows if r["taker_buy_sell_ratio"])
        median_taker = None
        if taker_values:
            mid = len(taker_values) // 2
            median_taker = (
                taker_values[mid]
                if len(taker_values) % 2 == 1
                else (taker_values[mid - 1] + taker_values[mid]) / 2
            )
        latest_at = max((r["captured_at"] for r in rows if r["captured_at"]), default=None)
        payload = _envelope(
            {
                "contracts": len(rows),
                "total_oi_notional": total_oi,
                "weighted_long_short_ratio": weighted_ls,
                "median_taker_buy_sell_ratio": median_taker,
                "latest_captured_at": latest_at.isoformat() if latest_at else None,
            },
            rows=len(rows),
        )
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    @app.get("/api/crypto/futures/{contract_code}/series")
    def crypto_futures_series(
        contract_code: str,
        hours: int = Query(24, ge=1, le=720),
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """单合约 5 分钟序列（默认最近 24 小时）。"""
        code = contract_code.upper()
        key = f"crypto_futures:series:{code}:{hours}"
        hit = cache.get_json(key)
        if hit is not None:
            return hit
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM bp_crypto_contract WHERE contract_code = %s",
                (code,),
            )
            if cur.fetchone() is None:
                raise HTTPException(404, "contract_not_found")
            cur.execute(
                """
                SELECT captured_at, mark_price, oi_notional, long_short_ratio,
                       taker_buy_sell_ratio, basis_pct
                FROM bp_crypto_futures_snapshot_5m
                WHERE contract_code = %s AND captured_at >= now() - make_interval(hours => %s)
                ORDER BY captured_at
                """,
                (code, hours),
            )
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        payload = _envelope(rows, rows=len(rows), contract_code=code, hours=hours)
        cache.set_json(key, payload, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

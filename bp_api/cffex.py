"""CFFEX 股指期货看板 — API 端点。

三个接口:
  GET /api/cffex/spot       最新收盘快照 (Redis 30min 缓存, 纯 DB 读)
  GET /api/cffex/history    历史年化升贴水率走势 (支持 days 或 start_date/end_date)
  GET /api/cffex/statistics 统计分位表

无鉴权要求 (公开页面)。

数据更新机制: bp_ingest 调度器每 BP_CFFEX_SYNC_HOURS 小时增量拉取 CFFEX 日行情
(akshare get_futures_daily) 落库; 有新交易日则重算 premium, 否则跳过。
看板快照仅使用「期货与挂钩指数同日齐全」的最近交易日, 禁止混日基差。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from . import cache, db

# 注意: bp_ingest 的导入放到函数内(lazy import), 避免模块级导入触发 uvicorn reload loop

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 本地常量 (避免跨包模块级导入)
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))

CFFEX_VARIETIES = ["IF", "IH", "IC", "IM"]

VARIETY_NAMES: dict[str, str] = {
    "IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000",
}

INDEX_QUOTE_MAP: dict[str, str] = {
    "IF": "000300", "IH": "000016", "IC": "000905", "IM": "000852",
}

CFFEX_INDEX_SYMBOLS = list(INDEX_QUOTE_MAP.values())

CONTRACT_TYPE_ORDER = {"当月": 0, "次月": 1, "当季": 2, "次季": 3}

_PERIOD_DAYS = {
    "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260,
}

CFFEX_SPOT_CACHE_KEY = "cffex:spot:closed"


def _spot_cache_key() -> str:
    """盘前/盘后分桶, 避免 15:10 前后共用同一缓存快照。"""
    from bp_ingest.calendar import session_close_confirmed_at

    suffix = "post" if session_close_confirmed_at() else "pre"
    return f"{CFFEX_SPOT_CACHE_KEY}:{suffix}"


def _lazy_cmap():
    """Lazy-import cffex_contract_map (避免 uvicorn reload loop)。"""
    from bp_ingest.cffex_contract_map import (
        Contract, days_to_expiry, map_contracts_from_symbols,
    )
    return Contract, days_to_expiry, map_contracts_from_symbols


def invalidate_cffex_spot_cache() -> None:
    """期货/现货入库后失效看板快照缓存。"""
    cache.delete(CFFEX_SPOT_CACHE_KEY)
    cache.delete(f"{CFFEX_SPOT_CACHE_KEY}:pre")
    cache.delete(f"{CFFEX_SPOT_CACHE_KEY}:post")
    cache.delete_pattern("cffex:history:*")
    cache.delete_pattern("cffex:stats:*")


def pick_effective_trade_date(
    candidate_dates: list[date],
    futures_varieties_by_date: dict[date, set[str]],
    spot_symbols_by_date: dict[date, set[str]],
    required_varieties: list[str] | None = None,
    required_spot_symbols: list[str] | None = None,
    *,
    max_confirmed_date: date | None = None,
) -> Optional[date]:
    """最近一个「四品种期货齐全且四挂钩指数同日有收盘」的交易日。

    纯函数, 便于单测。candidate_dates 须降序。
    max_confirmed_date: 若给定, 只考虑 <= 该日的候选(排除未确认收盘的今日)。
    """
    vars_need = set(required_varieties or CFFEX_VARIETIES)
    spots_need = set(required_spot_symbols or CFFEX_INDEX_SYMBOLS)
    for d in candidate_dates:
        if max_confirmed_date is not None and d > max_confirmed_date:
            continue
        if not vars_need.issubset(futures_varieties_by_date.get(d, set())):
            continue
        if not spots_need.issubset(spot_symbols_by_date.get(d, set())):
            continue
        return d
    return None


# ---------------------------------------------------------------------------
# 收盘快照 (纯 DB 读)
# ---------------------------------------------------------------------------

def _index_closes_post_confirmed(
    cur,
    trade_date: date,
    *,
    now: datetime,
) -> bool:
    """四挂钩指数在 trade_date 的原始行情是否均在收盘确认时刻之后写入。

    只看 bp_index_quote_daily(抓取落库时间)。bp_quote_clean 的 updated_at
    会在 rebuild 时被刷新, 即使 close 仍是盘中脏价, 不能当作收盘确认证据。
    历史日(早于今天)直接通过。
    """
    from bp_ingest.calendar import close_confirm_deadline, now_cst

    wall = now_cst(now)
    if trade_date < wall.date():
        return True
    deadline = close_confirm_deadline(trade_date)
    cur.execute(
        """
        SELECT symbol, MAX(updated_at) AS ua
        FROM bp_index_quote_daily
        WHERE symbol = ANY(%s) AND trade_date = %s
        GROUP BY symbol
        """,
        (CFFEX_INDEX_SYMBOLS, trade_date),
    )
    rows = cur.fetchall()
    by_sym = {r[0]: r[1] for r in rows}
    for sym in CFFEX_INDEX_SYMBOLS:
        ua = by_sym.get(sym)
        if ua is None:
            return False
        if ua.tzinfo is None:
            ua = ua.replace(tzinfo=CST)
        else:
            ua = ua.astimezone(CST)
        if ua < deadline:
            return False
    return True


def _build_closing_snapshot() -> dict:
    Contract, days_to_expiry, map_contracts_from_symbols = _lazy_cmap()
    from bp_ingest.calendar import (
        is_trade_date_close_confirmed,
        now_cst,
        session_close_confirmed_at,
    )

    now = now_cst()
    today = now.date()
    # 未确认收盘时, 看板最多展示到昨日(即使库中已有今日脏行)
    max_confirmed: date | None = today
    if not is_trade_date_close_confirmed(today, now=now, today=today):
        max_confirmed = today - timedelta(days=1)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT trade_date
                FROM bp_cffex_contract_daily
                WHERE trade_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY trade_date DESC
            """)
            candidate_dates = [r[0] for r in cur.fetchall()]
            if not candidate_dates:
                return {
                    "trading_status": "closed", "indices": [], "contracts": [],
                    "fetched_at": now.isoformat(), "source": "db_empty",
                    "is_synced": False,
                    "close_confirmed": session_close_confirmed_at(now),
                }

            futures_latest: date = candidate_dates[0]
            lookback_start = candidate_dates[-1]

            # 各日具备的期货品种
            cur.execute("""
                SELECT trade_date, variety
                FROM bp_cffex_contract_daily
                WHERE trade_date >= %s AND variety = ANY(%s)
                GROUP BY trade_date, variety
            """, (lookback_start, CFFEX_VARIETIES))
            futures_varieties_by_date: dict[date, set[str]] = {}
            for td, var in cur.fetchall():
                futures_varieties_by_date.setdefault(td, set()).add(var)

            # 各日具备的挂钩指数 (精确 trade_date, 禁止 MAX<= 混日)
            cur.execute("""
                SELECT trade_date, symbol FROM (
                    SELECT trade_date, symbol FROM bp_quote_clean
                    WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s
                    UNION
                    SELECT trade_date, symbol FROM bp_index_quote_daily
                    WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s
                ) sub
            """, (
                CFFEX_INDEX_SYMBOLS, lookback_start, futures_latest,
                CFFEX_INDEX_SYMBOLS, lookback_start, futures_latest,
            ))
            spot_symbols_by_date: dict[date, set[str]] = {}
            for td, sym in cur.fetchall():
                spot_symbols_by_date.setdefault(td, set()).add(sym)

            spot_latest: date | None = None
            for d in candidate_dates:
                if max_confirmed is not None and d > max_confirmed:
                    continue
                if set(CFFEX_INDEX_SYMBOLS).issubset(spot_symbols_by_date.get(d, set())):
                    spot_latest = d
                    break

            effective_td = pick_effective_trade_date(
                candidate_dates, futures_varieties_by_date, spot_symbols_by_date,
                max_confirmed_date=max_confirmed,
            )
            # 今日行若仍是收盘确认前写入的脏价, 继续回退到更早完整日
            while effective_td is not None and not _index_closes_post_confirmed(
                cur, effective_td, now=now
            ):
                logger.warning(
                    "CFFEX spot: %s 指数收盘价尚未经收盘后确认, 回退候选日",
                    effective_td,
                )
                earlier = [d for d in candidate_dates if d < effective_td]
                effective_td = pick_effective_trade_date(
                    earlier, futures_varieties_by_date, spot_symbols_by_date,
                    max_confirmed_date=max_confirmed,
                )
            if effective_td is None:
                return {
                    "trading_status": "closed", "indices": [], "contracts": [],
                    "fetched_at": now.isoformat(), "source": "db_no_synced_day",
                    "futures_latest": futures_latest.isoformat(),
                    "spot_latest": spot_latest.isoformat() if spot_latest else None,
                    "is_synced": False,
                    "close_confirmed": session_close_confirmed_at(now),
                }

            is_synced = futures_latest == effective_td
            # 前一交易日(用于指数涨跌幅): 候选日中严格早于 effective_td 的最近一日
            prev_td = next((d for d in candidate_dates if d < effective_td), None)
            if prev_td is None:
                prev_td = effective_td - timedelta(days=1)

            index_price_map: dict[str, float] = {}
            indices_out = []
            for variety in CFFEX_VARIETIES:
                idx_sym = INDEX_QUOTE_MAP.get(variety)
                pt = None
                prev_pt = None
                if idx_sym:
                    cur.execute("""
                        SELECT close FROM bp_quote_clean
                        WHERE symbol = %s AND trade_date = %s
                        LIMIT 1
                    """, (idx_sym, effective_td))
                    r = cur.fetchone()
                    if not r:
                        cur.execute("""
                            SELECT close FROM bp_index_quote_daily
                            WHERE symbol = %s AND trade_date = %s
                            ORDER BY updated_at DESC NULLS LAST
                            LIMIT 1
                        """, (idx_sym, effective_td))
                        r = cur.fetchone()
                    if r:
                        pt = float(r[0])

                    cur.execute("""
                        SELECT close FROM bp_quote_clean
                        WHERE symbol = %s AND trade_date = %s
                        LIMIT 1
                    """, (idx_sym, prev_td))
                    r = cur.fetchone()
                    if not r:
                        cur.execute("""
                            SELECT close FROM bp_index_quote_daily
                            WHERE symbol = %s AND trade_date = %s
                            ORDER BY updated_at DESC NULLS LAST
                            LIMIT 1
                        """, (idx_sym, prev_td))
                        r = cur.fetchone()
                    if r:
                        prev_pt = float(r[0])

                change_pct = (
                    (pt - prev_pt) / prev_pt * 100
                    if pt is not None and prev_pt is not None and prev_pt != 0 else None
                )
                index_price_map[variety] = pt or 0.0
                indices_out.append({
                    "variety": variety, "name": VARIETY_NAMES.get(variety, variety),
                    "current_point": round(pt, 2) if pt is not None else None,
                    "change_pct": round(change_pct, 2) if change_pct is not None else None,
                    "prev_close": round(prev_pt, 2) if prev_pt is not None else None,
                })

            cur.execute("""
                SELECT symbol, variety, close, settle, volume, open_interest
                FROM bp_cffex_contract_daily
                WHERE trade_date = %s AND variety = ANY(%s)
                ORDER BY variety, symbol
            """, (effective_td, CFFEX_VARIETIES))
            rows = cur.fetchall()

            contracts_by_variety: dict[str, list[str]] = {}
            contract_data: dict[str, dict] = {}
            for sym, var, close_val, settle_val, vol, oi in rows:
                contracts_by_variety.setdefault(var, []).append(sym)
                contract_data[sym] = {
                    "variety": var, "close": float(close_val) if close_val else 0.0,
                    "settle": float(settle_val) if settle_val else None,
                    "volume": int(vol) if vol else None,
                    "open_interest": float(oi) if oi else None,
                }

            global_ctype_map: dict[str, str] = {}
            for var, syms in contracts_by_variety.items():
                var_types = map_contracts_from_symbols(syms, effective_td)
                global_ctype_map.update(var_types)
                logger.info("DB snapshot %s contracts: %s → %s", var, syms, var_types)

            contracts_out = []
            for sym, data in contract_data.items():
                var = data["variety"]
                spot_pt = index_price_map.get(var, 0.0)
                fp = data["close"]
                st = data["settle"]
                dte = days_to_expiry(sym, effective_td) or 0
                # 仅同日现货存在时计算基差 (effective_td 已保证四指数齐全)
                basis = spot_pt - fp if spot_pt else None
                premium_rate = (
                    (-basis / spot_pt * 100)
                    if basis is not None and spot_pt != 0 else None
                )
                ann_premium_rate = (
                    (premium_rate * 365 / dte)
                    if premium_rate is not None and dte > 0 else None
                )

                contracts_out.append({
                    "symbol": sym, "raw_symbol": sym, "variety": var,
                    "contract_type": global_ctype_map.get(sym, "未知"),
                    "current_price": round(fp, 2) if fp else None,
                    "settle": round(st, 2) if st else None,
                    "open": None, "high": None, "low": None,
                    "volume": data["volume"], "hold": data["open_interest"], "amount": None,
                    "days_to_expiry": dte,
                    "basis": round(basis, 2) if basis is not None else None,
                    "premium_rate": round(premium_rate, 2) if premium_rate is not None else None,
                    "ann_premium_rate": round(ann_premium_rate, 2) if ann_premium_rate is not None else None,
                })

    contracts_out.sort(key=lambda x: (
        CFFEX_VARIETIES.index(x["variety"]) if x["variety"] in CFFEX_VARIETIES else 99,
        CONTRACT_TYPE_ORDER.get(x.get("contract_type", ""), 99),
    ))

    close_ok = is_trade_date_close_confirmed(effective_td, now=now, today=today)
    return {
        "trading_status": "closed",
        "indices": indices_out,
        "contracts": contracts_out,
        "fetched_at": now.isoformat(),
        "source": f"db_close_{effective_td.isoformat()}",
        "data_date": effective_td.isoformat(),
        "as_of": f"{effective_td.isoformat()} 15:00:00",
        "futures_latest": futures_latest.isoformat(),
        "spot_latest": spot_latest.isoformat() if spot_latest else None,
        "is_synced": is_synced,
        "close_confirmed": close_ok,
    }


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------

def _handle_spot() -> dict:
    """最新收盘快照: Redis 30min 缓存, 未命中则从 DB 构建并回写。"""
    key = _spot_cache_key()
    cached = cache.get_json(key)
    if cached is not None:
        return cached
    data = _build_closing_snapshot()
    if data.get("contracts"):
        cache.set_json(key, data, ttl_seconds=1800)
    return data


def _handle_history(
    variety: str | None = None,
    days: int = 750,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """历史年化升贴水率走势。date_mode + days_mode 二选一。"""
    cache_key = f"cffex:history:{variety or 'all'}:{days}:{start_date}:{end_date}"
    cached = cache.get_json(cache_key)
    if cached is not None:
        return cached

    varieties = [variety] if variety else CFFEX_VARIETIES[:]
    varieties = [v for v in varieties if v in CFFEX_VARIETIES]

    # Phase 1: 收集每个品种的原始数据 + 构建统一日期轴
    raw_series: dict[str, dict[str, float | None]] = {}   # raw_series[var][date_str] = composite_rate
    raw_index: dict[str, dict[str, float]] = {}             # raw_index[var][date_str] = index_close
    all_dates: set[str] = set()

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for var in varieties:
                raw_series[var] = {}
                raw_index[var] = {}

                # --- 单次查询 bp_cffex_premium_daily (普通表, 非 hypertable) 同时取 composite_rate + spot_price ---
                # 避免读 bp_quote_clean/bp_index_quote_daily 这两张 1200+ chunk 的 hypertable
                # 导致 "out of shared memory / max_locks_per_transaction" 锁溢出。
                # spot_price 即挂钩指数当日收盘价, 与 hypertable 的 close 等价; 覆盖 2017-起全部历史。
                if days <= 0:
                    cur.execute("""
                        SELECT trade_date, composite_rate, spot_price
                        FROM bp_cffex_premium_daily
                        WHERE variety = %s AND contract_type = '当月'
                          AND composite_rate IS NOT NULL
                        ORDER BY trade_date
                    """, (var,))
                elif start_date and end_date:
                    cur.execute("""
                        SELECT trade_date, composite_rate, spot_price
                        FROM bp_cffex_premium_daily
                        WHERE variety = %s AND contract_type = '当月'
                          AND composite_rate IS NOT NULL
                          AND trade_date BETWEEN %s AND %s
                        ORDER BY trade_date
                    """, (var, start_date, end_date))
                else:
                    cur.execute("""
                        SELECT trade_date, composite_rate, spot_price
                        FROM bp_cffex_premium_daily
                        WHERE variety = %s AND contract_type = '当月'
                          AND composite_rate IS NOT NULL
                          AND trade_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
                        ORDER BY trade_date
                    """, (var, days))
                for r in cur.fetchall():
                    ds = str(r[0])
                    raw_series[var][ds] = float(r[1]) if r[1] is not None else None
                    if r[2] is not None:
                        raw_index[var][ds] = float(r[2])
                    all_dates.add(ds)

    # Phase 2: 对齐 — 所有品种的数据按统一日期轴展开
    sorted_dates = sorted(all_dates)
    result: dict = {"dates": sorted_dates, "series": {}}

    for var in varieties:
        series_data = raw_series.get(var, {})
        index_data = raw_index.get(var, {})
        rates = [series_data.get(d) for d in sorted_dates]
        prices = [index_data.get(d) for d in sorted_dates]
        result["series"][var] = {
            "name": VARIETY_NAMES.get(var, var),
            "ann_premium_rates": rates,
            "index_prices": prices,
        }

    cache.set_json(cache_key, result, ttl_seconds=3600)
    return result


def _handle_statistics(
    variety: str | None = None,
    period: str = "3Y",
) -> dict:
    cache_key = f"cffex:stats:{variety or 'all'}:{period}"
    cached = cache.get_json(cache_key)
    if cached is not None:
        return cached

    lookback = _PERIOD_DAYS.get(period, 756)
    varieties = [variety] if variety else CFFEX_VARIETIES[:]
    varieties = [v for v in varieties if v in CFFEX_VARIETIES]

    stats = []
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for var in varieties:
                cur.execute("""
                    SELECT composite_rate FROM bp_cffex_premium_daily
                    WHERE variety = %s AND contract_type = '当月'
                      AND composite_rate IS NOT NULL
                      AND trade_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
                    ORDER BY trade_date
                """, (var, lookback))
                rows = cur.fetchall()
                if not rows:
                    continue
                values = sorted(float(r[0]) for r in rows if r[0] is not None)
                if not values:
                    continue

                n = len(values)
                mean_val = sum(values) / n
                variance = sum((x - mean_val) ** 2 for x in values) / n
                std_val = variance ** 0.5 if variance > 0 else 0.0

                def _percentile(vals: list[float], p: float) -> float:
                    k = (len(vals) - 1) * p
                    f = int(k); c = k - f
                    if f + 1 < len(vals):
                        return vals[f] + c * (vals[f + 1] - vals[f])
                    return vals[f]

                stats.append({
                    "variety": var, "name": VARIETY_NAMES.get(var, var),
                    "count": n, "min": round(values[0], 2), "max": round(values[-1], 2),
                    "p10": round(_percentile(values, 0.10), 2),
                    "p30": round(_percentile(values, 0.30), 2),
                    "p50": round(_percentile(values, 0.50), 2),
                    "p70": round(_percentile(values, 0.70), 2),
                    "p90": round(_percentile(values, 0.90), 2),
                    "mean": round(mean_val, 2), "std": round(std_val, 2),
                })

    result = {"period": period, "statistics": stats}
    cache.set_json(cache_key, result, ttl_seconds=3600)
    return result


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

def register_routes(app: FastAPI) -> None:

    @app.get("/api/cffex/spot")
    def cffex_spot() -> dict:
        try:
            return _handle_spot()
        except Exception as exc:
            logger.error("cffex/spot 异常: %s", exc)
            raise HTTPException(500, f"获取行情数据失败: {exc}")

    @app.get("/api/cffex/history")
    def cffex_history(
        variety: str | None = Query(None, description="品种: IF/IH/IC/IM"),
        days: int = Query(750, ge=0, le=3650, description="回溯天数 (0=全量, 默认750)"),
        start_date: str | None = Query(None, description="起始日 YYYY-MM-DD (与 end_date 配用)"),
        end_date: str | None = Query(None, description="截止日 YYYY-MM-DD"),
    ) -> dict:
        if variety and variety not in CFFEX_VARIETIES:
            raise HTTPException(400, f"无效品种: {variety}")
        try:
            return _handle_history(variety=variety, days=days,
                                   start_date=start_date, end_date=end_date)
        except Exception as exc:
            logger.error("cffex/history 异常: %s", exc)
            raise HTTPException(500, f"查询历史数据失败: {exc}")

    @app.get("/api/cffex/statistics")
    def cffex_statistics(
        variety: str | None = Query(None, description="品种过滤"),
        period: str = Query("3Y", description="统计周期: 3M/6M/1Y/3Y/5Y"),
    ) -> dict:
        if variety and variety not in CFFEX_VARIETIES:
            raise HTTPException(400, f"无效品种: {variety}")
        if period not in _PERIOD_DAYS:
            raise HTTPException(400, f"无效周期: {period}")
        try:
            return _handle_statistics(variety=variety, period=period)
        except Exception as exc:
            logger.error("cffex/statistics 异常: %s", exc)
            raise HTTPException(500, f"查询统计失败: {exc}")

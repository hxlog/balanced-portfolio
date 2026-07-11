"""场外衍生品数据访问层: 交易日历 / 挂钩指数 / 历史波动率 / 簿记 CRUD。

全部 psycopg3 原生 SQL, 与 bp_api.repositories 风格一致。
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg
from psycopg.types.json import Json

from . import cache
from .quant.otc.calendar import TradingCalendarView
from .quant.otc.holidays import is_estimated_cn_holiday

logger = logging.getLogger(__name__)

MARKET = "CN"
CALENDAR_FLOOR = date(2019, 1, 1)      # 历史下界(覆盖存续簿记回看)
CALENDAR_YEARS_AHEAD = 2               # 未来外推年数
_OTC_DEAL_RESULT_TTL = 86400           # Redis 单簿记 last_result 缓存 24h


def _deal_result_cache_key(deal_id: int) -> str:
    return f"otc:deal:{deal_id}:result"


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if obj is None or isinstance(obj, (int, bool, str)):
        return obj
    try:
        f = float(obj)
    except (TypeError, ValueError):
        return obj
    return None if (math.isnan(f) or math.isinf(f)) else f


# ---------------------------------------------------------------------------
# 交易日历
# ---------------------------------------------------------------------------
def _load_akshare_trading_days() -> list[date]:
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    col = df.columns[0]
    days: list[date] = []
    for v in df[col].tolist():
        if isinstance(v, datetime):
            days.append(v.date())
        elif isinstance(v, date):
            days.append(v)
        else:
            try:
                days.append(date.fromisoformat(str(v)[:10]))
            except ValueError:
                continue
    return sorted(set(days))


def refresh_trading_calendar(conn: psycopg.Connection, years_ahead: int = CALENDAR_YEARS_AHEAD) -> dict:
    """从 akshare 拉官方交易日 + 去周末外推补足未来, upsert 到 bp_trading_calendar。

    不覆盖 confidence='custom' 的行(用户手工调整优先)。
    """
    official = _load_akshare_trading_days()
    if not official:
        raise RuntimeError("akshare 未返回交易日历")
    official_set = set(official)
    official_max = max(official)
    ceil = date.today() + timedelta(days=365 * years_ahead + 5)

    rows: list[tuple] = []
    d = CALENDAR_FLOOR
    n_official = n_estimated = 0
    while d <= ceil:
        if d in official_set:
            rows.append((MARKET, d, True, "official", None))
            n_official += 1
        elif d <= official_max:
            rows.append((MARKET, d, False, "official", None))
        else:
            is_tr = d.weekday() < 5 and not is_estimated_cn_holiday(d)
            rows.append((MARKET, d, is_tr, "estimated", None))
            if is_tr:
                n_estimated += 1
        d += timedelta(days=1)

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO bp_trading_calendar (market, cal_date, is_trading, confidence, note)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (market, cal_date) DO UPDATE
                 SET is_trading = EXCLUDED.is_trading,
                     confidence = EXCLUDED.confidence,
                     note = EXCLUDED.note,
                     updated_at = now()
               WHERE bp_trading_calendar.confidence <> 'custom'""",
            rows,
        )
    logger.info("交易日历刷新: 官方交易日 %d, 预估交易日 %d, 至 %s", n_official, n_estimated, ceil)
    return {"official_trading_days": n_official, "estimated_trading_days": n_estimated,
            "through": ceil.isoformat(), "official_max": official_max.isoformat()}


def _calendar_count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bp_trading_calendar WHERE market=%s", (MARKET,))
        return int(cur.fetchone()[0])


def ensure_calendar(conn: psycopg.Connection) -> None:
    """空表则尝试刷新(best-effort, 失败不抛)。"""
    try:
        if _calendar_count(conn) == 0:
            refresh_trading_calendar(conn)
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_calendar 刷新失败(忽略): %s", exc)


def get_calendar(conn: psycopg.Connection, dfrom: date, dto: date) -> list[dict]:
    ensure_calendar(conn)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT cal_date, is_trading, confidence FROM bp_trading_calendar
               WHERE market=%s AND cal_date BETWEEN %s AND %s ORDER BY cal_date""",
            (MARKET, dfrom, dto),
        )
        rows = cur.fetchall()
    return [{"date": r[0].isoformat(), "is_trading": bool(r[1]), "confidence": r[2]} for r in rows]


def load_calendar_view(
    conn: psycopg.Connection, start: date, end: date
) -> TradingCalendarView:
    """构建 [start-buffer, end+buffer] 内交易日的视图, 供定价引擎使用。

    DB 为空则退化到 akshare, 再退化到工作日。
    """
    lo = min(start, CALENDAR_FLOOR) - timedelta(days=5)
    hi = end + timedelta(days=5)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT cal_date FROM bp_trading_calendar
               WHERE market=%s AND is_trading AND cal_date BETWEEN %s AND %s ORDER BY cal_date""",
            (MARKET, lo, hi),
        )
        days = [r[0] for r in cur.fetchall()]
    if days:
        return TradingCalendarView(days)
    # fallback 1: akshare
    try:
        aks = [d for d in _load_akshare_trading_days() if lo <= d <= hi]
        if aks:
            return TradingCalendarView(aks)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_calendar_view akshare 回退失败: %s", exc)
    # fallback 2: 工作日
    gen = []
    d = lo
    while d <= hi:
        if d.weekday() < 5:
            gen.append(d)
        d += timedelta(days=1)
    return TradingCalendarView(gen)


# ---------------------------------------------------------------------------
# 挂钩指数 + 历史波动率
# ---------------------------------------------------------------------------
def list_underlyings(conn: psycopg.Connection) -> list[dict]:
    """可选挂钩指数 = is_selectable 且 asset_class 含 'index' (排除期货/ETF/债/商品)。"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.symbol, c.source, c.name, s.asset_class
               FROM bp_index_config c JOIN bp_data_source s ON c.source = s.code
               WHERE c.is_deleted = 0 AND c.is_selectable = TRUE
                 AND s.asset_class LIKE '%%index%%'
               ORDER BY c.symbol"""
        )
        rows = cur.fetchall()
    return [{"symbol": r[0], "source": r[1], "name": r[2], "asset_class": r[3]} for r in rows]


def resolve_source(conn: psycopg.Connection, symbol: str, source: Optional[str]) -> Optional[str]:
    if source:
        return source
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.source FROM bp_index_config c JOIN bp_data_source s ON c.source=s.code
               WHERE c.symbol=%s AND c.is_deleted=0 AND s.asset_class LIKE '%%index%%'
               ORDER BY c.is_selectable DESC LIMIT 1""",
            (symbol,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def load_close_series(
    conn: psycopg.Connection, symbol: str, source: str,
    start: Optional[date] = None, end: Optional[date] = None,
) -> pd.Series:
    q = "SELECT trade_date, close FROM bp_quote_clean WHERE symbol=%s AND source=%s"
    params: list = [symbol, source]
    if start:
        q += " AND trade_date >= %s"; params.append(start)
    if end:
        q += " AND trade_date <= %s"; params.append(end)
    q += " ORDER BY trade_date"
    with conn.cursor() as cur:
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.to_datetime([r[0] for r in rows])
    vals = [float(r[1]) for r in rows]
    return pd.Series(vals, index=idx, name=symbol)


def historical_volatility(
    conn: psycopg.Connection, symbols: list[str],
    windows: list[int], source: Optional[str] = None, max_points: int = 1260,
    trading_days: int = 252,
) -> dict:
    """各指数 90/120/180/365 交易日滚动年化波动率(对数收益, √trading_days 年化)。

    默认 max_points≈1260 (~5 年 × 252), 前端可再截取近 3 年展示。
    """
    out: dict[str, dict] = {}
    for sym in symbols:
        src = resolve_source(conn, sym, source)
        if not src:
            continue
        s = load_close_series(conn, sym, src)
        if s.empty or len(s) < 5:
            continue
        logret = np.log(s / s.shift(1))
        name = None
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM bp_index_config WHERE symbol=%s AND source=%s", (sym, src))
            r = cur.fetchone()
            if r:
                name = r[0]
        series_by_window: dict[str, list] = {}
        for w in windows:
            vol = logret.rolling(w).std() * math.sqrt(trading_days)
            vol = vol.dropna()
            if vol.empty:
                series_by_window[str(w)] = []
                continue
            if len(vol) > max_points:
                vol = vol.iloc[-max_points:]
            series_by_window[str(w)] = [
                {"date": ts.date().isoformat(), "vol": round(float(v), 6)}
                for ts, v in vol.items()
            ]
        out[sym] = {"symbol": sym, "source": src, "name": name, "windows": series_by_window}
    return out


def realized_vol_estimate(
    conn: psycopg.Connection, symbol: str, source: str, window: int = 90,
    trading_days: int = 252,
) -> Optional[float]:
    """挂钩标的最近 window 交易日年化波动率(用于波动率默认值)。"""
    s = load_close_series(conn, symbol, source)
    if s.empty or len(s) < window + 1:
        return None
    logret = np.log(s / s.shift(1)).dropna()
    if len(logret) < window:
        return None
    vol = float(logret.iloc[-window:].std() * math.sqrt(trading_days))
    return round(vol, 6) if not (math.isnan(vol) or math.isinf(vol)) else None


# ---------------------------------------------------------------------------
# 簿记 CRUD
# ---------------------------------------------------------------------------
_DEAL_COLS = (
    "deal_id, name, product_type, engine, underlying_symbol, underlying_source, terms, "
    "is_example, owner_user_id, last_price, last_present_notional, last_greeks, last_status, last_valued_at, "
    "last_result, created_at, updated_at"
)
_DEAL_COLS_D = (
    "d.deal_id, d.name, d.product_type, d.engine, d.underlying_symbol, d.underlying_source, d.terms, "
    "d.is_example, d.owner_user_id, d.last_price, d.last_present_notional, d.last_greeks, d.last_status, "
    "d.last_valued_at, d.last_result, d.created_at, d.updated_at"
)
_DEAL_ORDER_CLAUSE = (
    "ORDER BY d.is_example DESC, COALESCE(o.display_order, 2147483647) ASC, d.deal_id DESC"
)


def _row_to_deal(row) -> dict:
    def iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    return {
        "deal_id": row[0], "name": row[1], "product_type": row[2], "engine": row[3],
        "underlying_symbol": row[4], "underlying_source": row[5], "terms": row[6] or {},
        "is_example": bool(row[7]), "owner_user_id": row[8],
        "last_price": float(row[9]) if row[9] is not None else None,
        "last_present_notional": float(row[10]) if row[10] is not None else None,
        "last_greeks": row[11] or None, "last_status": row[12],
        "last_valued_at": iso(row[13]), "last_result": row[14] or None,
        "created_at": iso(row[15]), "updated_at": iso(row[16]),
    }


def list_otc_deals(conn: psycopg.Connection, user_id: Optional[int], is_admin: bool) -> list[dict]:
    with conn.cursor() as cur:
        if is_admin and user_id is not None:
            cur.execute(
                f"""SELECT {_DEAL_COLS_D}
                    FROM bp_otc_deal d
                    LEFT JOIN bp_user_otc_deal_order o
                      ON o.deal_id = d.deal_id AND o.user_id = %s
                    {_DEAL_ORDER_CLAUSE}""",
                (user_id,),
            )
        elif user_id is not None:
            cur.execute(
                f"""SELECT {_DEAL_COLS_D}
                    FROM bp_otc_deal d
                    LEFT JOIN bp_user_otc_deal_order o
                      ON o.deal_id = d.deal_id AND o.user_id = %s
                    WHERE d.is_example = TRUE OR d.owner_user_id = %s
                    {_DEAL_ORDER_CLAUSE}""",
                (user_id, user_id),
            )
        else:
            cur.execute(
                f"SELECT {_DEAL_COLS} FROM bp_otc_deal WHERE is_example = TRUE "
                "ORDER BY is_example DESC, deal_id DESC"
            )
        return [_row_to_deal(r) for r in cur.fetchall()]


def reorder_otc_deals(conn: psycopg.Connection, user_id: int, ordered_ids: list[int]) -> None:
    """保存当前用户的簿记列表顺序; 仅对其可见的簿记生效。"""
    if user_id is None:
        raise ValueError("缺少用户")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT deal_id FROM bp_otc_deal
               WHERE is_example = TRUE OR owner_user_id = %s
                  OR EXISTS (SELECT 1 FROM bp_user WHERE user_id=%s AND role='admin')""",
            (user_id, user_id),
        )
        visible = {r[0] for r in cur.fetchall()}
        for order, did in enumerate(ordered_ids):
            if did not in visible:
                continue
            cur.execute(
                """INSERT INTO bp_user_otc_deal_order (user_id, deal_id, display_order)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, deal_id)
                   DO UPDATE SET display_order = EXCLUDED.display_order, updated_at = now()""",
                (user_id, did, order),
            )


def get_otc_deal(conn: psycopg.Connection, deal_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_DEAL_COLS} FROM bp_otc_deal WHERE deal_id=%s", (deal_id,))
        row = cur.fetchone()
    if not row:
        return None
    deal = _row_to_deal(row)
    cached = cache.get_json(_deal_result_cache_key(deal_id))
    if isinstance(cached, dict) and cached:
        deal["last_result"] = cached
        if deal.get("last_price") is None and cached.get("price") is not None:
            try:
                deal["last_price"] = float(cached["price"])
            except (TypeError, ValueError):
                pass
        if deal.get("last_status") is None and cached.get("status") is not None:
            deal["last_status"] = cached.get("status")
        return deal
    if deal.get("last_result"):
        cache.set_json(
            _deal_result_cache_key(deal_id),
            deal["last_result"],
            ttl_seconds=_OTC_DEAL_RESULT_TTL,
        )
    return deal


def can_view_otc_deal(conn: psycopg.Connection, deal_id: int, user_id: Optional[int], is_admin: bool) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT is_example, owner_user_id FROM bp_otc_deal WHERE deal_id=%s", (deal_id,))
        row = cur.fetchone()
    if not row:
        return False
    return bool(row[0]) or is_admin or (user_id is not None and row[1] == user_id)


def can_edit_otc_deal(conn: psycopg.Connection, deal_id: int, user_id: Optional[int], is_admin: bool) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT owner_user_id FROM bp_otc_deal WHERE deal_id=%s", (deal_id,))
        row = cur.fetchone()
    if not row:
        return False
    if is_admin:
        return True
    return user_id is not None and row[0] == user_id


def count_user_deals(conn: psycopg.Connection, user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM bp_otc_deal WHERE owner_user_id=%s AND is_example=FALSE",
            (user_id,),
        )
        return int(cur.fetchone()[0])


def create_otc_deal(conn: psycopg.Connection, payload: dict, owner_user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_otc_deal
                 (name, product_type, engine, underlying_symbol, underlying_source, terms, owner_user_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING deal_id""",
            (
                payload["name"], payload["product_type"], payload.get("engine", "mc"),
                payload["underlying_symbol"], payload.get("underlying_source", "cn_index_em"),
                Json(_json_safe(payload.get("terms", {}))), owner_user_id,
            ),
        )
        return int(cur.fetchone()[0])


def update_otc_deal(conn: psycopg.Connection, deal_id: int, payload: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_otc_deal
               SET name=%s, product_type=%s, engine=%s, underlying_symbol=%s,
                   underlying_source=%s, terms=%s
               WHERE deal_id=%s""",
            (
                payload["name"], payload["product_type"], payload.get("engine", "mc"),
                payload["underlying_symbol"], payload.get("underlying_source", "cn_index_em"),
                Json(_json_safe(payload.get("terms", {}))), deal_id,
            ),
        )
    # 条款变更后缓存可能过期; DB last_result 保留, 下次重估覆盖
    cache.delete(_deal_result_cache_key(deal_id))


def delete_otc_deal(conn: psycopg.Connection, deal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_otc_deal WHERE deal_id=%s", (deal_id,))
    cache.delete(_deal_result_cache_key(deal_id))


def set_otc_example(conn: psycopg.Connection, deal_id: int, is_example: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE bp_otc_deal SET is_example=%s WHERE deal_id=%s", (is_example, deal_id))


def spot_on_date(
    conn: psycopg.Connection,
    symbol: str,
    source: Optional[str] = None,
    on_date: Optional[date] = None,
) -> Optional[dict]:
    """指定日(或之前最近交易日)的指数收盘价。"""
    src = resolve_source(conn, symbol, source)
    if not src:
        return None
    end = on_date or date.today()
    s = load_close_series(conn, symbol, src, end=end)
    if s.empty:
        return None
    if on_date is not None:
        sub = s[s.index.date <= on_date]
        if sub.empty:
            return None
        ts = sub.index[-1]
        close = float(sub.iloc[-1])
    else:
        ts = s.index[-1]
        close = float(s.iloc[-1])
    return {
        "symbol": symbol,
        "source": src,
        "date": ts.date().isoformat(),
        "close": round(close, 4),
    }


def save_deal_valuation(
    conn: psycopg.Connection,
    deal_id: int,
    result: dict,
    task_id: Optional[str] = None,
) -> None:
    safe = _json_safe(result)
    pnl = safe.get("current_pnl") if isinstance(safe, dict) else None
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_otc_deal
               SET last_price=%s, last_present_notional=%s, last_greeks=%s,
                   last_status=%s, last_valued_at=now(), last_result=%s
               WHERE deal_id=%s""",
            (
                _json_safe(result.get("price")), _json_safe(result.get("present_notional")),
                Json(_json_safe(result.get("greeks", {}))), result.get("status"),
                Json(safe), deal_id,
            ),
        )
        cur.execute(
            """INSERT INTO bp_otc_deal_price_history
                 (deal_id, price, status, current_pnl, result, task_id)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                deal_id,
                _json_safe(result.get("price")),
                result.get("status"),
                _json_safe(pnl),
                Json(safe),
                task_id,
            ),
        )
    cache.set_json(_deal_result_cache_key(deal_id), safe, ttl_seconds=_OTC_DEAL_RESULT_TTL)

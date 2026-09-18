"""加密相关性预计算引擎 — 由调度任务 / bp_ingest.run 钩子调用, 落库预计算结果。

把原 /api/crypto/correlation 请求路径上的 27s build_all_correlations 移到此处,
结果写入 bp_crypto_corr_daily / bp_crypto_price_daily / bp_crypto_meta (普通表,
非 hypertable — 镜像 bp_cffex_premium_daily, 避免 1200+ chunk hypertable 锁溢出)。
API 只读这三张表, 请求路径永不计算。

日历对齐: 标普500 在 bp_quote_clean 的交易日 = NYSE 交易日历 (单一事实源,
与 A 股 TradingCalendar 解耦)。所有资产 reindex 到 NYSE 日再算对数收益,
确保相关系数在同日标签可比。
as_of = 最近共同 NYSE 交易日 (6 资产齐全且收盘确认) 的 16:00 ET (DST 自洽)。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
import psycopg
import requests
from scipy import stats as scipy_stats

from .calendar import NY_TZ, is_nyse_close_confirmed, now_ny

logger = logging.getLogger(__name__)

# ---- 符号常量 ----
BTC_SYMBOL = "BTC-USD"
DXY_SYMBOL = "DX-Y.NYB"
COMEX_GOLD_SYMBOL = "GC=F"
SP500_SYMBOL = "标普500"
# DB 实际 seeded 符号是 纳斯达克 (gen_seed_sql.py 的 纳斯达克100 是 stale 过滤条目, 未实际入库)。
NASDAQ_SYMBOL = "纳斯达克"

YFINANCE_SOURCE = "crypto_yfinance"      # BTC-USD (用户保留 yfinance, atomicity hold-back 兜底)
GLOBAL_INDEX_SOURCE = "global_index_em"
CMDTY_SOURCE = "cmdty_main_sina"
# 以下两个切自 yfinance → 东方财富 (prod IP 被 Yahoo 429; DXY=push2his secid 100.UDI, GC=F=akshare futures_foreign_hist)
DXY_SOURCE = "dxy_em"
COMEX_SOURCE = "gold_comex_em"

# 窗口: 月数 → 近似交易日数 (美股 ~252 日/年)
WINDOWS: dict[str, int] = {"3M": 63, "6M": 126, "9M": 189, "12M": 252}

METHODS = ["pearson", "spearman", "kendall", "hoeffding"]

ASSET_PAIRS: dict[str, dict[str, str]] = {
    "comex_gold": {"symbol": COMEX_GOLD_SYMBOL, "source": COMEX_SOURCE,         "label": "COMEX黄金"},
    "au0_gold":   {"symbol": "AU0",             "source": CMDTY_SOURCE,         "label": "沪金AU0"},
    "sp500":      {"symbol": SP500_SYMBOL,      "source": GLOBAL_INDEX_SOURCE,  "label": "标普500"},
    "nasdaq":     {"symbol": NASDAQ_SYMBOL,     "source": GLOBAL_INDEX_SOURCE,  "label": "纳斯达克100"},
}

LAG_PERIODS = WINDOWS

# 6 个截面资产 (effective_td 门槛: 必须同日齐全)
ALL_PANEL_SYMBOLS = [BTC_SYMBOL, DXY_SYMBOL, COMEX_GOLD_SYMBOL, "AU0", SP500_SYMBOL, NASDAQ_SYMBOL]

# 7 年回看 (足够最宽 252 日窗口的滚动相关性)
LOOKBACK_DAYS = 2555


# ---------------------------------------------------------------------------
# 数据加载 (仅 JOB 内读 bp_quote_clean hypertable; API 不读)
# ---------------------------------------------------------------------------

def _load_close(
    conn: psycopg.Connection, symbol: str, source: str, start: date, end: date,
    *, usd_native: bool = False,
) -> pd.Series:
    """读清洗表收盘序列。

    `usd_native=True` 用于**本身就以美元计价**的看板资产(标普500/纳斯达克, 源
    global_index_em): 它们的 currency 非 CNY, 清洗阶段已按日折算成人民币, 直接读会把
    CNY 口径的价格当成 USD 展示(实测标普500 显示 52643 而真实是 7799), 并让 BTC 相关性
    偏离原生美元口径(近 3M 实测 0.2116 vs 真实 0.2546)。故此处在读侧用 `fx_rate` 还原
    原生美元价 —— /crypto 是美元口径看板(「BTC 价格 (USD)」/NYSE 日历), 与组合回测的
    CNY 口径是两条独立链路。

    其余面板资产(BTC-USD/DXY/GC=F/AU0)的 fx_rate 为 NULL 或 1, 不受影响。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT trade_date, close, fill_flag, fx_rate FROM bp_quote_clean
               WHERE symbol = %s AND source = %s
                 AND trade_date BETWEEN %s AND %s
               ORDER BY trade_date""",
            (symbol, source, start, end),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.Series(dtype=float)

    def _value(c, fill_flag, fx) -> float:
        # fill_flag='interp' 行(线性插值, 用了未来右锚)置 NaN, 防止未来函数 +
        # 防止美股假日 interp 行(标普500 被 cleaning 重索引到 A 股日历)污染 NYSE 日历;
        # 引擎随后 ffill(左锚)使缺口日收益=0、复牌日收益=真实缺口, 无未来依赖。
        if fill_flag == "interp" or c is None:
            return float("nan")
        v = float(c)
        if usd_native and fx is not None and float(fx) not in (0.0, 1.0):
            v /= float(fx)  # 折算价 → 原生美元价
        return v

    s = pd.Series({r[0]: _value(r[1], r[2], r[3]) for r in rows}, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


# ---------------------------------------------------------------------------
# 四种相关系数
# ---------------------------------------------------------------------------

def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(x, y)[0, 1])


def _spearman_r(x: np.ndarray, y: np.ndarray) -> float:
    from scipy.stats import rankdata
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def _kendall_tau(x: np.ndarray, y: np.ndarray) -> float:
    tau, _ = scipy_stats.kendalltau(x, y, variant="b")
    return float(tau) if not np.isnan(tau) else 0.0


def _hoeffding_d(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 10:
        return float("nan")
    from scipy.stats import rankdata
    rx = rankdata(x).astype(int)
    ry = rankdata(y).astype(int)
    ci = np.zeros(n, dtype=int)
    for i in range(n):
        ci[i] = int(np.sum((rx <= rx[i]) & (ry <= ry[i])))
    Q = np.sum((ci - 1) * (ci - 2))
    R = np.sum((rx - 1) * (rx - 2) * (ry - 1) * (ry - 2))
    T = np.sum((rx - 2) * (ry - 2) * (ci - 1))
    S = (n - 2) * (n - 3) * Q + R - 2 * (n - 2) * T
    denom = n * (n - 1) * (n - 2) * (n - 3) * (n - 4)
    if denom == 0:
        return float("nan")
    return float(30.0 * S / denom)


_CORR_FUNCS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "pearson": _pearson_r,
    "spearman": _spearman_r,
    "kendall": _kendall_tau,
    "hoeffding": _hoeffding_d,
}


# ---------------------------------------------------------------------------
# 滚动相关系数 (按 NYSE 交易日, 不做 forward-fill)
# ---------------------------------------------------------------------------

def _rolling_corr(
    ret_a: pd.Series, ret_b: pd.Series, window: int, method: str,
    calendar: pd.DatetimeIndex,
) -> tuple[list[str], list[float | None]]:
    """在给定日历上计算滚动相关系数。结果对齐到 calendar。"""
    corr_func = _CORR_FUNCS[method]
    common = ret_a.index.intersection(ret_b.index).intersection(calendar).sort_values()
    if len(common) < window:
        return [], []

    ra = ret_a.loc[common].values
    rb = ret_b.loc[common].values
    n = len(ra)

    result: list[float | None] = [None] * (window - 1)
    for i in range(window - 1, n):
        x = ra[i - window + 1 : i + 1]
        y = rb[i - window + 1 : i + 1]
        if np.any(np.isnan(x)) or np.any(np.isnan(y)):
            result.append(None)
        else:
            try:
                r = corr_func(x, y)
                result.append(round(r, 4) if not np.isnan(r) else None)
            except Exception:
                result.append(None)

    raw_s = pd.Series(result, index=common, dtype=object).reindex(calendar)
    dates_out = [d.strftime("%Y-%m-%d") for d in calendar]
    corr_out: list[float | None] = [
        None if pd.isna(v) else v for v in raw_s.tolist()
    ]
    return dates_out, corr_out


# ---------------------------------------------------------------------------
# effective_td + 标准化 as_of
# ---------------------------------------------------------------------------

def pick_effective_trade_date(
    candidate_dates: list[date],
    symbols_by_date: dict[date, set[str]],
    required_symbols: list[str],
    *,
    max_confirmed_date: date | None = None,
) -> Optional[date]:
    """最近一个「6 资产齐全且 <= max_confirmed_date」的 NYSE 交易日。

    纯函数, 便于单测 (镜像 bp_api.cffex.pick_effective_trade_date)。
    candidate_dates 须降序。
    """
    need = set(required_symbols)
    for d in candidate_dates:
        if max_confirmed_date is not None and d > max_confirmed_date:
            continue
        if need.issubset(symbols_by_date.get(d, set())):
            return d
    return None


def _canonical_as_of_ts(effective_td: date) -> datetime:
    """effective_td 16:00 America/New_York → tz-aware UTC (DST 自洽)。"""
    return datetime.combine(effective_td, time(16, 0), tzinfo=NY_TZ).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 批量 upsert (镜像 bp_ingest/cffex.py 的批量写模式)
# ---------------------------------------------------------------------------

def _batch_upsert(
    conn: psycopg.Connection,
    *,
    table: str,
    columns: list[str],
    rows: list[tuple],
    conflict_cols: list[str],
    update_cols: list[str],
    ts_col: str = "as_of_ts",
    batch_size: int = 2000,
) -> int:
    """批量 INSERT ... ON CONFLICT DO UPDATE。rows 元组顺序同 columns。"""
    if not rows:
        return 0
    col_sql = ", ".join(columns)
    placeholder = "(" + ", ".join(["%s"] * len(columns)) + ")"
    upd = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols] + [f"{ts_col} = now()"])
    conf = ", ".join(conflict_cols)
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        values_sql = ", ".join([placeholder] * len(batch))
        params = [v for row in batch for v in row]
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {table} ({col_sql}) VALUES {values_sql} "
                f"ON CONFLICT ({conf}) DO UPDATE SET {upd}",
                params,
            )
    return len(rows)


def _upsert_meta(conn: psycopg.Connection, key: str, value: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_crypto_meta (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (key, str(value)),
        )


def _bump_version(conn: psycopg.Connection) -> int:
    """version +1, 返回新值 (首次写 1)。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_crypto_meta (key, value) VALUES ('version', '1') "
            "ON CONFLICT (key) DO UPDATE SET "
            "  value = (bp_crypto_meta.value::int + 1)::text, updated_at = now() "
            "RETURNING value::int"
        )
        return int(cur.fetchone()[0])


def _read_version_meta(conn: psycopg.Connection) -> Optional[int]:
    """读 bp_crypto_meta.version (不递增); 用于 no-op 跳过 bump。"""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM bp_crypto_meta WHERE key = 'version'")
        r = cur.fetchone()
    if not r or r[0] is None:
        return None
    try:
        return int(r[0])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Next.js SSR 缓存失效 ping (best-effort, cacheLife TTL 兜底)
# ---------------------------------------------------------------------------

def _ping_crypto_revalidate() -> None:
    base = os.getenv("BP_WEB_BASE")
    token = os.getenv("BP_INTERNAL_REVALIDATE_TOKEN")
    if not base or not token:
        return
    try:
        requests.post(
            f"{base.rstrip('/')}/api/revalidate/crypto",
            headers={"X-Internal-Token": token},
            timeout=3,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("crypto revalidate ping 失败 (忽略, cacheLife 兜底): %s", exc)


# ---------------------------------------------------------------------------
# 主入口: 全量预计算 + 落库
# ---------------------------------------------------------------------------

def compute_and_store_crypto_corr(
    conn: psycopg.Connection,
    *,
    trade_dates: Optional[list[date]] = None,
    full: bool = False,
) -> dict:
    """预计算全部 (4 方法 × 4 窗口 × 4 资产对) 滚动相关性 + 6 资产对齐收盘, 落库。

    滚动相关性在第 d 日的值依赖 [d-window+1, d] 的收益, 故任一底层新数据都会
    影响其后所有日 → 每次调用都全量重算整个 7 年序列 (幂等 upsert 覆盖)。
    trade_dates/full 仅作触发日志与未来部分重算的预留, 不改变本次全量语义。
    不 commit — 由调用方控制事务 (与 cffex._compute_premiums 同样由 cffex_sync 提交)。
    """
    stats: dict[str, Any] = {
        "rows_corr": 0, "rows_price": 0, "effective_td": None, "as_of_ts": None, "version": 0,
    }
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)

    if trade_dates:
        logger.info("crypto 预计算触发 (trigger dates=%d, full=%s)", len(trade_dates), full)

    # 1. 加载 6 资产 7 年收盘 (仅 JOB 内读 bp_quote_clean hypertable)
    #    标普500/纳斯达克必须 usd_native=True: 清洗阶段已把非 CNY 资产折成人民币,
    #    而 /crypto 是美元口径看板。见 _load_close 文档。
    loaded: dict[str, pd.Series] = {
        BTC_SYMBOL:         _load_close(conn, BTC_SYMBOL, YFINANCE_SOURCE, start, end),
        DXY_SYMBOL:         _load_close(conn, DXY_SYMBOL, DXY_SOURCE, start, end),
        COMEX_GOLD_SYMBOL:  _load_close(conn, COMEX_GOLD_SYMBOL, COMEX_SOURCE, start, end),
        "AU0":               _load_close(conn, "AU0", CMDTY_SOURCE, start, end),
        SP500_SYMBOL:       _load_close(conn, SP500_SYMBOL, GLOBAL_INDEX_SOURCE, start, end,
                                        usd_native=True),
        NASDAQ_SYMBOL:      _load_close(conn, NASDAQ_SYMBOL, GLOBAL_INDEX_SOURCE, start, end,
                                        usd_native=True),
    }

    # 2. NYSE 日历 = 标普500 交易日 (单一事实源)
    sp500_close = loaded[SP500_SYMBOL]
    if len(sp500_close) == 0:
        raise RuntimeError("标普500 无交易日数据, 无法获取 NYSE 日历")
    nyse_cal = sp500_close.index.sort_values()
    n_dates = len(nyse_cal)
    nyse_dates = [d.date() for d in nyse_cal]

    # 3. effective_td = 最近 6 资产齐全且收盘确认的 NYSE 日
    # 只统计真实(非 NaN)收盘日: _load_close 把 fill_flag='interp' 行置 NaN
    # (标普500 被 cleaning 重索引到 A 股日历产生的插值行)。若按 s.index 统计, 会把这些
    # 无真实收盘的 NYSE 假日误判为 S&P500 齐全, effective_td 越过 6 资产真实截止日。
    symbols_by_date: dict[date, set[str]] = {}
    for sym, s in loaded.items():
        for d, v in s.items():
            if not pd.isna(v):
                symbols_by_date.setdefault(d.date(), set()).add(sym)
    candidate_desc = sorted(nyse_dates, reverse=True)
    today_ny = now_ny().date()
    max_confirmed = today_ny if is_nyse_close_confirmed(today_ny) else today_ny - timedelta(days=1)
    # effective_td = 最近「6 资产齐全且 ≤ max_confirmed」的 NYSE 交易日 (镜像 CFFEX)。
    # 6 资产齐全 = symbols_by_date 只统计非 NaN 收盘日 (见上方), 杜绝 interp/ffill 假日
    # 被误判齐全。BTC(yfinance) 缺口时 effective_td 回退到缺口前完整日, 看板 HOLD 在
    # 前一日 (is_synced=False), 不用 ffill 假价冒充最新收盘 — 与 CFFEX「待现货对齐」同语义。
    effective_td = pick_effective_trade_date(
        candidate_desc, symbols_by_date, ALL_PANEL_SYMBOLS,
        max_confirmed_date=max_confirmed,
    )
    # max_candidate = 候选中 ≤ max_confirmed 的最新日 (用于 is_synced, 镜像
    # cffex.is_synced = futures_latest == effective_td)。须在下方截断 nyse_cal 前算。
    max_candidate = next(
        (d for d in candidate_desc if max_confirmed is None or d <= max_confirmed),
        None,
    )
    is_synced = (
        effective_td is not None
        and max_candidate is not None
        and effective_td == max_candidate
    )
    if effective_td is None:
        logger.warning(
            "crypto: 无 6 资产齐全的确认交易日 (max_confirmed=%s), 跳过预计算",
            max_confirmed,
        )
        return stats

    # 截断输出至 effective_td: 杜绝 > effective_td 的 NYSE 日 (标普500 尾部 ffill 假价 /
    # 陈旧 corr) 落库。两步:
    #  (1) 计算用日历截断到 ≤ effective_td — corr 滚动窗口只向回看, 截断尾部不影响历史,
    #      且 ffill 仍填补 [start, effective_td] 内历史缺口 (保留 07-28 折线断点修复);
    #  (2) DELETE 前次(bug 运行)残留的 > effective_td 行 — upsert 只覆盖传入日, 清不到旧日,
    #      不删则 API 按 trade_date 全量读仍会显示到旧 tail, 修复作废。
    nyse_cal = nyse_cal[nyse_cal <= pd.Timestamp(effective_td)]
    nyse_dates = [d for d in nyse_dates if d <= effective_td]
    n_dates = len(nyse_dates)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_crypto_corr_daily WHERE trade_date > %s", (effective_td,))
        cur.execute("DELETE FROM bp_crypto_price_daily WHERE trade_date > %s", (effective_td,))

    # 4. 对齐到 NYSE 日历 + 对数收益; ffill(左锚)使缺口日收益=0, 消除折线断点 (无未来函数)
    btc_nyse_close = loaded[BTC_SYMBOL].reindex(nyse_cal).ffill()
    btc_logret = _log_returns(btc_nyse_close)
    asset_logrets: dict[str, pd.Series] = {}
    for key, info in ASSET_PAIRS.items():
        cn = loaded[info["symbol"]].reindex(nyse_cal).ffill()
        asset_logrets[key] = _log_returns(cn) if len(cn) > 0 else pd.Series(dtype=float)

    # 5. 滚动相关性: 对每个 (pair_key, method) 算 4 个窗口的 corr 数组 (按 NYSE 日历对齐)
    win_items = list(WINDOWS.items())  # [(3M,63), (6M,126), (9M,189), (12M,252)]
    corr_by_pm: dict[tuple[str, str], list[list[float | None]]] = {}
    for method in METHODS:
        for key in ASSET_PAIRS:
            ret_b = asset_logrets[key]
            win_arrays: list[list[float | None]] = []
            for _w_label, w_days in win_items:
                if ret_b.empty or btc_logret.empty:
                    cv: list[float | None] = [None] * n_dates
                else:
                    _, cv = _rolling_corr(btc_logret, ret_b, w_days, method, nyse_cal)
                    cv = cv if len(cv) == n_dates else [None] * n_dates
                win_arrays.append(cv)
            corr_by_pm[(key, method)] = win_arrays  # [c3m, c6m, c9m, c12m], 每个长 n_dates

    # 6. 写 bp_crypto_corr_daily (Option A: 一行=一日×一对×一方法, 4 窗口作列, ~27k 行)
    corr_rows: list[tuple] = []
    for i, d in enumerate(nyse_dates):
        for (key, method), win_arrays in corr_by_pm.items():
            corr_rows.append((
                d, key, BTC_SYMBOL, ASSET_PAIRS[key]["symbol"], method,
                None if win_arrays[0][i] is None else round(float(win_arrays[0][i]), 6),  # 3M
                None if win_arrays[1][i] is None else round(float(win_arrays[1][i]), 6),  # 6M
                None if win_arrays[2][i] is None else round(float(win_arrays[2][i]), 6),  # 9M
                None if win_arrays[3][i] is None else round(float(win_arrays[3][i]), 6),  # 12M
            ))
    stats["rows_corr"] = _batch_upsert(
        conn,
        table="bp_crypto_corr_daily",
        columns=["trade_date", "pair_key", "asset_a", "asset_b", "method", "corr_3m", "corr_6m", "corr_9m", "corr_12m"],
        rows=corr_rows,
        conflict_cols=["trade_date", "pair_key", "method"],
        update_cols=["asset_a", "asset_b", "corr_3m", "corr_6m", "corr_9m", "corr_12m"],
    )

    # 7. 写 bp_crypto_price_daily (6 资产 NYSE 对齐收盘, ~10k 行; 供快照 + DXY 滞后图 + BTC 叠加)
    src_map = {
        BTC_SYMBOL: YFINANCE_SOURCE, DXY_SYMBOL: DXY_SOURCE,
        COMEX_GOLD_SYMBOL: COMEX_SOURCE, "AU0": CMDTY_SOURCE,
        SP500_SYMBOL: GLOBAL_INDEX_SOURCE, NASDAQ_SYMBOL: GLOBAL_INDEX_SOURCE,
    }
    aligned = {sym: loaded[sym].reindex(nyse_cal).ffill() for sym in ALL_PANEL_SYMBOLS}
    price_rows: list[tuple] = []
    for i, d_ts in enumerate(nyse_cal):
        d = d_ts.date()
        for sym in ALL_PANEL_SYMBOLS:
            v = aligned[sym].iloc[i]
            if pd.isna(v):
                continue  # close NOT NULL, 缺数据不写 (effective_td 保证 6 资产齐全)
            price_rows.append((d, sym, src_map[sym], round(float(v), 4)))
    stats["rows_price"] = _batch_upsert(
        conn,
        table="bp_crypto_price_daily",
        columns=["trade_date", "symbol", "source", "close"],
        rows=price_rows,
        conflict_cols=["trade_date", "symbol"],
        update_cols=["source", "close"],
    )

    # 8. meta (latest_as_of/computed_at/effective_td/is_synced/version + 清理 JSONB 旧版残留 key)
    as_of_ts = _canonical_as_of_ts(effective_td)
    # 仅在 effective_td 或 is_synced 实际变化时 bump version + ping revalidate;
    # 全量重算每次都跑(幂等), no-op(数据未推进)时不必刷 SSR cacheTag。
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, value FROM bp_crypto_meta WHERE key = ANY(%s)",
            (["effective_td", "is_synced"],),
        )
        prev = {k: v for k, v in cur.fetchall()}
    changed = (
        effective_td.isoformat() != prev.get("effective_td")
        or str(is_synced).lower() != (prev.get("is_synced") or "").lower()
    )
    _upsert_meta(conn, "latest_as_of", as_of_ts.isoformat())
    _upsert_meta(conn, "computed_at", datetime.now(timezone.utc).isoformat())
    _upsert_meta(conn, "btc_data_end", effective_td.isoformat())
    _upsert_meta(conn, "effective_td", effective_td.isoformat())
    _upsert_meta(conn, "is_synced", "true" if is_synced else "false")
    if changed:
        version = _bump_version(conn)
    else:
        version = _read_version_meta(conn) or 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM bp_crypto_meta WHERE key = ANY(%s)",
            (["nyse_dates", "btc_prices", "dxy_prices", "snapshot_prices"],),
        )

    stats["effective_td"] = effective_td.isoformat()
    stats["as_of_ts"] = as_of_ts.isoformat()
    stats["is_synced"] = is_synced
    stats["changed"] = changed
    stats["version"] = version
    logger.info(
        "crypto 预计算完成: effective_td=%s as_of=%s rows_corr=%d rows_price=%d version=%d",
        effective_td, as_of_ts.isoformat(), stats["rows_corr"], stats["rows_price"], version,
    )
    return stats

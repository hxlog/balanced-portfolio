"""CFFEX 期货数据落库 / 增量更新。

利用 akshare get_futures_daily(market="CFFEX") 拉取 IF/IH/IC/IM 日行情,
写入 bp_cffex_contract_daily, 并计算升贴水率写入 bp_cffex_premium_daily。

增量策略 (参照 bp_ingest/ingest.py):
  1. 查询 bp_cffex_contract_daily 中最新的 trade_date
  2. 若首次 (无数据): 从 DEFAULT_START 拉全量
  3. 若已有数据: 从 last_date - revision_days 拉增量窗口 (覆盖修正)
  4. 仅重新计算窗口中受影响交易日的 premium

指数价格从 bp_index_quote_daily / bp_quote_clean 读取 (依赖主 ingest 流水线)。

用法:
  python -m bp_ingest cffex-backfill              # 全量/增量 (自动判断)
  python -m bp_ingest cffex-backfill --full        # 强制全量
  python -m bp_ingest cffex-incremental            # T-1 增量
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import akshare as ak
import pandas as pd
import psycopg

from . import db as ingest_db
from .calendar import (
    filter_confirmed_trade_dates,
    is_trade_date_close_confirmed,
    now_cst,
)
from .config import AppConfig, load_config
from .cffex_contract_map import (
    CFFEX_VARIETIES,
    INDEX_SINA_MAP,
    INDEX_SYMBOL_MAP,
    INDEX_SINA_MAP as _INDEX_SINA,
    Contract,
    compute_ann_premium_rate,
    compute_basis,
    compute_composite,
    compute_premium_rate,
    days_to_expiry,
    map_contracts,
)

logger = logging.getLogger(__name__)

# 历史回填起始日 (仅用于首次全量)
DEFAULT_START = date(2017, 1, 1)

# 增量修正窗口 (自然日)
REVISION_DAYS = 7


# ======================================================================
# 辅助
# ======================================================================

def _to_date(s) -> date | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    if isinstance(s, date):
        return s
    if isinstance(s, (datetime, pd.Timestamp)):
        return s.date()
    s_str = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s_str, fmt).date()
        except ValueError:
            continue
    return None


def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _safe_num(val) -> Decimal | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


# ======================================================================
# 数据库状态查询
# ======================================================================

def _get_last_date(conn: psycopg.Connection) -> date | None:
    """获取 bp_cffex_contract_daily 中最新 trade_date。"""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date) FROM bp_cffex_contract_daily")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _get_fresh_premium_dates(conn: psycopg.Connection, since: date) -> list[date]:
    """需计算/重算 premium 的交易日: 尚无行, 或已有行但 spot_price 无效(=0)。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT cd.trade_date
            FROM bp_cffex_contract_daily cd
            WHERE cd.trade_date >= %s
              AND cd.variety = ANY(%s)
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM bp_cffex_premium_daily pd
                      WHERE pd.trade_date = cd.trade_date
                        AND pd.variety = cd.variety
                  )
                  OR EXISTS (
                      SELECT 1 FROM bp_cffex_premium_daily pd
                      WHERE pd.trade_date = cd.trade_date
                        AND pd.variety = cd.variety
                        AND (pd.spot_price IS NULL OR pd.spot_price = 0)
                  )
              )
            ORDER BY cd.trade_date
        """, (since, CFFEX_VARIETIES))
        return [r[0] for r in cur.fetchall()]


# ======================================================================
# 数据拉取
# ======================================================================

def fetch_cffex_futures_daily(start: date, end: date) -> pd.DataFrame | None:
    """拉取 CFFEX 全部期货品种日行情 (OHLCV + settle + open_interest)。"""
    try:
        s = _fmt_date(start)
        e = _fmt_date(end)
        logger.info("拉取 CFFEX 日行情: %s → %s", s, e)
        df = ak.get_futures_daily(start_date=s, end_date=e, market="CFFEX")
        if df is None or df.empty:
            logger.warning("CFFEX %s-%s 返回空数据", s, e)
            return None
        return df
    except Exception as exc:
        logger.error("拉取 CFFEX 日行情失败: %s", exc)
        return None


# ======================================================================
# 落库
# ======================================================================

def _upsert_contract_daily(conn: psycopg.Connection, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bp_cffex_contract_daily
                (trade_date, symbol, variety, open, high, low, close,
                 settle, volume, open_interest, pre_settle, turnover)
            VALUES (%(trade_date)s, %(symbol)s, %(variety)s,
                    %(open)s, %(high)s, %(low)s, %(close)s,
                    %(settle)s, %(volume)s, %(open_interest)s,
                    %(pre_settle)s, %(turnover)s)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open          = EXCLUDED.open,
                high          = EXCLUDED.high,
                low           = EXCLUDED.low,
                close         = EXCLUDED.close,
                settle        = EXCLUDED.settle,
                volume        = EXCLUDED.volume,
                open_interest = EXCLUDED.open_interest,
                pre_settle    = EXCLUDED.pre_settle,
                turnover      = EXCLUDED.turnover,
                updated_at    = now()
        """, row)


def _upsert_premium_daily(conn: psycopg.Connection, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bp_cffex_premium_daily
                (trade_date, variety, contract_symbol, contract_type,
                 days_to_expiry, spot_price, futures_price, basis,
                 premium_rate, ann_premium_rate, composite_rate)
            VALUES (%(trade_date)s, %(variety)s, %(contract_symbol)s, %(contract_type)s,
                    %(days_to_expiry)s, %(spot_price)s, %(futures_price)s, %(basis)s,
                    %(premium_rate)s, %(ann_premium_rate)s, %(composite_rate)s)
            ON CONFLICT (trade_date, variety, contract_symbol) DO UPDATE SET
                contract_type   = EXCLUDED.contract_type,
                days_to_expiry  = EXCLUDED.days_to_expiry,
                spot_price      = EXCLUDED.spot_price,
                futures_price   = EXCLUDED.futures_price,
                basis           = EXCLUDED.basis,
                premium_rate    = EXCLUDED.premium_rate,
                ann_premium_rate= EXCLUDED.ann_premium_rate,
                composite_rate  = EXCLUDED.composite_rate
        """, row)


# ======================================================================
# 合约入库
# ======================================================================

def _ingest_contracts(
    conn: psycopg.Connection,
    df: pd.DataFrame,
    *,
    now: datetime | None = None,
) -> int:
    """从 akshare DataFrame 解析合约并写入 bp_cffex_contract_daily。返回写入行数。"""
    wall = now_cst(now)
    today = wall.date()
    written = 0
    skipped_unconfirmed = 0
    for _, row in df.iterrows():
        td = _to_date(row.get("trade_date") or row.get("date"))
        if td is None:
            continue
        if not is_trade_date_close_confirmed(td, now=wall, today=today):
            skipped_unconfirmed += 1
            continue
        sym = str(row.get("symbol", "")).strip().upper()
        # 仅 IF/IH/IC/IM
        m = re.match(r"^(IF|IH|IC|IM)\d{4}$", sym)
        if not m:
            continue
        variety = m.group(1)

        _upsert_contract_daily(conn, {
            "trade_date": td, "symbol": sym, "variety": variety,
            "open": _safe_num(row.get("open")), "high": _safe_num(row.get("high")),
            "low": _safe_num(row.get("low")), "close": _safe_num(row.get("close")),
            "settle": _safe_num(row.get("settle")),
            "volume": int(row["volume"]) if row.get("volume") and not pd.isna(row.get("volume")) else None,
            "open_interest": int(row["open_interest"]) if row.get("open_interest") and not pd.isna(row.get("open_interest")) else None,
            "pre_settle": _safe_num(row.get("pre_settle")),
            "turnover": _safe_num(row.get("turnover")),
        })
        written += 1
    if skipped_unconfirmed:
        logger.info("收盘未确认, 跳过 %d 行当日期货日 K", skipped_unconfirmed)
    return written


# ======================================================================
# Premium 计算
# ======================================================================

def _compute_premiums(
    conn: psycopg.Connection,
    trade_dates: list[date],
) -> int:
    """全量批量重算升贴水率 — 内存计算 + 批量写入。

    优化原理: 将合同数据和指数价格一次性加载到内存,
    在 Python 中完成所有计算, 最后用 execute_values 批量写入。
    """
    if not trade_dates:
        return 0

    # 未确认收盘的当日不参与升贴水(避免盘中脏现货/期货)
    trade_dates = filter_confirmed_trade_dates(list(trade_dates))
    if not trade_dates:
        return 0

    # --- 1. 一次性加载所有合同数据 ---
    logger.info("加载合同数据到内存...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT trade_date, symbol, variety, close
            FROM bp_cffex_contract_daily
            WHERE trade_date >= %s AND variety = ANY(%s)
            ORDER BY trade_date, variety, symbol
        """, (trade_dates[0], CFFEX_VARIETIES))
        all_contracts = cur.fetchall()
    logger.info("  合同数据: %d 行", len(all_contracts))

    # 按 (variety, trade_date) 分组
    from collections import defaultdict
    contract_map: dict[tuple[str, date], list[tuple[str, float]]] = defaultdict(list)
    for td, sym, var, close_val in all_contracts:
        contract_map[(var, td)].append((sym, float(close_val) if close_val else 0.0))

    # --- 2. 一次性加载所有指数收盘价 ---
    index_prices: dict[tuple[str, date], float] = {}
    wall = now_cst()
    today = wall.date()
    for variety in CFFEX_VARIETIES:
        idx_sym = INDEX_SYMBOL_MAP.get(variety)
        if not idx_sym:
            continue
        for table in ("bp_quote_clean", "bp_index_quote_daily"):
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT trade_date, close FROM {table}
                    WHERE symbol = %s AND trade_date >= %s
                    ORDER BY trade_date
                """, (idx_sym, trade_dates[0]))
                rows = cur.fetchall()
                if rows:
                    for td, close_val in rows:
                        if not is_trade_date_close_confirmed(td, now=wall, today=today):
                            continue
                        if close_val is not None and (variety, td) not in index_prices:
                            index_prices[(variety, td)] = float(close_val)
            if any((variety, td) in index_prices for td in trade_dates[:5]):
                break  # 该表有数据则不用查下一张
        # 任一目标日缺现货则尝试 akshare 补拉 (尤其最新期货日)
        missing = sum(1 for td in trade_dates if (variety, td) not in index_prices)
        if missing > 0:
            _ensure_index_data(conn, variety, index_prices, trade_dates, now=wall)
        logger.info("  指数 %s: %d 个交易日价格已加载", variety,
                     sum(1 for td in trade_dates if (variety, td) in index_prices))

    # --- 3. 内存批量计算 ---
    logger.info("开始批量计算升贴水率...")
    premium_rows: list[dict] = []
    composite_updates: list[tuple[float, date, str]] = []
    skipped_no_spot = 0

    for (variety, td), contracts in sorted(contract_map.items()):
        symbols = [s for s, _ in contracts]
        parsed = [c for s in symbols if (c := Contract.parse(s))]
        if not parsed:
            continue
        spot_price = index_prices.get((variety, td), 0.0)
        if not spot_price or spot_price <= 0:
            skipped_no_spot += 1
            continue
        ctype_map = map_contracts(parsed, td)

        premiums_by_type: dict[str, float] = {}
        for sym, close_val in contracts:
            ctype = ctype_map.get(sym)
            if ctype is None:
                continue
            dte = days_to_expiry(sym, td) or 0
            basis = compute_basis(spot_price, close_val)
            pr = compute_premium_rate(basis, spot_price)
            apr = compute_ann_premium_rate(pr, dte) if pr is not None and dte is not None else None

            premium_rows.append({
                "trade_date": td, "variety": variety,
                "contract_symbol": sym, "contract_type": ctype,
                "days_to_expiry": dte, "spot_price": _safe_num(spot_price),
                "futures_price": _safe_num(close_val), "basis": _safe_num(basis),
                "premium_rate": _safe_num(pr), "ann_premium_rate": _safe_num(apr),
            })
            if apr is not None:
                premiums_by_type[ctype] = apr

        comp = compute_composite(premiums_by_type)
        if comp is not None:
            composite_updates.append((_safe_num(comp), td, variety))

    if skipped_no_spot:
        logger.warning("跳过 %d 个 (variety,td) — 缺同日现货, 不写 spot_price=0", skipped_no_spot)
    logger.info("  计算完成: %d 行 premium, %d 个 composite", len(premium_rows), len(composite_updates))

    # --- 4. 批量写入 ---
    logger.info("批量写入 bp_cffex_premium_daily...")
    from psycopg import sql as _psysql
    batch_size = 2000
    for i in range(0, len(premium_rows), batch_size):
        batch = premium_rows[i:i + batch_size]
        with conn.cursor() as cur:
            values = []
            params = []
            for row in batch:
                values.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
                params.extend([
                    row["trade_date"], row["variety"], row["contract_symbol"],
                    row["contract_type"], row["days_to_expiry"], row["spot_price"],
                    row["futures_price"], row["basis"], row["premium_rate"],
                    row["ann_premium_rate"],
                ])
            if values:
                sql = _psysql.SQL(
                    "INSERT INTO bp_cffex_premium_daily "
                    "(trade_date, variety, contract_symbol, contract_type, "
                    "days_to_expiry, spot_price, futures_price, basis, "
                    "premium_rate, ann_premium_rate) VALUES {} "
                    "ON CONFLICT (trade_date, variety, contract_symbol) DO UPDATE SET "
                    "contract_type = EXCLUDED.contract_type, "
                    "days_to_expiry = EXCLUDED.days_to_expiry, "
                    "spot_price = EXCLUDED.spot_price, "
                    "futures_price = EXCLUDED.futures_price, "
                    "basis = EXCLUDED.basis, "
                    "premium_rate = EXCLUDED.premium_rate, "
                    "ann_premium_rate = EXCLUDED.ann_premium_rate"
                ).format(_psysql.SQL(", ").join(map(_psysql.SQL, values)))
                cur.execute(sql, params)
        if i % 10000 == 0:
            logger.info("  已写入 %d/%d 行", min(i + batch_size, len(premium_rows)), len(premium_rows))

    # --- 5. 批量更新 composite_rate ---
    logger.info("批量更新 composite_rate (%d 个)...", len(composite_updates))
    for i in range(0, len(composite_updates), batch_size):
        batch = composite_updates[i:i + batch_size]
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE bp_cffex_premium_daily AS pd SET composite_rate = v.comp
                FROM (SELECT unnest(%s::numeric[]) AS comp, unnest(%s::date[]) AS td, unnest(%s::text[]) AS var) AS v
                WHERE pd.trade_date = v.td AND pd.variety = v.var
            """, (
                [r[0] for r in batch],
                [r[1] for r in batch],
                [r[2] for r in batch],
            ))

    conn.commit()
    logger.info("批量重算完成: %d 行 premium, %d 个交易日", len(premium_rows), len(trade_dates))
    return len(trade_dates)


def _ensure_index_data(
    conn: psycopg.Connection, variety: str,
    index_prices: dict, trade_dates: list[date],
    *,
    now: datetime | None = None,
) -> None:
    """拉取缺失的指数历史数据并写入 DB + 更新内存 index_prices。

    允许新浪补拉, 但今日未过收盘确认时刻的行不落库、不写入内存价,
    避免盘中最新价污染正式收盘。
    """
    idx_sym = INDEX_SYMBOL_MAP.get(variety)
    sina_sym = INDEX_SINA_MAP.get(variety)
    if not idx_sym or not sina_sym:
        return
    wall = now_cst(now)
    today = wall.date()
    try:
        logger.info("指数 %s 从 akshare 补拉: %s", variety, sina_sym)
        df = ak.stock_zh_index_daily(symbol=sina_sym)
        if df is None or df.empty:
            return
        rows_written = 0
        skipped_unconfirmed = 0
        for _, row in df.iterrows():
            td = _to_date(row.get("date") or row.get("trade_date"))
            if td is None:
                continue
            if not is_trade_date_close_confirmed(td, now=wall, today=today):
                skipped_unconfirmed += 1
                continue
            close_val = row.get("close")
            if close_val is None or (isinstance(close_val, float) and pd.isna(close_val)):
                continue
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bp_index_quote_daily
                        (trade_date, symbol, source, category, name, close)
                    VALUES (%s, %s, 'cn_index_sina', 'cn_index', %s, %s)
                    ON CONFLICT (symbol, source, trade_date) DO UPDATE SET
                        close = EXCLUDED.close, updated_at = now()
                """, (td, idx_sym, sina_sym, _safe_num(close_val)))
            rows_written += 1
            # 同时更新内存
            index_prices[(variety, td)] = float(close_val)
        conn.commit()
        if skipped_unconfirmed:
            logger.info("指数 %s: 收盘未确认, 跳过今日 %d 行", variety, skipped_unconfirmed)
        logger.info("指数 %s: 写入 %d 行", variety, rows_written)
    except Exception as exc:
        logger.warning("指数 %s akshare 补拉失败: %s", variety, exc)


# ======================================================================
# 核心: 增量同步
# ======================================================================

def cffex_sync(
    conn: psycopg.Connection,
    *,
    force_full: bool = False,
    recompute_premium: bool = False,
) -> dict:
    """CFFEX 增量同步 (自动判断全量 vs 增量)。

    recompute_premium: 删除已有 premium 数据后全部重算 (公式变更后使用)。
    force_full: 同时强制全量拉取 + 重算 premium。
    """
    stats = {"contracts": 0, "premium_days": 0}

    # 重算模式: 先清空 premium 表
    if recompute_premium or force_full:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bp_cffex_premium_daily")
        conn.commit()
        logger.info("已清空 bp_cffex_premium_daily (准备重算)")

    last_date = _get_last_date(conn)
    wall = now_cst()
    today = wall.date()
    # 盘中不把「今天」当作同步终点, 避免未确认日 K 入库
    sync_end = today
    if not is_trade_date_close_confirmed(today, now=wall, today=today):
        sync_end = today - timedelta(days=1)

    if last_date is None or force_full:
        start = DEFAULT_START
        logger.info("=== 全量回填: %s → %s ===", start, sync_end)
    else:
        start = last_date - timedelta(days=REVISION_DAYS)
        logger.info("=== 增量同步: %s → %s (last=%s) ===", start, sync_end, last_date)

    end = sync_end

    # 1. 拉取期货数据 (仅 re-fetch 模式; recompute_premium 单独模式跳过拉取)
    skip_fetch = recompute_premium and not force_full
    if skip_fetch:
        logger.info("跳过数据拉取 (仅重算 premium)")
        futures_success = True
        start = DEFAULT_START  # premium 全量重算范围
    else:
        futures_success = False

    if not skip_fetch:
        year = start.year
        end_year = end.year
        while year <= end_year:
            y_start = max(start, date(year, 1, 1))
            y_end = min(end, date(year, 12, 31))
            if y_start <= y_end:
                df = fetch_cffex_futures_daily(y_start, y_end)
                if df is not None and not df.empty:
                    n = _ingest_contracts(conn, df, now=wall)
                    stats["contracts"] += n
                    logger.info("  %d年: %d 行入库", year, n)
                    futures_success = True
                time.sleep(0.5)
            year += 1

    if not futures_success and last_date is not None and not recompute_premium:
        # 期货无新行时仍尝试重算缺现货的 premium (现货可能刚入库)
        premium_dates = _get_fresh_premium_dates(conn, start)
        if premium_dates:
            logger.info("期货无增量, 但有 %d 日 premium 待补算", len(premium_dates))
            stats["premium_days"] = _compute_premiums(conn, premium_dates)
            conn.commit()
            try:
                from bp_api.cffex import invalidate_cffex_spot_cache
                invalidate_cffex_spot_cache()
            except Exception as exc:  # noqa: BLE001
                logger.warning("失效 CFFEX 看板缓存失败: %s", exc)
        else:
            logger.info("无新数据, 已是最新")
        return stats

    conn.commit()

    # 2. premium 计算 — 增量窗口内全量重算, 以便现货收盘价修正后覆盖脏 spot_price
    if recompute_premium or force_full:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT trade_date FROM bp_cffex_contract_daily
                WHERE variety = ANY(%s) AND trade_date >= %s
                ORDER BY trade_date
            """, (CFFEX_VARIETIES, start))
            premium_dates = [r[0] for r in cur.fetchall()]
        logger.info("全量重算 premium: %d 个交易日", len(premium_dates))
    else:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT trade_date FROM bp_cffex_contract_daily
                WHERE variety = ANY(%s) AND trade_date >= %s
                ORDER BY trade_date
            """, (CFFEX_VARIETIES, start))
            premium_dates = [r[0] for r in cur.fetchall()]
        logger.info("窗口重算 premium: %d 个交易日", len(premium_dates))

    stats["premium_days"] = _compute_premiums(conn, premium_dates)
    conn.commit()

    try:
        from bp_api.cffex import invalidate_cffex_spot_cache
        invalidate_cffex_spot_cache()
    except Exception as exc:  # noqa: BLE001
        logger.warning("失效 CFFEX 看板缓存失败: %s", exc)

    logger.info("=== 同步完成: contracts=%d premium_days=%d ===",
                stats["contracts"], stats["premium_days"])
    return stats


# ======================================================================
# CLI 入口
# ======================================================================

def run_backfill(force_full: bool = False, recompute_premium: bool = False) -> dict:
    """CLI: cffex-backfill (自动判断全量/增量)。"""
    app = load_config()
    from .http_session import install_hardened_session
    install_hardened_session()

    with ingest_db.connect(app.db) as conn:
        conn.autocommit = False
        return cffex_sync(conn, force_full=force_full, recompute_premium=recompute_premium)


def run_incremental() -> dict:
    """CLI: cffex-incremental (T-1 增量)。"""
    app = load_config()
    from .http_session import install_hardened_session
    install_hardened_session()

    with ingest_db.connect(app.db) as conn:
        conn.autocommit = False
        return cffex_sync(conn, force_full=False, recompute_premium=False)

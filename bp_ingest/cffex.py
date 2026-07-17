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
  python -m bp_ingest cffex-backfill --full        # 强制全量 (按月 ZIP 并发, 不限频)
  python -m bp_ingest cffex-incremental            # T-1 增量
"""

from __future__ import annotations

import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Optional

import akshare as ak
import pandas as pd
import psycopg
import requests

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

# 中金所按月 ZIP (内含该月全部交易日 CSV); akshare 逐日重复下同一 ZIP, 极慢
CFFEX_MONTH_ZIP_URL = "http://www.cffex.com.cn/sj/historysj/{ym}/zip/{ym}.zip"
# 全量回填并发月数 (中金所无严格限频, 直接打满)
CFFEX_FETCH_WORKERS = 16
_INDEX_FUTURE_RE = re.compile(r"^(IF|IH|IC|IM)\d{4}$")
_SKIP_ROW_RE = re.compile(r"小计|合计|IO|MO|HO")


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
# 数据拉取 (按月 ZIP 并发, 不限频)
# ======================================================================

def _iter_months(start: date, end: date) -> list[str]:
    """闭区间 [start, end] 覆盖的 YYYYMM 列表。"""
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _decode_cffex_csv(raw: bytes) -> str:
    for enc in ("gb2312", "gbk", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gbk", errors="replace")


def _parse_cffex_day_csv(raw: bytes, day: str) -> pd.DataFrame:
    """解析中金所单日 CSV → akshare 兼容列 (仅 IF/IH/IC/IM)。"""
    text = _decode_cffex_csv(raw)
    data_df = pd.read_csv(StringIO(text))
    if data_df.empty:
        return pd.DataFrame()

    col0 = data_df.columns[0]
    sym = data_df[col0].astype(str).str.strip()
    keep = ~sym.str.contains(_SKIP_ROW_RE, na=False) & sym.str.match(_INDEX_FUTURE_RE)
    data_df = data_df.loc[keep].copy()
    if data_df.empty:
        return pd.DataFrame()
    data_df[col0] = sym[keep].values

    n_cols = data_df.shape[1]
    if n_cols == 15:
        data_df.columns = [
            "symbol", "open", "high", "low", "volume", "turnover",
            "open_interest", "_", "close", "settle", "pre_settle",
            "_2", "_3", "_4", "_5",
        ]
    elif n_cols >= 14:
        # 14 列及偶发多列: 按前 11 个有效字段对齐
        rename = {
            data_df.columns[0]: "symbol",
            data_df.columns[1]: "open",
            data_df.columns[2]: "high",
            data_df.columns[3]: "low",
            data_df.columns[4]: "volume",
            data_df.columns[5]: "turnover",
            data_df.columns[6]: "open_interest",
            data_df.columns[8]: "close",
            data_df.columns[9]: "settle",
            data_df.columns[10]: "pre_settle",
        }
        data_df = data_df.rename(columns=rename)
    else:
        return pd.DataFrame()

    data_df["date"] = day
    data_df["trade_date"] = day
    data_df["symbol"] = data_df["symbol"].astype(str).str.strip().str.upper()
    return data_df[[
        "symbol", "date", "trade_date", "open", "high", "low", "close",
        "volume", "open_interest", "turnover", "settle", "pre_settle",
    ]]


def _fetch_cffex_month_zip(ym: str, start: date, end: date) -> pd.DataFrame:
    """下载单月 ZIP, 解析区间内全部交易日 CSV。失败返回空 DataFrame。"""
    url = CFFEX_MONTH_ZIP_URL.format(ym=ym)
    try:
        # 每线程独立 Session, 避开全局 hardened session 的线程安全问题;
        # 中金所直连、不限频。
        with requests.Session() as sess:
            sess.trust_env = False
            r = sess.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                },
                timeout=60,
            )
        if r.status_code != 200 or len(r.content) < 100:
            logger.warning(
                "CFFEX 月 ZIP 不可用: %s status=%s bytes=%d",
                ym, r.status_code, len(r.content),
            )
            return pd.DataFrame()
        frames: list[pd.DataFrame] = []
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            for name in zf.namelist():
                # 文件名形如 20240102_1.csv
                m = re.match(r"^(\d{8})_1\.csv$", name.split("/")[-1])
                if not m:
                    continue
                day = m.group(1)
                d = _to_date(day)
                if d is None or d < start or d > end:
                    continue
                with zf.open(name) as f:
                    day_df = _parse_cffex_day_csv(f.read(), day)
                if not day_df.empty:
                    frames.append(day_df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CFFEX 月 ZIP 拉取失败 %s: %s", ym, exc)
        return pd.DataFrame()


def fetch_cffex_futures_daily(
    start: date,
    end: date,
    *,
    workers: int = CFFEX_FETCH_WORKERS,
) -> pd.DataFrame | None:
    """拉取 CFFEX 股指期货日行情 (OHLCV + settle + open_interest)。

    直接按月下载中金所历史 ZIP 并并发解析, 避免 akshare 逐日重复下载同月 ZIP。
    不插入限频 sleep。
    """
    if start > end:
        return None
    months = _iter_months(start, end)
    logger.info(
        "拉取 CFFEX 日行情(按月 ZIP 并发×%d): %s → %s (%d 个月)",
        workers, _fmt_date(start), _fmt_date(end), len(months),
    )
    frames: list[pd.DataFrame] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {
            pool.submit(_fetch_cffex_month_zip, ym, start, end): ym
            for ym in months
        }
        for fut in as_completed(futs):
            ym = futs[fut]
            done += 1
            try:
                df = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("CFFEX %s 任务异常: %s", ym, exc)
                continue
            if df is not None and not df.empty:
                frames.append(df)
                logger.info("  %s: %d 行 (%d/%d)", ym, len(df), done, len(months))
            else:
                logger.info("  %s: 空 (%d/%d)", ym, done, len(months))

    if not frames:
        logger.warning("CFFEX %s-%s 返回空数据", _fmt_date(start), _fmt_date(end))
        return None
    out = pd.concat(frames, ignore_index=True)
    # 稳定排序, 便于日志/调试
    if "date" in out.columns:
        out = out.sort_values(["date", "symbol"]).reset_index(drop=True)
    logger.info("CFFEX 拉取完成: %d 行 / %d 个月", len(out), len(months))
    return out


# ======================================================================
# 落库
# ======================================================================

_TEMP_CONTRACT_TABLE = "tmp_cffex_contract_daily"

_TEMP_CONTRACT_DDL = f"""
CREATE TEMP TABLE {_TEMP_CONTRACT_TABLE} (
    trade_date    DATE NOT NULL,
    symbol        TEXT NOT NULL,
    variety       TEXT NOT NULL,
    open          NUMERIC(20,4),
    high          NUMERIC(20,4),
    low           NUMERIC(20,4),
    close         NUMERIC(20,4) NOT NULL,
    settle        NUMERIC(20,4),
    volume        BIGINT,
    open_interest BIGINT,
    pre_settle    NUMERIC(20,4),
    turnover      NUMERIC(20,4)
)
"""

_MERGE_CONTRACT_SQL = f"""
INSERT INTO bp_cffex_contract_daily
    (trade_date, symbol, variety, open, high, low, close,
     settle, volume, open_interest, pre_settle, turnover)
SELECT
    trade_date, symbol, variety, open, high, low, close,
    settle, volume, open_interest, pre_settle, turnover
FROM {_TEMP_CONTRACT_TABLE}
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
"""


def _safe_int(val) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(val)
    except Exception:
        return None


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
    """批量写入 bp_cffex_contract_daily: COPY → 临时表 → INSERT…SELECT ON CONFLICT → DROP。"""
    if df is None or df.empty:
        return 0

    wall = now_cst(now)
    today = wall.date()
    skipped_unconfirmed = 0
    # (symbol, trade_date) → row; 后者覆盖前者, 避免 COPY 源内重复键
    by_key: dict[tuple[str, date], tuple] = {}

    for row in df.itertuples(index=False):
        td = _to_date(getattr(row, "trade_date", None) or getattr(row, "date", None))
        if td is None:
            continue
        if not is_trade_date_close_confirmed(td, now=wall, today=today):
            skipped_unconfirmed += 1
            continue
        sym = str(getattr(row, "symbol", "") or "").strip().upper()
        m = _INDEX_FUTURE_RE.match(sym)
        if not m:
            continue
        close_val = _safe_num(getattr(row, "close", None))
        if close_val is None:
            continue  # 表约束 close NOT NULL
        by_key[(sym, td)] = (
            td,
            sym,
            m.group(1),
            _safe_num(getattr(row, "open", None)),
            _safe_num(getattr(row, "high", None)),
            _safe_num(getattr(row, "low", None)),
            close_val,
            _safe_num(getattr(row, "settle", None)),
            _safe_int(getattr(row, "volume", None)),
            _safe_int(getattr(row, "open_interest", None)),
            _safe_num(getattr(row, "pre_settle", None)),
            _safe_num(getattr(row, "turnover", None)),
        )

    if skipped_unconfirmed:
        logger.info("收盘未确认, 跳过 %d 行当日期货日 K", skipped_unconfirmed)
    if not by_key:
        return 0

    rows = list(by_key.values())
    logger.info("合约批量落库: COPY %d 行 → 临时表 → upsert", len(rows))

    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TEMP_CONTRACT_TABLE}")
        cur.execute(_TEMP_CONTRACT_DDL)
        cols = (
            "trade_date, symbol, variety, open, high, low, close, "
            "settle, volume, open_interest, pre_settle, turnover"
        )
        with cur.copy(f"COPY {_TEMP_CONTRACT_TABLE} ({cols}) FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)
        cur.execute(_MERGE_CONTRACT_SQL)
        cur.execute(f"DROP TABLE IF EXISTS {_TEMP_CONTRACT_TABLE}")

    logger.info("合约批量落库完成: %d 行", len(rows))
    return len(rows)


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
        # 一次性按月并发拉取整个区间 (不按年切、不 sleep)
        df = fetch_cffex_futures_daily(start, end)
        if df is not None and not df.empty:
            n = _ingest_contracts(conn, df, now=wall)
            stats["contracts"] += n
            logger.info("合约入库: %d 行", n)
            futures_success = True
        else:
            logger.warning("期货拉取无数据")

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

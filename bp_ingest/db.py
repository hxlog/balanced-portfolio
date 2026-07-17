"""PostgreSQL / TimescaleDB 访问层 (psycopg3)。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Iterator, Optional

import psycopg

from .config import DBConfig

logger = logging.getLogger(__name__)


@dataclass
class ConfigRow:
    config_id: int
    symbol: str
    source: str
    category: Optional[str]
    name: Optional[str]
    start_date: Optional[date]
    extra_params: dict
    has_data: bool  # 配置对应行情表是否已有数据(由查询填充)


@dataclass
class QuoteRow:
    trade_date: date
    symbol: str
    source: str
    category: Optional[str]
    name: Optional[str]
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Decimal
    volume: Optional[int]
    amount: Optional[Decimal]
    turnover_rate: Optional[Decimal]
    pct_change: Optional[Decimal]


@contextmanager
def connect(db: DBConfig) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(db.conninfo())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping(db: DBConfig) -> str:
    """连通性测试, 返回服务器版本字符串。"""
    with connect(db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
            return row[0] if row else "unknown"


def fetch_active_configs(
    conn: psycopg.Connection, symbols: Optional[list[str]] = None
) -> list[ConfigRow]:
    """读取有效配置。symbols 非空时按 symbol 过滤(管理员显式单标的, 含停用品种)。
    symbols 为空(全量/调度)时仅取启用品种(is_selectable=1)。"""
    sql = """
        SELECT config_id, symbol, source, category, name, start_date, extra_params
        FROM bp_index_config
        WHERE is_deleted = 0
    """
    params: list = []
    if symbols:
        sql += " AND symbol = ANY(%s)"
        params.append(symbols)
    else:
        sql += " AND is_selectable = TRUE"
    sql += " ORDER BY source, symbol"

    rows: list[ConfigRow] = []
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for r in cur.fetchall():
            rows.append(
                ConfigRow(
                    config_id=r[0],
                    symbol=r[1],
                    source=r[2],
                    category=r[3],
                    name=r[4],
                    start_date=r[5],
                    extra_params=r[6] or {},
                    has_data=False,
                )
            )
    return rows


def get_last_trade_date(
    conn: psycopg.Connection, symbol: str, source: str
) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(trade_date) FROM bp_index_quote_daily "
            "WHERE symbol = %s AND source = %s",
            (symbol, source),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_quote_updated_at(
    conn: psycopg.Connection, symbol: str, source: str, trade_date: date
) -> Optional[datetime]:
    """单日行情行的 updated_at; 无行则 None。用于判断盘中脏 close 是否需收盘后重拉。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT updated_at FROM bp_index_quote_daily
            WHERE symbol = %s AND source = %s AND trade_date = %s
            """,
            (symbol, source, trade_date),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_prev_close(
    conn: psycopg.Connection, symbol: str, source: str, before_date: date
) -> Optional[Decimal]:
    """取 before_date 之前最近一个交易日的收盘价, 用于 pct_change 基准。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close FROM bp_index_quote_daily
            WHERE symbol = %s AND source = %s AND trade_date < %s
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (symbol, source, before_date),
        )
        row = cur.fetchone()
        return row[0] if row else None


_UPSERT_SQL = """
INSERT INTO bp_index_quote_daily
    (trade_date, symbol, source, category, name,
     open, high, low, close, volume, amount, turnover_rate, pct_change)
VALUES
    (%(trade_date)s, %(symbol)s, %(source)s, %(category)s, %(name)s,
     %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(amount)s,
     %(turnover_rate)s, %(pct_change)s)
ON CONFLICT (symbol, source, trade_date) DO UPDATE SET
    category      = EXCLUDED.category,
    name          = EXCLUDED.name,
    open          = EXCLUDED.open,
    high          = EXCLUDED.high,
    low           = EXCLUDED.low,
    close         = EXCLUDED.close,
    volume        = EXCLUDED.volume,
    amount        = EXCLUDED.amount,
    turnover_rate = EXCLUDED.turnover_rate,
    pct_change    = EXCLUDED.pct_change,
    updated_at    = now()
"""


def upsert_quotes(conn: psycopg.Connection, rows: Iterable[QuoteRow]) -> int:
    """幂等写入行情。返回处理行数。"""
    payload = [
        {
            "trade_date": r.trade_date,
            "symbol": r.symbol,
            "source": r.source,
            "category": r.category,
            "name": r.name,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "amount": r.amount,
            "turnover_rate": r.turnover_rate,
            "pct_change": r.pct_change,
        }
        for r in rows
    ]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, payload)
    return len(payload)


def mark_sync_success(
    conn: psycopg.Connection,
    config_id: int,
    start_date_writeback: Optional[date] = None,
) -> None:
    """记录同步成功; start_date_writeback 非空时回写(仅当当前为空)。"""
    if start_date_writeback is not None:
        sql = """
            UPDATE bp_index_config
            SET last_sync_at = now(),
                last_error = NULL,
                start_date = COALESCE(start_date, %s)
            WHERE config_id = %s
        """
        params = (start_date_writeback, config_id)
    else:
        sql = """
            UPDATE bp_index_config
            SET last_sync_at = now(), last_error = NULL
            WHERE config_id = %s
        """
        params = (config_id,)
    with conn.cursor() as cur:
        cur.execute(sql, params)


def mark_sync_error(conn: psycopg.Connection, config_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_index_config SET last_error = %s WHERE config_id = %s",
            (error[:2000], config_id),
        )

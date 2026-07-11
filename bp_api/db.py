"""API 数据库连接池(psycopg3)。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from .settings import ApiSettings

_pool: Optional[ConnectionPool] = None


def init_pool(settings: ApiSettings) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.db.conninfo(),
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"autocommit": False},
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    if _pool is None:
        raise RuntimeError("连接池未初始化, 请先 init_pool()")
    with _pool.connection() as conn:
        yield conn

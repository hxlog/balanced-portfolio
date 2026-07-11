"""运行配置: 从环境变量 / .env 读取数据库连接与增量参数。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv

load_dotenv()


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    connect_timeout: int

    def conninfo(self) -> str:
        """psycopg3 连接串。"""
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password} "
            f"connect_timeout={self.connect_timeout}"
        )

    def safe_repr(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"


@dataclass(frozen=True)
class AppConfig:
    db: DBConfig
    default_start_date: date
    revision_days: int
    lag_days: int
    max_retries: int
    request_interval: float
    request_jitter: float
    schedule_hours: int
    cffex_sync_hours: int
    log_level: str


def _parse_date(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def load_config() -> AppConfig:
    db = DBConfig(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=_get_int("PGPORT", 5432),
        dbname=os.getenv("PGDATABASE", "balanced_portfolio"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        connect_timeout=_get_int("PG_CONNECT_TIMEOUT", 15),
    )
    return AppConfig(
        db=db,
        default_start_date=_parse_date(
            os.getenv("BP_DEFAULT_START_DATE", "2017-01-01"), date(2017, 1, 1)
        ),
        revision_days=_get_int("BP_REVISION_DAYS", 7),
        lag_days=_get_int("BP_LAG_DAYS", 0),
        max_retries=_get_int("BP_MAX_RETRIES", 3),
        request_interval=_get_float("BP_REQUEST_INTERVAL", 2.5),
        request_jitter=_get_float("BP_REQUEST_JITTER", 3.5),
        schedule_hours=_get_int("BP_SCHEDULE_HOURS", 6),
        cffex_sync_hours=_get_int("BP_CFFEX_SYNC_HOURS", 2),
        log_level=os.getenv("BP_LOG_LEVEL", "INFO").upper(),
    )


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

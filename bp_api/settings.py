"""API 运行配置: 复用 bp_ingest 的 DB 配置 + 量化/服务参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from bp_ingest.config import DBConfig, load_config as _load_ingest_config


@dataclass(frozen=True)
class ApiSettings:
    db: DBConfig
    risk_free: float
    trading_days: int
    min_window: int
    default_lookback: int
    rebalance_band: float
    cors_origins: list[str]
    admin_email: str
    jwt_secret: str
    jwt_expire_hours: int
    admin_initial_password: str | None = None


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def load_settings() -> ApiSettings:
    db = _load_ingest_config().db
    origins = os.getenv(
        "BP_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    jwt_secret = os.getenv("BP_JWT_SECRET", "").strip()
    if not jwt_secret:
        raise RuntimeError("必须显式设置 BP_JWT_SECRET（请使用随机长字符串）")
    if len(jwt_secret) < 32:
        raise RuntimeError("BP_JWT_SECRET 至少需要 32 个字符")
    admin_email = os.getenv("BP_ADMIN_EMAIL", "").strip().lower() or "admin@example.com"
    admin_initial_password = os.getenv("BP_ADMIN_INITIAL_PASSWORD", "").strip() or None
    return ApiSettings(
        db=db,
        risk_free=_get_float("BP_RISK_FREE", 0.0),
        trading_days=_get_int("BP_TRADING_DAYS", 244),
        min_window=_get_int("BP_MIN_WINDOW", 60),
        default_lookback=_get_int("BP_DEFAULT_LOOKBACK", 156),
        rebalance_band=_get_float("BP_REBALANCE_BAND", 0.05),
        cors_origins=[o.strip() for o in origins if o.strip()],
        admin_email=admin_email,
        jwt_secret=jwt_secret,
        jwt_expire_hours=_get_int("BP_JWT_EXPIRE_HOURS", 168),
        admin_initial_password=admin_initial_password,
    )

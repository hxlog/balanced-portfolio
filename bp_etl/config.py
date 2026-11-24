"""bp_etl 运行配置：环境变量 → 不可变配置对象。

复用 `bp_ingest.config` 的数据库配置（单一口径），只新增 ETL 专属开关。
所有默认值必须保守：ETL 默认关闭（off），relay 默认不配置，并发默认小。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time

from dotenv import dotenv_values, load_dotenv

from bp_ingest.config import DBConfig, load_config as load_ingest_config

load_dotenv()
# PM2 保存的旧进程环境可能带有过期的 BP_ETL_*（例如历史上以 off 启动）；
# 以仓库 .env 为唯一口径强制覆盖，避免"改 .env 后 restart 仍 off"。
_dotenv_values = dotenv_values()
for _key, _value in _dotenv_values.items():
    if _key.startswith("BP_ETL_") and _value is not None:
        os.environ[_key] = _value

_VALID_MODES = frozenset({"off", "shadow", "on"})
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


def _parse_hhmm(raw: str, fallback: time) -> time:
    """解析 HHMM（与 BP_CLOSE_CONFIRM_HHMM 同风格）；非法回退。"""
    text = (raw or "").strip()
    if len(text) == 4 and text.isdigit():
        hour, minute = int(text[:2]), int(text[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    return fallback


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class EtlConfig:
    """ETL 进程配置。db 与 bp_ingest 共用，避免两套连接口径漂移。"""

    db: DBConfig
    mode: str  # off / shadow / on
    workers: int  # 单 dataset 默认 worker 上限
    relay_sg: str | None  # 通用 relay（EM 小流量通道），如 http://127.0.0.1:10809
    relay_prologue: str | None  # 第二 relay（容灾），如 http://127.0.0.1:10810
    log_level: str
    rebuild_window: tuple[time, time]  # 历史重建夜窗

    @property
    def write_enabled(self) -> bool:
        """shadow 模式只拉取/校验，不写行情表。"""
        return self.mode == "on"


def load_etl_config() -> EtlConfig:
    ingest = load_ingest_config()
    mode = (os.getenv("BP_ETL_MODE") or "off").strip().lower()
    if mode not in _VALID_MODES:
        mode = "off"
    level = (os.getenv("BP_ETL_LOG_LEVEL") or "INFO").strip().upper()
    if level not in _VALID_LOG_LEVELS:
        level = "INFO"
    return EtlConfig(
        db=ingest.db,
        mode=mode,
        workers=max(1, min(_int_env("BP_ETL_WORKERS", 4), 8)),
        relay_sg=(os.getenv("BP_ETL_RELAY_SG") or "").strip() or None,
        relay_prologue=(os.getenv("BP_ETL_RELAY2") or "").strip() or None,
        log_level=level,
        rebuild_window=(
            _parse_hhmm(os.getenv("BP_ETL_REBUILD_START") or "0100", time(1, 0)),
            _parse_hhmm(os.getenv("BP_ETL_REBUILD_END") or "0500", time(5, 0)),
        ),
    )
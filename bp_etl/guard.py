"""资源守护：单机内存检查 + 重活全局互斥锁（防止并行重任务把 2C/3.7GB 生产机打爆）。

背景：2026-11-24 生产事故——A 股 hfq 重建 + ETF 全量 + 临时 L3 抽样同时跑，内存耗尽导致
PostgreSQL 异常终止。本模块提供：
- `mem_available_mb()`：读取 /proc/meminfo MemAvailable（Linux；其它平台返回 None）；
- `require_memory(min_mb=700)`：低于阈值抛 `MemoryGuardError`（调用方应排队/放弃）；
- `heavy_lock(path="/tmp/bp_etl-heavy.lock")`：fcntl.flock 非阻塞互斥，保证任意时刻只有一个
  重 ETL 进程（rebuild/全量 run）；拿不到锁抛 `HeavyJobBusy`；非 POSIX 平台退化为进程内锁。
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_MIN_MB = 700
DEFAULT_LOCK_PATH = "/tmp/bp_etl-heavy.lock"
_PROCESS_LOCK = threading.Lock()


class MemoryGuardError(RuntimeError):
    """可用内存低于安全阈值（默认 700MB），拒绝启动重活。"""


class HeavyJobBusy(RuntimeError):
    """已有另一个重 ETL 进程在运行（全局互斥锁被占用）。"""


def read_meminfo() -> dict[str, int] | None:
    path = "/proc/meminfo"
    if not os.path.exists(path):
        return None
    values: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parts = line.split(":", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip().split()[0]
                try:
                    values[key] = int(value)
                except ValueError:
                    continue
    except OSError:
        return None
    return values


def mem_available_mb() -> int | None:
    values = read_meminfo()
    if not values or "MemAvailable" not in values:
        return None
    return int(values["MemAvailable"] // 1024)


def require_memory(min_mb: int = DEFAULT_MIN_MB) -> None:
    available = mem_available_mb()
    if available is None:
        return  # 非 Linux（本地开发）不阻断
    if available < min_mb:
        raise MemoryGuardError(
            f"可用内存 {available}MB < 安全阈值 {min_mb}MB，拒绝启动重 ETL（请等待重活结束/扩容）"
        )


@contextmanager
def heavy_lock(path: str = DEFAULT_LOCK_PATH) -> Iterator[None]:
    """全局重活互斥：同一台机器上同时只允许一个 rebuild/全量 run 进程。"""
    try:
        import fcntl  # noqa: PLC0415 - 仅 POSIX
    except ImportError:  # pragma: no cover - Windows/本地
        acquired = _PROCESS_LOCK.acquire(blocking=False)
        if not acquired:
            raise HeavyJobBusy("已有重 ETL 进程在运行（进程内锁）")
        try:
            yield
        finally:
            _PROCESS_LOCK.release()
        return

    handle = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise HeavyJobBusy(f"重 ETL 全局锁被占用（{path}）") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()

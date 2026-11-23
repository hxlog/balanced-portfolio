"""资源守护测试：内存解析/阈值/全局重活锁。"""
from __future__ import annotations

import pytest

from bp_etl import guard


def test_mem_available_parses_meminfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "read_meminfo", lambda: {"MemAvailable": 800 * 1024, "MemTotal": 3900000})
    assert guard.mem_available_mb() == 800


def test_require_memory_raises_when_low(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "read_meminfo", lambda: {"MemAvailable": 200 * 1024})
    with pytest.raises(guard.MemoryGuardError):
        guard.require_memory(700)


def test_require_memory_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "read_meminfo", lambda: {"MemAvailable": 900 * 1024})
    guard.require_memory(700)  # 不抛


def test_heavy_lock_nested_busy() -> None:
    with guard.heavy_lock():
        with pytest.raises(guard.HeavyJobBusy):
            with guard.heavy_lock():
                pass
    # 释放后可再次获取
    with guard.heavy_lock():
        pass


def test_non_linux_meminfo_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard.os.path, "exists", lambda path: False)
    assert guard.mem_available_mb() is None
    guard.require_memory(700)  # 非 Linux 不阻断

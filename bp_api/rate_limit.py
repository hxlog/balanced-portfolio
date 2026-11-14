"""对外 API 的令牌级限流与请求日志（进程内实现，Redis 不可用也不阻断）。

窗口：60 秒滑动窗口；上限由 BP_API_RATE_LIMIT_RPM 控制（默认 60）。
超限返回 429 + Retry-After，不进入业务逻辑（避免打库）。
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException

DEFAULT_RPM = 60
WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = {}


def limit_per_minute() -> int:
    try:
        value = int(os.environ.get("BP_API_RATE_LIMIT_RPM", str(DEFAULT_RPM)))
    except ValueError:
        return DEFAULT_RPM
    return value if value > 0 else DEFAULT_RPM


def check(token_id: str) -> None:
    rpm = limit_per_minute()
    key = str(token_id)
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= rpm:
            retry_after = max(1, int(WINDOW_SECONDS - (now - q[0])) + 1)
            raise HTTPException(
                429,
                detail={
                    "code": "rate_limited",
                    "message": "超过每分钟 %d 次的调用上限" % rpm,
                    "limit_per_minute": rpm,
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()

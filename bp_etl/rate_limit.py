"""通道级全局限速（保守令牌桶）与自适应退避。

设计：docs/superpowers/specs/2026-11-23-unified-market-etl-design.md §7
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucket:
    """单源全局令牌桶：容量 1，按 rate_per_sec 匀速放行。"""

    def __init__(
        self,
        rate_per_sec: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec 必须为正")
        self.rate = float(rate_per_sec)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = clock()
        self._tokens = 1.0
        self.total_wait = 0.0

    def acquire(self, tokens: float = 1.0) -> float:
        """获取令牌；返回本线程为等待令牌睡眠的秒数（测试可断言）。"""
        with self._lock:
            now = self._clock()
            self._tokens = min(1.0, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return 0.0
            wait = (tokens - self._tokens) / self.rate
        self._sleep(wait)
        with self._lock:
            self._tokens = 0.0
            self._last = self._clock()
        self.total_wait += wait
        return wait


class RateLimiterRegistry:
    """按源名懒加载令牌桶；速率来自 SourceSpec。"""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def bucket(self, source: str, rate_per_sec: float) -> TokenBucket:
        with self._lock:
            bucket = self._buckets.get(source)
            if bucket is None:
                bucket = TokenBucket(rate_per_sec)
                self._buckets[source] = bucket
            return bucket

    def snapshot(self) -> dict[str, float]:
        return {name: round(bucket.total_wait, 3) for name, bucket in self._buckets.items()}

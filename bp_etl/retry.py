"""deadline 语义的重试/时间预算工具（防 WAF 慢速滴流挂死线程）。"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class DeadlineExceeded(RuntimeError):
    """超过单次抓取总时间预算。"""


class Deadline:
    """总耗时预算：调用前后都检查，超过即抛（不无限重试）。"""

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        if seconds <= 0:
            raise ValueError("seconds 必须为正")
        self.seconds = float(seconds)
        self._clock = clock
        self._started = clock()

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed)

    def check(self) -> None:
        if self.elapsed > self.seconds:
            raise DeadlineExceeded(f"deadline {self.seconds:.1f}s exceeded ({self.elapsed:.1f}s)")


def with_deadline(seconds: float, fn: Callable[[], T], *, clock: Callable[[], float] = time.monotonic) -> T:
    deadline = Deadline(seconds, clock=clock)
    deadline.check()
    result = fn()
    deadline.check()
    return result

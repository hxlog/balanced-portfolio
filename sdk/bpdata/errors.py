"""bpdata SDK 的异常类型。

调用方通常只需要捕获 ``BpApiError``；更细的鉴权 / 限频场景可分别捕获
``BpAuthError`` 与 ``BpRateLimitError``。
"""

from __future__ import annotations

from typing import Any


class BpApiError(Exception):
    """API 返回非 2xx，或响应信封中的 ``error`` 非空时抛出。

    Attributes:
        status: HTTP 状态码（服务端返回的 4xx / 5xx 原样保留）。
        code: 稳定的机器可读错误码，例如 ``unknown_code``。
        message: 面向人的错误说明（服务端可能调整，不要用于编程判断）。
        payload: 完整错误信封（若可解析），便于排查 ``required_scope`` 等上下文。
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)
        self.payload = payload or {}
        super().__init__(f"HTTP {self.status} [{self.code}]: {self.message}")


class BpAuthError(BpApiError):
    """401（Token 缺失/无效/过期）或 403（缺少 scope）。

    这两类错误**不会自动重试**，因为重试无法改变鉴权结果。
    """


class BpRateLimitError(BpApiError):
    """429 限频，且指数退避重试次数已耗尽。"""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retry_after: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status, code, message, payload=payload)
        self.retry_after = retry_after

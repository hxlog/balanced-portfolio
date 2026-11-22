"""带「总耗时」上限的 HTTP GET。

requests 的 timeout 只能限制「连接/两次读之间」的停顿，防不住 WAF 的慢速滴流
（腾讯 501/tarpit 会持续吐少量字节，read timeout 被不断重置，线程永久挂住）。
本模块用 stream=True + 总 deadline 读取，超时立即关闭连接并抛 TimeoutError。
"""
from __future__ import annotations

import json as _json
import time
from typing import Any

import requests


class DeadlineResponse:
    """最小响应对象：保留 status_code / text / json() / raise_for_status()。"""

    def __init__(self, status_code: int, text: str, url: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.url = url

    def json(self) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}", response=None)  # type: ignore[arg-type]


def get_with_deadline(
    session: requests.Session,
    url: str,
    *,
    deadline: float = 25.0,
    chunk_size: int = 8192,
    **kwargs: Any,
) -> DeadlineResponse:
    """GET 并读取完整响应体；总耗时超过 deadline 抛 TimeoutError。"""
    kwargs.setdefault("stream", True)
    kwargs.setdefault("timeout", (5, 10))
    started = time.monotonic()
    response = session.get(url, **kwargs)
    chunks: list[bytes] = []
    try:
        for chunk in response.iter_content(chunk_size):
            if chunk:
                chunks.append(chunk)
            if time.monotonic() - started > deadline:
                raise TimeoutError(f"deadline {deadline}s exceeded: {url}")
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    try:
        text = body.decode(encoding, "replace")
    except (LookupError, TypeError):
        text = body.decode("utf-8", "replace")
    return DeadlineResponse(response.status_code, text, url)

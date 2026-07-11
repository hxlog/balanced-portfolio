"""Redis 缓存封装。

缓存是可选增强：Redis 不可用时自动降级为 miss，不影响核心功能。
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

try:
    import redis
except Exception:  # pragma: no cover - redis 依赖缺失时降级
    redis = None  # type: ignore


def _client():
    if redis is None:
        return None
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
    except Exception:
        return None


def get_json(key: str) -> Optional[Any]:
    client = _client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def set_json(key: str, value: Any, ttl_seconds: int = 300) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return


def delete(key: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        return


def delete_pattern(pattern: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        for key in client.scan_iter(pattern):
            client.delete(key)
    except Exception:
        return


def incr_with_ttl(key: str, ttl_seconds: int) -> int:
    client = _client()
    if client is None:
        return 0
    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        count, _ = pipe.execute()
        return int(count)
    except Exception:
        return 0


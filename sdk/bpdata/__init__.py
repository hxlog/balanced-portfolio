"""bpdata —— Balanced Portfolio 对外数据 API 的 Python SDK。

Example:
    >>> from bpdata import Client
    >>> client = Client("bp_live_xxx")
    >>> rows = client.valuation("930641", start="2020-01-01", end="2024-12-31")
"""

from __future__ import annotations

from .client import Client
from .errors import BpApiError, BpAuthError, BpRateLimitError

__version__ = "0.1.0"

__all__ = [
    "BpApiError",
    "BpAuthError",
    "BpRateLimitError",
    "Client",
    "__version__",
]

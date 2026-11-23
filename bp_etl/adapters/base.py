"""适配器公共协议：Bar 结构、错误类型、WAF/JSON 防护工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

ALLOWED_ADJUST = ("bfq", "hfq")


class AdapterError(RuntimeError):
    """适配器基类错误。"""


class SourceParseError(AdapterError):
    """源返回 HTML/WAF/空 JSON/字段缺失——绝不允许把垃圾写进行情表。"""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail


class SourceUnavailable(AdapterError):
    """源不可达（连接错误/封禁）；调用方应切换通道或回退源。"""


@dataclass(frozen=True)
class Bar:
    """归一化日线行；价格字段保留源精度（Decimal 由 writer 负责）。"""

    symbol: str
    trade_date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    volume: Optional[int] = None
    amount: Optional[float] = None
    pct_change: Optional[float] = None
    source: str = ""
    adjust: str = "bfq"


@dataclass(frozen=True)
class NavRow:
    """场外基金净值行（bp_fund_nav_daily）。"""

    fund_code: str
    trade_date: date
    nav: float
    acc_nav: Optional[float] = None
    source: str = ""


def ensure_adjust(adjust: str) -> str:
    """qfq 已停用：任何适配器收到 qfq 必须立即失败（防止口径回潮）。"""
    if adjust == "qfq":
        raise ValueError("qfq 已停用（76 号迁移）；只允许 bfq/hfq")
    if adjust not in ALLOWED_ADJUST:
        raise ValueError(f"非法 adjust: {adjust!r}")
    return adjust


def is_waf_html(response: Any) -> bool:
    """腾讯/东财 WAF 页特征：非 JSON 的 HTML 响应。"""
    content_type = str(getattr(response, "headers", {}).get("content-type", "") or "").lower()
    text = str(getattr(response, "text", "") or "").lstrip()
    if "json" in content_type:
        return False
    if "html" in content_type:
        return True
    return text.startswith("<")


def json_body(response: Any, *, source: str) -> dict:
    """把响应解析为 JSON；WAF/非 JSON 一律 SourceParseError。"""
    if is_waf_html(response):
        raise SourceParseError(source, "WAF/HTML 响应（非 JSON）")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise SourceParseError(source, f"JSON 解析失败: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SourceParseError(source, f"JSON 顶层类型异常: {type(payload).__name__}")
    return payload

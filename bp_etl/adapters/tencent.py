"""腾讯行情适配器：qt 批量快照（bfq）+ fqkline/hkfqkline（hfq/bfq）。

端点与回退（2026-11-22 生产实测）：
- 主：`ifzq.gtimg.cn/appstock/app/fqkline/get`（A 股/ETF）、`hkfqkline/get`（港股复权）
- 备：`proxy.finance.qq.com/ifzqgtimg/appstock/app/...`（ifzq 被 WAF 时）
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable, Sequence

from .base import Bar, SourceParseError, ensure_adjust, is_waf_html, json_body

QT_URL = "https://qt.gtimg.cn/q="
KLINE_HOSTS = (
    "https://ifzq.gtimg.cn/appstock/app",
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app",
)
SOURCE_QT = "tencent_qt"
SOURCE_KLINE_A_ETF = "tencent_kline"
SOURCE_KLINE_HK = "tencent_hk_kline"

QT_BATCH_SIZE = 60


def split_market(symbol: str) -> tuple[str, str]:
    """'600036'/'sh600036'/'00700'/'hk00700' → (qt 前缀形式, 市场)。"""
    text = symbol.strip().lower()
    if text.startswith(("sh", "sz", "bj", "hk")) and len(text) > 2:
        prefix, code = text[:2], text[2:]
        return prefix + code, ("HK" if prefix == "hk" else "A")
    if len(text) == 5:
        return "hk" + text, "HK"
    head = text[0] if text else ""
    if head in ("6", "9"):
        return "sh" + text, "A"
    if head in ("4", "8"):
        return "bj" + text, "A"
    if head == "5":
        return "sh" + text, "A"
    return "sz" + text, "A"


def _qt_date(stamp: str) -> date:
    return date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))


def parse_qt_text(text: str, *, source: str = SOURCE_QT) -> list[Bar]:
    """解析 qt.gtimg.cn 批量响应（gbk 文本）；坏行跳过，不抛整体错误。"""
    bars: list[Bar] = []
    for line in text.split(";"):
        line = line.strip()
        if "=" not in line:
            continue
        raw = line.split("=", 1)[1].strip().strip('"')
        parts = raw.split("~")
        if len(parts) < 38:
            continue
        try:
            code = parts[2]
            current = float(parts[3])
            if current <= 0:
                continue
            trade_date = _qt_date(parts[30])
            volume = int(float(parts[36]) * 100) if parts[36] else None
            amount = float(parts[37]) * 10000.0 if parts[37] else None
            bar = Bar(
                symbol=code,
                trade_date=trade_date,
                open=float(parts[5]) if parts[5] else None,
                high=float(parts[33]) if parts[33] else None,
                low=float(parts[34]) if parts[34] else None,
                close=current,
                volume=volume,
                amount=amount,
                pct_change=float(parts[32]) if parts[32] else None,
                source=source,
                adjust="bfq",
            )
        except (ValueError, IndexError):
            continue
        bars.append(bar)
    return bars


def fetch_qt_batch(
    channel: Any,
    symbols: Sequence[str],
    *,
    chunk_size: int = QT_BATCH_SIZE,
    source: str = SOURCE_QT,
) -> list[Bar]:
    """A 股/ETF 当日 bfq 快照：60~100 只/请求。"""
    bars: list[Bar] = []
    codes = [split_market(s)[0] for s in symbols]
    for start in range(0, len(codes), chunk_size):
        chunk = codes[start:start + chunk_size]
        response = channel.get(QT_URL + ",".join(chunk), timeout=15)
        content = getattr(response, "content", None)
        text = (
            content.decode("gbk", errors="replace")
            if isinstance(content, (bytes, bytearray))
            else str(getattr(response, "text", "") or "")
        )
        if is_waf_html(response) or "<html" in text.lower():
            raise SourceParseError(source, f"WAF/HTML 响应（chunk {start}）")
        bars.extend(parse_qt_text(text, source=source))
    return bars


_KLINE_KEY = {"bfq": "day", "hfq": "hfqday"}


def parse_kline_rows(
    payload: dict, symbol: str, adjust: str, *, source: str
) -> list[Bar]:
    """解析 fqkline/hkfqkline 的 data[symbol][day|qfqday|hfqday]。"""
    ensure_adjust(adjust)
    data = (payload.get("data") or {}).get(symbol)
    if not isinstance(data, dict):
        return []
    key = {"bfq": "day", "hfq": "hfqday"}[adjust]
    rows = data.get(key) or []
    bars: list[Bar] = []
    for row in rows:
        try:
            trade_date = date.fromisoformat(str(row[0])[:10])
            close = float(row[2])
            if close <= 0:
                continue
            volume = int(float(row[5])) if len(row) > 5 and row[5] not in (None, "") else None
            bars.append(
                Bar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=float(row[1]) if row[1] not in (None, "") else None,
                    high=float(row[3]) if len(row) > 3 and row[3] not in (None, "") else None,
                    low=float(row[4]) if len(row) > 4 and row[4] not in (None, "") else None,
                    close=close,
                    volume=volume,
                    amount=None,
                    pct_change=None,
                    source=source,
                    adjust=adjust,
                )
            )
        except (ValueError, IndexError, TypeError):
            continue
    return bars


def fetch_kline(
    channel: Any,
    symbol: str,
    adjust: str,
    start: date,
    end: date,
    *,
    market: str = "A",
    count: int = 640,
    source: str | None = None,
) -> list[Bar]:
    """单只标的 kline 抓取（A/ETF 用 fqkline，港股 hfq 用 hkfqkline，港股 bfq 用 fqkline）。"""
    ensure_adjust(adjust)
    qt_symbol, detected_market = split_market(symbol)
    market = market or detected_market
    is_hk = market == "HK"
    path = "hkfqkline" if (is_hk and adjust == "hfq") else "fqkline"
    src = source or (SOURCE_KLINE_HK if is_hk else SOURCE_KLINE_A_ETF)
    kind = "" if adjust == "bfq" else adjust
    params = {"param": ",".join([qt_symbol, "day", start.isoformat(), end.isoformat(), str(count), kind])}
    last_error: Exception | None = None
    for host in KLINE_HOSTS:
        try:
            response = channel.get(f"{host}/{path}/get", timeout=15, params=params)
            payload = json_body(response, source=src)
            return parse_kline_rows(payload, qt_symbol, adjust, source=src)
        except Exception as exc:  # noqa: BLE001 - 主端点 WAF 时换备用端点
            last_error = exc
            if not isinstance(exc, SourceParseError):
                raise
    raise last_error or SourceParseError(src, "全部端点失败")

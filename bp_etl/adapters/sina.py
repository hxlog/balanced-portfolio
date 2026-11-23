"""新浪适配器：A 股 hfq 因子 / 港股 bfq / ETF bfq。

关键设计（口径与性能兼顾）：
- A 股 hfq = 不复权价 × 新浪 hfq 因子（因子文件为轻量 JSON，无需 V8 解码）；
  因此日更只需 1 次因子请求 + 当日 bfq（腾讯 qt 批量已有），重建时用库内 bfq 历史 × 因子。
- 港股 bfq / ETF bfq 复用 akshare 的 JS 解码实现（新浪 klc 文件需要 V8），
  只在需要时惰性 import，避免常驻内存。
- 任何源异常 → `SourceParseError` / `SourceUnavailable`；qfq 直接拒绝。
"""

from __future__ import annotations

import ast
import re
from datetime import date
from typing import Any, Iterable, Sequence

from .base import Bar, SourceParseError, SourceUnavailable, ensure_adjust

SOURCE_A = "sina_kline"
SOURCE_HK = "sina_hk_kline"
SOURCE_ETF = "sina_etf_kline"

A_HFQ_FACTOR_URL = "https://finance.sina.com.cn/realstock/company/{}/hfq.js"
_FACTOR_RE = re.compile(r"=\s*(\{.*\})\s*;?", re.S)


def parse_hfq_factor(text: str, *, source: str = SOURCE_A) -> list[tuple[date, float]]:
    """解析 hfq.js：`var _hfq_factor = {"data":[["YYYY-MM-DD", 1.234], ...]}`。"""
    if not text or "<html" in text[:200].lower():
        raise SourceParseError(source, "hfq 因子响应为 HTML/WAF")
    match = _FACTOR_RE.search(text)
    if not match:
        raise SourceParseError(source, "hfq 因子格式无法识别")
    try:
        payload = ast.literal_eval(match.group(1))
        rows = payload.get("data") or []
    except (ValueError, SyntaxError) as exc:
        raise SourceParseError(source, f"hfq 因子解析失败: {type(exc).__name__}") from exc
    factors: list[tuple[date, float]] = []
    for row in rows:
        try:
            factors.append((date.fromisoformat(str(row[0])[:10]), float(row[1])))
        except (ValueError, IndexError, TypeError):
            continue
    factors.sort(key=lambda item: item[0])
    return factors


def fetch_hfq_factor(
    channel: Any, symbol: str, *, source: str = SOURCE_A
) -> list[tuple[date, float]]:
    response = channel.get(A_HFQ_FACTOR_URL.format(symbol), timeout=20)
    text = _response_text(response)
    return parse_hfq_factor(text, source=source)


def _response_text(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return content.decode("utf-8", errors="replace")
    return str(getattr(response, "text", "") or "")


def _fmt_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def build_hfq_from_bfq(
    bfq_bars: Sequence[Bar],
    factors: Sequence[tuple[date, float]],
    *,
    source: str = SOURCE_A,
) -> list[Bar]:
    """hfq = bfq × 当日有效因子（因子 ffill；除权日因子变化自然生效）。"""
    if not bfq_bars:
        return []
    if not factors:
        raise SourceParseError(source, "hfq 因子为空")
    points = sorted(factors)
    out: list[Bar] = []
    idx = 0
    current = points[0][1]
    for bar in sorted(bfq_bars, key=lambda item: item.trade_date):
        while idx < len(points) and points[idx][0] <= bar.trade_date:
            current = points[idx][1]
            idx += 1
        out.append(
            Bar(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                open=_mul(bar.open, current),
                high=_mul(bar.high, current),
                low=_mul(bar.low, current),
                close=bar.close * current,
                volume=bar.volume,
                amount=bar.amount,
                pct_change=bar.pct_change,
                source=source,
                adjust="hfq",
            )
        )
    return out


def _mul(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _akshare() -> Any:
    try:
        import akshare as ak  # 惰性 import：V8/pandas 只在港股/ETF 路径加载
        return ak
    except Exception as exc:  # pragma: no cover - 环境缺依赖
        raise SourceUnavailable(SOURCE_HK, f"akshare 不可用: {type(exc).__name__}") from exc


def _df_to_bars(df: Any, symbol: str, *, source: str, adjust: str = "bfq") -> list[Bar]:
    if df is None or len(df) == 0:
        return []
    bars: list[Bar] = []
    for row in df.to_dict("records"):
        try:
            trade_date = _fmt_date(row.get("date"))
            close = float(row.get("close"))
            if close <= 0:
                continue
            volume = row.get("volume")
            bars.append(
                Bar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=_opt_float(row.get("open")),
                    high=_opt_float(row.get("high")),
                    low=_opt_float(row.get("low")),
                    close=close,
                    volume=int(float(volume)) if volume not in (None, "") else None,
                    amount=_opt_float(row.get("amount")),
                    pct_change=None,
                    source=source,
                    adjust=adjust,
                )
            )
        except (ValueError, TypeError, KeyError):
            continue
    return bars


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def fetch_hk_bfq(
    channel: Any, symbol: str, start: date, end: date, *, source: str = SOURCE_HK
) -> list[Bar]:
    """港股 bfq（新浪）——akshare 解码 klc/js，失败抛 SourceUnavailable。"""
    channel.throttle()
    code = symbol.strip().lower()
    if code.startswith("hk"):
        code = code[2:]
    try:
        df = _akshare().stock_hk_daily(symbol=code, adjust="")
    except Exception as exc:  # noqa: BLE001 - akshare 内部错误统一降级
        raise SourceUnavailable(source, f"{type(exc).__name__}: {exc}") from exc
    bars = _df_to_bars(df, symbol=code, source=source)
    return [b for b in bars if start <= b.trade_date <= end]


def fetch_etf_bfq(
    channel: Any, symbol: str, start: date, end: date, *, source: str = SOURCE_ETF
) -> list[Bar]:
    """ETF bfq（新浪，无复权）；返回原始价。"""
    channel.throttle()
    code = symbol.strip().lower()
    try:
        df = _akshare().fund_etf_hist_sina(symbol=code)
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(source, f"{type(exc).__name__}: {exc}") from exc
    bars = _df_to_bars(df, symbol=code, source=source)
    return [b for b in bars if start <= b.trade_date <= end]

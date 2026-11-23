"""东财适配器：push2his K 线（仅 relay 通道）+ 基金净值直连（rankhandler/lsjz）。

约束：
- EM push2his 已封禁生产服务器直连 IP（2026-11-21 起），**只允许 relay 通道**；
  若传入直连通道立即 `SourceUnavailable`，避免无效打点/加重封禁。
- 天天基金 rankhandler/lsjz 走 `fund.eastmoney.com`/`api.fund.eastmoney.com`，直连可用。
- 成交量东财单位为「手」（1 手=100 股），统一换算为「股」；amount 为元。
- qfq 停用：任何调用收到 qfq 立即 ValueError。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Sequence

from .base import Bar, NavRow, SourceParseError, SourceUnavailable, ensure_adjust

SOURCE_KLINE = "em_kline"
SOURCE_RANK = "em_rankhandler"
SOURCE_LSJZ = "em_lsjz"

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"

RANK_PAGE_SIZE = 500
_FQT = {"bfq": "0", "hfq": "2"}


def em_secid(symbol: str, market: str | None = None) -> str:
    """代码 → 东财 secid（1=沪、0=深/北、116=港股）。"""
    code = symbol.strip().lower()
    if code.startswith("hk"):
        return "116." + code[2:]
    if code.startswith(("sh", "sz", "bj")):
        prefix, code = code[:2], code[2:]
        return ("1." if prefix == "sh" else "0.") + code
    if len(code) == 5 and (market or "").upper() == "HK":
        return "116." + code
    if not code:
        raise ValueError("空代码")
    head = code[0]
    if head in ("6", "9", "5"):
        return "1." + code
    return "0." + code


def _date_compact(value: date) -> str:
    return value.strftime("%Y%m%d")


def parse_kline_payload(payload: dict, symbol: str, adjust: str, *, source: str = SOURCE_KLINE) -> list[Bar]:
    ensure_adjust(adjust)
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    bars: list[Bar] = []
    for item in klines:
        parts = str(item).split(",")
        if len(parts) < 6:
            continue
        try:
            trade_date = date.fromisoformat(parts[0][:10])
            close = float(parts[2])
            if close <= 0:
                continue
            volume = int(float(parts[5])) * 100 if parts[5] not in ("", "-") else None
            bars.append(
                Bar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=float(parts[1]) if parts[1] not in ("", "-") else None,
                    high=float(parts[3]) if parts[3] not in ("", "-") else None,
                    low=float(parts[4]) if parts[4] not in ("", "-") else None,
                    close=close,
                    volume=volume,
                    amount=float(parts[6]) if len(parts) > 6 and parts[6] not in ("", "-") else None,
                    pct_change=float(parts[7]) if len(parts) > 7 and parts[7] not in ("", "-") else None,
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
    market: str | None = None,
    source: str = SOURCE_KLINE,
) -> list[Bar]:
    ensure_adjust(adjust)
    if getattr(channel, "channel_kind", "direct") == "direct":
        raise SourceUnavailable(source, "EM push2his 封禁服务器直连 IP，必须经 relay 通道")
    secid = em_secid(symbol, market)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": _FQT[adjust],
        "beg": _date_compact(start),
        "end": _date_compact(end),
    }
    response = channel.get(KLINE_URL, timeout=25, params=params)
    payload = _json(response, source)
    return parse_kline_payload(payload, symbol, adjust, source=source)


def _json(response: Any, source: str) -> dict:
    text = _text(response).strip()
    if text.startswith("<"):
        raise SourceParseError(source, "WAF/HTML 响应（非 JSON）")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise SourceParseError(source, f"JSON 解析失败: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SourceParseError(source, f"JSON 顶层类型异常: {type(payload).__name__}")
    return payload


def _text(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return content.decode("utf-8", errors="replace")
    return str(getattr(response, "text", "") or "")


# ---------------------------------------------------------------------------
# 基金净值
# ---------------------------------------------------------------------------
def parse_rankhandler_text(text: str, *, source: str = SOURCE_RANK) -> tuple[list[NavRow], int]:
    """解析 rankhandler 批量榜：`datas:["code,name,pinyin,date,nav,acc,...",...],allRecords`。"""
    if not text or text.lstrip().startswith("<"):
        raise SourceParseError(source, "rankhandler 返回 HTML/WAF")
    all_pages = 0
    match = re.search(r"allPages:(\d+)", text)
    if match:
        all_pages = int(match.group(1))
    block = re.search(r"datas:\[(.*?)\],allRecords", text, re.S)
    if not block:
        raise SourceParseError(source, "rankhandler 缺少 datas 块")
    rows: list[NavRow] = []
    for item in re.findall(r'"([^"]+)"', block.group(1)):
        parts = item.split(",")
        if len(parts) < 6:
            continue
        try:
            trade_date = date.fromisoformat(parts[3].strip())
            nav = float(parts[4]) if parts[4].strip() else None
        except ValueError:
            continue
        if nav is None:
            continue
        try:
            acc_nav = float(parts[5]) if parts[5].strip() else None
        except ValueError:
            acc_nav = None
        rows.append(NavRow(parts[0].strip(), trade_date, nav, acc_nav, source))
    return rows, all_pages


def fetch_rankhandler(
    channel: Any, page: int = 1, *, page_size: int = RANK_PAGE_SIZE, source: str = SOURCE_RANK
) -> tuple[list[NavRow], int]:
    params = {
        "op": "ph", "dt": "kf", "ft": "all", "rs": "", "gs": "0",
        "sc": "1nzf", "st": "desc", "sd": "", "ed": "", "qdii": "",
        "tabSubtype": ",,,,", "pi": str(page), "pn": str(page_size), "dx": "1", "v": "0.1",
    }
    response = channel.get(RANK_URL, timeout=30, params=params, headers={"Referer": "https://fund.eastmoney.com/data/fundranking.html"})
    return parse_rankhandler_text(_text(response), source=source)


def parse_lsjz_payload(payload: dict, code: str, *, source: str = SOURCE_LSJZ) -> list[NavRow]:
    items = ((payload or {}).get("Data") or {}).get("LSJZList") or []
    rows: list[NavRow] = []
    for item in items:
        try:
            trade_date = date.fromisoformat(str(item.get("FSRQ") or "")[:10])
            nav_text = str(item.get("DWJZ") or "").strip()
            nav = float(nav_text) if nav_text else None
        except ValueError:
            continue
        if nav is None:
            continue
        try:
            acc_text = str(item.get("LJJZ") or "").strip()
            acc_nav = float(acc_text) if acc_text else None
        except ValueError:
            acc_nav = None
        rows.append(NavRow(code, trade_date, nav, acc_nav, source))
    return rows


def fetch_lsjz(
    channel: Any, code: str, *, page_size: int = 40, source: str = SOURCE_LSJZ
) -> list[NavRow]:
    params = {"fundCode": code, "pageIndex": "1", "pageSize": str(page_size)}
    response = channel.get(LSJZ_URL, timeout=25, params=params, headers={"Referer": "https://fundf10.eastmoney.com/"})
    return parse_lsjz_payload(_json(response, source), code, source=source)

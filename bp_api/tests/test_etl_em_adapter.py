"""东财适配器测试（T6，离线 fixture）。"""
from __future__ import annotations

from datetime import date

import pytest

from bp_etl.adapters.base import SourceParseError, SourceUnavailable
from bp_etl.adapters.eastmoney import (
    em_secid,
    fetch_kline,
    fetch_lsjz,
    fetch_rankhandler,
    parse_kline_payload,
    parse_lsjz_payload,
    parse_rankhandler_text,
)


class FakeResponse:
    def __init__(self, *, payload: object = None, text: str = "", status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeChannel:
    def __init__(self, responses: list[FakeResponse], *, channel_kind: str = "relay_sg") -> None:
        self.channel_kind = channel_kind
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kw: object) -> FakeResponse:
        self.calls.append((url, dict(kw.get("params") or {})))
        return self.responses.pop(0)

    def throttle(self) -> float:
        return 0.0


KLINE_PAYLOAD = {
    "rc": 0,
    "data": {
        "klines": [
            "2026-11-23,43.73,43.26,44.00,43.09,1262451,5647891234.00,-1.68",
            "2026-11-20,43.15,44.00,44.16,42.70,1520134,6789012345.00,1.20",
        ]
    },
}

RANK_TEXT = (
    'var rankData = {datas:["000001,华夏成长混合,HXCZ,2026-11-23,1.2340,3.4560,'
    '0.50,2026-11-22,1.2278,3.4498,0.50,1.00,0.00,0.00,0.00,0.00,0.00,0.00,0"],'
    'allRecords:1,allPages:42};'
)


def test_em_secid_mapping() -> None:
    assert em_secid("600036") == "1.600036"
    assert em_secid("000001") == "0.000001"
    assert em_secid("510300") == "1.510300"
    assert em_secid("159915") == "0.159915"
    assert em_secid("830799") == "0.830799"
    assert em_secid("00700", "HK") == "116.00700"
    assert em_secid("hk00700") == "116.00700"


def test_parse_kline_payload() -> None:
    bars = parse_kline_payload(KLINE_PAYLOAD, "600036", "hfq")
    assert len(bars) == 2
    first = bars[0]
    assert first.trade_date == date(2026, 11, 23)
    assert first.open == pytest.approx(43.73)
    assert first.high == pytest.approx(44.0)
    assert first.low == pytest.approx(43.09)
    assert first.close == pytest.approx(43.26)
    assert first.volume == 126245100  # 东财手 → 股
    assert first.amount == pytest.approx(5647891234.0)
    assert first.pct_change == pytest.approx(-1.68)
    assert first.adjust == "hfq"


def test_parse_kline_rejects_qfq() -> None:
    with pytest.raises(ValueError, match="qfq 已停用"):
        parse_kline_payload(KLINE_PAYLOAD, "600036", "qfq")


def test_fetch_kline_requires_relay_channel() -> None:
    channel = FakeChannel([FakeResponse(payload=KLINE_PAYLOAD)], channel_kind="direct")
    with pytest.raises(SourceUnavailable, match="relay"):
        fetch_kline(channel, "600036", "hfq", date(2026, 11, 18), date(2026, 11, 23))


def test_fetch_kline_relay_request() -> None:
    channel = FakeChannel([FakeResponse(payload=KLINE_PAYLOAD)])
    bars = fetch_kline(channel, "600036", "bfq", date(2026, 11, 18), date(2026, 11, 23))
    url, params = channel.calls[0]
    assert url == "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    assert params["secid"] == "1.600036"
    assert params["fqt"] == "0"
    assert params["beg"] == "20261118"
    assert len(bars) == 2


def test_parse_rankhandler_text() -> None:
    rows, pages = parse_rankhandler_text(RANK_TEXT)
    assert pages == 42
    assert len(rows) == 1
    row = rows[0]
    assert row.fund_code == "000001"
    assert row.trade_date == date(2026, 11, 23)
    assert row.nav == pytest.approx(1.234)
    assert row.acc_nav == pytest.approx(3.456)
    assert row.source == "em_rankhandler"


def test_parse_rankhandler_rejects_html() -> None:
    with pytest.raises(SourceParseError):
        parse_rankhandler_text("<html>WAF</html>")


def test_fetch_rankhandler_params() -> None:
    channel = FakeChannel([FakeResponse(text=RANK_TEXT)])
    rows, pages = fetch_rankhandler(channel, page=2)
    assert len(rows) == 1 and pages == 42
    _, params = channel.calls[0]
    assert params["pi"] == "2"
    assert params["pn"] == "500"


def test_fetch_lsjz() -> None:
    payload = {"Data": {"LSJZList": [
        {"FSRQ": "2026-11-23", "DWJZ": "1.2340", "LJJZ": "3.4560"},
        {"FSRQ": "2026-11-20", "DWJZ": "1.2278", "LJJZ": "3.4498"},
    ]}}
    channel = FakeChannel([FakeResponse(payload=payload)])
    rows = fetch_lsjz(channel, "110011")
    assert len(rows) == 2
    assert rows[0].trade_date == date(2026, 11, 23)
    assert rows[0].nav == pytest.approx(1.234)
    assert rows[0].source == "em_lsjz"


def test_parse_lsjz_skips_bad_rows() -> None:
    rows = parse_lsjz_payload({"Data": {"LSJZList": [
        {"FSRQ": "bad-date", "DWJZ": "1.1"},
        {"FSRQ": "2026-11-23", "DWJZ": ""},
        {"FSRQ": "2026-11-23", "DWJZ": "2.0", "LJJZ": "x"},
    ]}}, "110011")
    assert len(rows) == 1 and rows[0].acc_nav is None

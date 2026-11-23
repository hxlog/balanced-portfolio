"""腾讯适配器测试（T4，离线 fixture）。"""
from __future__ import annotations

import json
from datetime import date

import pytest

from bp_etl.adapters.base import SourceParseError
from bp_etl.adapters.tencent import (
    fetch_kline,
    fetch_qt_batch,
    parse_kline_rows,
    parse_qt_text,
    split_market,
)


class FakeResponse:
    def __init__(self, payload: object = None, *, status_code: int = 200,
                 content: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8", errors="replace") if content else str(payload)
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> object:
        if self._payload is None:
            raise json.JSONDecodeError("no payload", "", 0)
        return self._payload


class FakeChannel:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []
        self.params: list[dict] = []

    def get(self, url: str, **kw: object) -> FakeResponse:
        self.calls.append(url)
        self.params.append(dict(kw.get("params") or {}))
        return self.responses.pop(0)


def _qt_line(code: str = "600036", stamp: str = "20261123161442") -> str:
    parts = [""] * 38
    parts[1] = "招商银行"
    parts[2] = code
    parts[3] = "43.26"
    parts[5] = "43.73"
    parts[30] = stamp
    parts[32] = "-1.68"
    parts[33] = "44.000"
    parts[34] = "43.090"
    parts[36] = "1262451"
    parts[37] = "556789.12"
    return 'v_' + code + '="' + "~".join(parts) + '";'


def test_split_market() -> None:
    assert split_market("600036") == ("sh600036", "A")
    assert split_market("000001") == ("sz000001", "A")
    assert split_market("00700") == ("hk00700", "HK")
    assert split_market("sh510300") == ("sh510300", "A")


def test_parse_qt_text() -> None:
    bars = parse_qt_text(_qt_line())
    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "600036"
    assert bar.trade_date == date(2026, 11, 23)
    assert bar.open == pytest.approx(43.73)
    assert bar.high == pytest.approx(44.0)
    assert bar.low == pytest.approx(43.09)
    assert bar.close == pytest.approx(43.26)
    assert bar.volume == 126245100
    assert bar.amount == pytest.approx(556789.12 * 10000)
    assert bar.adjust == "bfq"


def test_parse_qt_skips_bad_lines() -> None:
    text = "garbage;v_bad=\"1~2~3\";" + _qt_line()
    bars = parse_qt_text(text)
    assert [b.symbol for b in bars] == ["600036"]


def test_fetch_qt_batch_chunks() -> None:
    chunk1 = _qt_line("600036")
    chunk2 = _qt_line("600519")
    channel = FakeChannel([
        FakeResponse(content=chunk1.encode("gbk")),
        FakeResponse(content=chunk2.encode("gbk")),
    ])
    bars = fetch_qt_batch(channel, ["600036", "600519"], chunk_size=1)
    assert [b.symbol for b in bars] == ["600036", "600519"]
    assert len(channel.calls) == 2
    assert channel.calls[0].startswith("https://qt.gtimg.cn/q=")


def test_fetch_qt_batch_rejects_waf_html() -> None:
    channel = FakeChannel([FakeResponse(content=b"<html>WAF</html>", headers={"content-type": "text/html"})])
    with pytest.raises(SourceParseError):
        fetch_qt_batch(channel, ["600036"])


def test_parse_kline_rows() -> None:
    payload = {
        "code": 0,
        "data": {
            "sh600036": {
                "day": [["2026-11-23", "43.730", "43.260", "44.000", "43.090", "1262451.000"]],
                "hfqday": [["2026-11-23", "231.413", "229.588", "232.461", "228.928", "1262451.000"]],
            }
        },
    }
    bfq = parse_kline_rows(payload, "sh600036", "bfq", source="tencent_kline")
    hfq = parse_kline_rows(payload, "sh600036", "hfq", source="tencent_kline")
    assert len(bfq) == 1 and len(hfq) == 1
    assert bfq[0].close == pytest.approx(43.26)
    assert hfq[0].close == pytest.approx(229.588)
    assert hfq[0].volume == 1262451


def test_parse_kline_rejects_qfq() -> None:
    with pytest.raises(ValueError, match="qfq 已停用"):
        parse_kline_rows({"data": {}}, "sh600036", "qfq", source="tencent_kline")


def test_fetch_kline_hk_hfq_uses_hkfqkline() -> None:
    payload = {"data": {"hk00700": {"hfqday": [["2026-11-23", "335.0", "344.0", "344.6", "333.0", "35289665"]]}}}
    channel = FakeChannel([FakeResponse(payload=payload)])
    bars = fetch_kline(channel, "00700", "hfq", date(2026, 11, 18), date(2026, 11, 23), market="HK")
    assert channel.calls[0].endswith("/hkfqkline/get")
    assert bars[0].symbol == "hk00700" and bars[0].close == pytest.approx(344.0)


def test_fetch_kline_falls_back_to_proxy_host_on_waf() -> None:
    payload = {"data": {"sh600036": {"hfqday": [["2026-11-23", "1", "2", "3", "1", "10"]]}}}
    channel = FakeChannel([
        FakeResponse(content=b"<html>501 WAF</html>", headers={"content-type": "text/html"}),
        FakeResponse(payload=payload),
    ])
    bars = fetch_kline(channel, "600036", "hfq", date(2026, 11, 18), date(2026, 11, 23))
    assert len(channel.calls) == 2
    assert "proxy.finance.qq.com" in channel.calls[1]
    assert bars[0].adjust == "hfq"

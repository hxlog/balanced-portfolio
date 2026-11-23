"""新浪适配器测试（T5，离线 fixture）。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import bp_etl.adapters.sina as sina
from bp_etl.adapters.base import Bar, SourceParseError
from bp_etl.adapters.sina import (
    build_hfq_from_bfq,
    fetch_etf_bfq,
    fetch_hfq_factor,
    fetch_hk_bfq,
    parse_hfq_factor,
)

FACTOR_TEXT = 'var _hfq_factor = {"total":3,"data":[["2020-01-02",1.0],["2021-07-01",1.25],["2026-11-01",1.4]]};\n'


class FakeResponse:
    def __init__(self, text: str, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self.content = text.encode("utf-8")
        self.text = text
        self.headers = {"content-type": "application/json"}


class FakeChannel:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[str] = []
        self.throttled = 0

    def get(self, url: str, **kw: object) -> FakeResponse:
        self.calls.append(url)
        return self.responses.pop(0)

    def throttle(self) -> float:
        self.throttled += 1
        return 0.0


def _bfq(symbol: str = "600036", trade_date: date = date(2026, 11, 20), close: float = 43.0) -> Bar:
    return Bar(
        symbol=symbol, trade_date=trade_date, open=close - 0.5, high=close + 1,
        low=close - 1, close=close, volume=100, amount=4300.0,
        source="tencent_qt", adjust="bfq",
    )


def test_parse_hfq_factor() -> None:
    factors = parse_hfq_factor(FACTOR_TEXT)
    assert factors == [
        (date(2020, 1, 2), 1.0),
        (date(2021, 7, 1), 1.25),
        (date(2026, 11, 1), 1.4),
    ]


def test_parse_hfq_factor_supports_new_dict_format() -> None:
    factors = parse_hfq_factor(FACTOR_TEXT_NEW)
    assert factors == [
        (date(2026, 1, 16), 6.562194383141),
        (date(2026, 7, 10), 6.7422879877129),
    ]


def test_parse_hfq_factor_rejects_html() -> None:
    with pytest.raises(SourceParseError):
        parse_hfq_factor("<html>WAF</html>")


def test_fetch_hfq_factor_uses_channel() -> None:
    channel = FakeChannel([FakeResponse(FACTOR_TEXT)])
    factors = fetch_hfq_factor(channel, "sh600036")
    assert len(factors) == 3
    assert channel.calls[0] == "https://finance.sina.com.cn/realstock/company/sh600036/hfq.js"


def test_build_hfq_from_bfq_applies_factor_by_date() -> None:
    bars = [
        _bfq(trade_date=date(2026, 10, 30), close=40.0),
        _bfq(trade_date=date(2026, 11, 2), close=42.0),
    ]
    factors = [(date(2020, 1, 2), 1.0), (date(2026, 11, 1), 1.4)]
    hfq = build_hfq_from_bfq(bars, factors)
    assert [b.adjust for b in hfq] == ["hfq", "hfq"]
    assert hfq[0].close == pytest.approx(40.0)  # 11-01 前用旧因子 1.0
    assert hfq[1].close == pytest.approx(58.8)  # 11-01 起 1.4
    assert hfq[1].volume == 100
    assert hfq[1].open == pytest.approx((42.0 - 0.5) * 1.4)


def test_build_hfq_requires_factors() -> None:
    with pytest.raises(SourceParseError):
        build_hfq_from_bfq([_bfq()], [])


class FakeAk:
    def __init__(self, df: pd.DataFrame | None = None, *, error: Exception | None = None) -> None:
        self.df = df
        self.error = error
        self.calls: list[dict] = []

    def stock_hk_daily(self, **kw: object) -> pd.DataFrame:
        self.calls.append(dict(kw, fn="hk"))
        if self.error:
            raise self.error
        return self.df if self.df is not None else pd.DataFrame()

    def fund_etf_hist_sina(self, **kw: object) -> pd.DataFrame:
        self.calls.append(dict(kw, fn="etf"))
        if self.error:
            raise self.error
        return self.df if self.df is not None else pd.DataFrame()


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_fetch_hk_bfq(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _df([
        {"date": date(2026, 11, 20), "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
        {"date": date(2026, 11, 23), "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
    ])
    fake = FakeAk(df)
    monkeypatch.setattr(sina, "_akshare", lambda: fake)
    channel = FakeChannel()
    bars = fetch_hk_bfq(channel, "hk00700", date(2026, 11, 21), date(2026, 11, 23))
    assert len(bars) == 1
    assert bars[0].symbol == "00700" and bars[0].close == pytest.approx(3.0)
    assert bars[0].trade_date == date(2026, 11, 23)
    assert channel.throttled == 1
    assert fake.calls[0]["fn"] == "hk"


def test_fetch_etf_bfq(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _df([{"date": date(2026, 11, 23), "open": 4.0, "high": 4.1, "low": 3.9, "close": 4.05, "volume": 1000}])
    fake = FakeAk(df)
    monkeypatch.setattr(sina, "_akshare", lambda: fake)
    channel = FakeChannel()
    bars = fetch_etf_bfq(channel, "sh510300", date(2026, 11, 23), date(2026, 11, 23))
    assert len(bars) == 1 and bars[0].close == pytest.approx(4.05)
    assert bars[0].source == "sina_etf_kline"
    assert fake.calls[0]["fn"] == "etf"
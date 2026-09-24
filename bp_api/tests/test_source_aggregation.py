"""多源聚合降级与逻辑源分组的单元测试。"""

from __future__ import annotations

import dataclasses
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
import requests

from bp_ingest import sources as src

# yfinance 对 Yahoo 429 抛自家 YFRateLimitError(非 requests 系, MRO: YFRateLimitError
# → YFException → Exception), 是 crypto 降级链的头号触发场景; 缺 yfinance 时跳过该参数。
try:
    from yfinance.exceptions import YFRateLimitError  # type: ignore[attr-defined]

    _HAS_YF_RATE_EXC = True
except Exception:  # noqa: BLE001
    YFRateLimitError = None  # type: ignore[assignment,misc]
    _HAS_YF_RATE_EXC = False


def _df(dates, closes):
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100] * len(dates),
            "amount": [None] * len(dates),
            "turnover_rate": [None] * len(dates),
            "pct_change": [None] * len(dates),
        }
    )


def _raise_http_error(symbol, start, end, extra):
    raise requests.exceptions.HTTPError("429 Too Many Requests")


def _raise_yf_rate_limit(symbol, start, end, extra):
    raise YFRateLimitError()


def test_align_fallback_scales_to_base_close():
    """降级源按重叠日收盘比值重锚到主源口径(腾讯 hfq 单位净值 → 东财 hfq 价格)。"""
    base = _df([date(2026, 8, 1), date(2026, 8, 2)], [100.0, 101.0])
    fb = _df([date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)], [1.0, 1.01, 1.02])
    aligned = src._align_fallback_to_base(base, fb)
    # 重叠日(08-02) 101/1.01 = 100 → 08-03 close 1.02*100 = 102.0
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(102.0)


def test_align_fallback_uses_anchor_close_when_no_overlap():
    """主源整段失败、无重叠时, 用库中锚点 close 对齐降级源。"""
    fb = _df([date(2026, 8, 3), date(2026, 8, 4)], [1.09, 1.10])
    aligned = src._align_fallback_to_base(None, fb, anchor_close=109.0, anchor_date=date(2026, 8, 3))
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(109.0)
    assert aligned[aligned["trade_date"] == date(2026, 8, 4)]["close"].iloc[0] == pytest.approx(110.0)


def test_align_fallback_weekend_anchor_uses_nearest_prior_row():
    """周末锚点(BTC 现货 7 天周)在 CME 期货帧(工作日)无精确行时, 取 ≤锚点日最近一根重锚。

    若直接原样返回, 未缩放的期货基差价会混入现货序列, 违反「绝不混用原始绝对价」。
    """
    fb = _df([date(2026, 9, 3), date(2026, 9, 4)], [110000.0, 111000.0])  # 周四/周五
    # 锚点 09-06 是周日, 期货帧无该日 → 取 09-04(周五) close 111000, ratio = 222000/111000 = 2
    aligned = src._align_fallback_to_base(
        None, fb, anchor_close=222000.0, anchor_date=date(2026, 9, 6)
    )
    assert aligned[aligned["trade_date"] == date(2026, 9, 3)]["close"].iloc[0] == pytest.approx(220000.0)
    assert aligned[aligned["trade_date"] == date(2026, 9, 4)]["close"].iloc[0] == pytest.approx(222000.0)
    assert aligned[aligned["trade_date"] == date(2026, 9, 4)]["open"].iloc[0] == pytest.approx(222000.0)


def test_align_fallback_stale_anchor_beyond_tolerance_noop():
    """锚点晚于降级帧最后一根超 7 天容差 → 无可用锚, 原样返回(未缩放)。"""
    fb = _df([date(2026, 9, 3), date(2026, 9, 4)], [110000.0, 111000.0])
    # 锚点 10-04 距最近可用行 09-04 有 30 天 > 容差 7 天
    aligned = src._align_fallback_to_base(
        None, fb, anchor_close=222000.0, anchor_date=date(2026, 10, 4)
    )
    assert aligned[aligned["trade_date"] == date(2026, 9, 3)]["close"].iloc[0] == pytest.approx(110000.0)
    assert aligned[aligned["trade_date"] == date(2026, 9, 4)]["close"].iloc[0] == pytest.approx(111000.0)


def test_align_fallback_noop_when_ratio_one():
    fb = _df([date(2026, 8, 3)], [50.0])
    aligned = src._align_fallback_to_base(None, fb, anchor_close=50.0, anchor_date=date(2026, 8, 3))
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(50.0)


def test_tx_market_prefix():
    assert src._tx_market_prefix("510300") == "sh510300"
    assert src._tx_market_prefix("159915") == "sz159915"
    assert src._tx_market_prefix("sh000300") == "sh000300"


def test_aggregate_chains_include_tencent_etf_fallback():
    """东财 ETF 主源应降级腾讯(后复权), 不再降级新浪(无复权)。"""
    assert src.AGGREGATE_CHAINS["etf_em"] == ["etf_tx"]
    assert "etf_sina" not in src.AGGREGATE_CHAINS.get("etf_em", [])
    assert "index_tx" in src.AGGREGATE_CHAINS["cn_index_em"]


# ---------------------------------------------------------------------
# btc_cme_sina: yfinance BTC-USD 的境内降级源 (akshare futures_foreign_hist)
# ---------------------------------------------------------------------
def _fake_btc_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-09-01", "2026-09-02", "2026-09-03"],
            "open": [108000.0, 109000.0, 110000.0],
            "high": [109500.0, 110500.0, 111500.0],
            "low": [107500.0, 108500.0, 109500.0],
            "close": [109000.0, 110000.0, 111000.0],
            "volume": [1000, 1100, 1200],
        }
    )


def test_btc_cme_sina_registered_and_normalized():
    adapter = src.get_adapter("btc_cme_sina")
    assert adapter.akshare_func == "futures_foreign_hist"
    with patch.object(src.ak, "futures_foreign_hist", return_value=_fake_btc_raw()):
        df = adapter.fetch("BTC-USD", date(2026, 9, 1), date(2026, 9, 3), {})
    assert list(df["trade_date"]) == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert float(df["close"].iloc[-1]) == 111000.0


@pytest.mark.parametrize(
    "raiser",
    [
        pytest.param(
            _raise_yf_rate_limit,
            id="yf-rate-limit",
            marks=pytest.mark.skipif(
                not _HAS_YF_RATE_EXC, reason="yfinance.exceptions.YFRateLimitError 不可用"
            ),
        ),
        pytest.param(_raise_http_error, id="requests-http-error"),
    ],
)
def test_crypto_yfinance_chain_falls_back_on_rate_limit(raiser):
    """Yahoo 429 触发 crypto 降级链: yfinance 实际抛的 YFRateLimitError 与
    requests.HTTPError 均须触发, 降级帧经库中锚点重锚到现货口径。"""
    assert src.AGGREGATE_CHAINS.get("crypto_yfinance") == ["btc_cme_sina"]
    raising = dataclasses.replace(
        src.SOURCES["crypto_yfinance"],
        fetch=raiser,
    )
    with patch.dict(
        src.SOURCES, {"crypto_yfinance": raising}
    ), patch.object(src.ak, "futures_foreign_hist", return_value=_fake_btc_raw()):
        df = src.fetch_with_fallback(
            "crypto_yfinance", "BTC-USD", date(2026, 9, 1), date(2026, 9, 3), {},
            anchor_close=222000.0, anchor_date=date(2026, 9, 3),
        )
    # 库中锚点重锚: 期货 close 111000 → 现货口径 222000 (ratio=2)
    assert abs(float(df["close"].iloc[-1]) - 222000.0) < 1e-6


# ---------------------------------------------------------------------
# 「全链空表」≠「全链被掐断」: 前者是代码不存在, 后者是限频(见 SymbolNotFoundError)
# ---------------------------------------------------------------------
def _empty_fetch(symbol, start, end, extra):
    return pd.DataFrame(columns=src.STANDARD_COLUMNS)


def _conn_error_fetch(symbol, start, end, extra):
    raise requests.exceptions.ConnectionError("curl: (52) Empty reply from server")


def test_all_sources_empty_raises_symbol_not_found():
    """东财对未知 secid 返回 HTTP 200 + 空 klines, 降级源同样空 —— 没有任何源报连接错,
    结论只能是「代码不存在」。若与限频共用 UnreachableSourceError, 写错的代码会被放行落库。"""
    empty = dataclasses.replace(src.SOURCES["etf_em"], fetch=_empty_fetch)
    empty_fb = dataclasses.replace(src.SOURCES["etf_tx"], fetch=_empty_fetch)
    with patch.dict(src.SOURCES, {"etf_em": empty, "etf_tx": empty_fb}):
        with pytest.raises(src.SymbolNotFoundError) as ei:
            src.fetch_with_fallback("etf_em", "999999", date(2026, 8, 1), date(2026, 9, 1), {})
    assert src.classify_probe_error(ei.value) == "invalid"


def test_primary_unreachable_with_empty_fallback_is_unreachable():
    """主源被反爬掐断、降级源恰好好好应答却没数据 —— 仍归 unreachable(重试有意义),
    不能因为降级源「没报错」就把限频误判成代码错误。"""
    down = dataclasses.replace(src.SOURCES["etf_em"], fetch=_conn_error_fetch)
    empty_fb = dataclasses.replace(src.SOURCES["etf_tx"], fetch=_empty_fetch)
    with patch.dict(src.SOURCES, {"etf_em": down, "etf_tx": empty_fb}):
        with pytest.raises(src.UnreachableSourceError) as ei:
            src.fetch_with_fallback("etf_em", "510300", date(2026, 8, 1), date(2026, 9, 1), {})
    assert src.classify_probe_error(ei.value) == "unreachable"


def test_symbol_not_found_is_not_unreachable_subclass():
    """两个异常必须是兄弟而非父子 —— 归错一边就会把死标的放行。"""
    assert not issubclass(src.SymbolNotFoundError, src.UnreachableSourceError)
    assert not issubclass(src.UnreachableSourceError, src.SymbolNotFoundError)

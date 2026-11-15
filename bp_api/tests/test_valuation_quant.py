"""估值分位纯函数单测（P0-T2）。

分位公式（唯一入口，见 ``docs/index-valuation/05-master-plan.md`` §3.5）::

    pct = (count(<x) + 0.5 * count(==x)) / N * 100
        = (count(<=x) - 0.5 * count(==x)) / N * 100

即并列值取其中点 rank（midrank），避免「所有并列值都算严格小于」或
「都算小于等于」造成的系统性偏移。
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from bp_api.quant.valuation import (
    MIN_SAMPLE,
    erp,
    level_of,
    percentile,
    summarize,
    window_slice,
)


# ---------------------------------------------------------------------------
# percentile: 公式与金标准
# ---------------------------------------------------------------------------

def test_percentile_golden_five_values():
    """金标准 1：[10,20,30,40,50] 中 x=30 → (2+0.5)/5*100 = 50%。"""
    assert percentile([10, 20, 30, 40, 50], 30) == pytest.approx(50.0)


def test_percentile_duplicate_values_use_midrank():
    """并列值修正：[10,10,10,20] 中 x=10。

    手算：count(<10)=0，count(==10)=3，N=4
        (0 + 0.5*3)/4*100 = 37.5%

    注意：任务书此处的 12.5% 与所给公式（以及 05/13/14 三份上游文档中的
    `(count(<=x)-0.5*count(==x))/N`）在算术上不一致；12.5% 只在「4 个样本、
    最小值仅出现一次」时成立（见下一个用例）。本测试锁定公式本身。
    """
    assert percentile([10, 10, 10, 20], 10) == pytest.approx(37.5)


def test_percentile_single_minimum_of_four_values_is_12_5():
    """4 个有效样本且最小值只出现一次时：(0+0.5)/4*100 = 12.5%。"""
    assert percentile([10, 20, 30, 40], 10) == pytest.approx(12.5)


@pytest.mark.parametrize("values", [[], [math.nan], [None, math.nan]])
def test_percentile_empty_or_all_missing_returns_none(values):
    assert percentile(values, 10) is None


def test_percentile_ignores_none_and_nan():
    # 有效样本 [10, 20]，x=20 → (1+0.5)/2*100 = 75
    assert percentile([10, None, math.nan, 20], 20) == pytest.approx(75.0)


def test_percentile_missing_current_value_returns_none():
    """当前值缺失时不得静默按 0% 处理（缺失即缺失）。"""
    assert percentile([10, 20, 30], math.nan) is None
    assert percentile([10, 20, 30], None) is None


def test_percentile_at_min_and_max():
    values = [10, 20, 30]
    # min: (0+0.5)/3*100；max: (2+0.5)/3*100
    assert percentile(values, 10) == pytest.approx(100.0 / 6.0)
    assert percentile(values, 30) == pytest.approx(250.0 / 3.0)


# ---------------------------------------------------------------------------
# summarize: 统计量、样本门槛与当前值分位
# ---------------------------------------------------------------------------

def test_summarize_insufficient_sample_returns_none_pct():
    out = summarize(list(range(119)))
    assert out["sample_size"] == 119
    assert out["pct"] is None
    assert out["reason"] == "insufficient_sample"
    assert MIN_SAMPLE == 120


def test_summarize_sufficient_sample_uses_latest_value_for_pct():
    out = summarize(list(range(120)))
    # 当前值 = 最后一个有效值 = 119；count(<119)=119, count(==119)=1
    assert out["sample_size"] == 120
    assert out["pct"] == pytest.approx((119 + 0.5) / 120 * 100)
    assert "reason" not in out


def test_summarize_stats_match_hand_calculation():
    out = summarize([10, 20, 30, 40, 50])
    assert out["pct"] is None  # n=5 < 120
    assert out["mean"] == pytest.approx(30.0)
    assert out["sd"] == pytest.approx(math.sqrt(250.0))  # STDEV.S (n-1)
    assert out["p20"] == pytest.approx(18.0)  # PERCENTILE.INC / linear
    assert out["p50"] == pytest.approx(30.0)
    assert out["p80"] == pytest.approx(42.0)
    assert out["min"] == 10.0
    assert out["max"] == 50.0
    assert out["sample_size"] == 5


def test_summarize_empty_returns_none_fields():
    assert summarize([]) == {
        "pct": None,
        "mean": None,
        "sd": None,
        "p20": None,
        "p50": None,
        "p80": None,
        "min": None,
        "max": None,
        "sample_size": 0,
        "reason": "insufficient_sample",
    }


def test_summarize_single_value_has_no_sd():
    out = summarize([42.0])
    assert out["mean"] == 42.0
    assert out["sd"] is None
    assert out["p20"] == out["p50"] == out["p80"] == 42.0
    assert out["sample_size"] == 1


def test_summarize_counts_only_valid_samples():
    out = summarize([10, None, math.nan, 20, 30])
    assert out["sample_size"] == 3
    assert out["mean"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# window_slice: 5y / 10y / all 边界与缺失值
# ---------------------------------------------------------------------------

def test_window_slice_5y_includes_both_endpoints():
    as_of = date(2026, 11, 14)
    series = [
        (date(2021, 11, 13), 1.0),  # 5y 边界前一天 → 排除
        (date(2021, 11, 14), 2.0),  # 恰在 5y 边界 → 包含
        (date(2024, 6, 1), 3.0),
        (as_of, 4.0),  # as_of 当日 → 包含
        (date(2026, 11, 15), 5.0),  # 未来 → 排除
    ]
    assert window_slice(series, as_of, "5y") == [2.0, 3.0, 4.0]


def test_window_slice_10y_includes_lower_boundary():
    as_of = date(2026, 11, 14)
    series = [
        (date(2016, 11, 13), 1.0),
        (date(2016, 11, 14), 2.0),
        (as_of, 3.0),
    ]
    assert window_slice(series, as_of, "10y") == [2.0, 3.0]


def test_window_slice_all_includes_old_history_and_excludes_future():
    as_of = date(2026, 11, 14)
    series = [
        (date(2005, 1, 1), 1.0),
        (date(2020, 1, 1), 2.0),
        (as_of, 3.0),
        (date(2027, 1, 1), 4.0),
    ]
    assert window_slice(series, as_of, "all") == [1.0, 2.0, 3.0]


def test_window_slice_drops_none_and_nan():
    as_of = date(2026, 11, 14)
    series = [
        (date(2020, 1, 1), None),
        (date(2021, 1, 1), math.nan),
        (as_of, 3.0),
    ]
    assert window_slice(series, as_of, "5y") == [3.0]


def test_window_slice_rejects_unknown_window():
    # 1y/3y/5y/10y/all 都是合法窗口；2y 未定义
    with pytest.raises(ValueError):
        window_slice([], date(2026, 11, 14), "2y")


def test_window_slice_5y_handles_leap_day():
    """as_of=2024-02-29 时，5 年前没有 2/29 → 回退到 2019-02-28。"""
    as_of = date(2024, 2, 29)
    series = [
        (date(2019, 2, 27), 1.0),
        (date(2019, 2, 28), 2.0),
        (as_of, 3.0),
    ]
    assert window_slice(series, as_of, "5y") == [2.0, 3.0]


def test_window_slice_returns_chronological_order_for_unsorted_input():
    """summarize 以最后一个值作为「当前值」，故窗口输出必须按日期升序。"""
    as_of = date(2026, 11, 14)
    series = [
        (as_of, 3.0),
        (date(2024, 1, 1), 1.0),
        (date(2025, 1, 1), 2.0),
    ]
    assert window_slice(series, as_of, "5y") == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# erp / level_of
# ---------------------------------------------------------------------------

def test_erp_in_percentage_points():
    # 股息率是小数(0.0368)，bond10y 已是百分数(1.6123)
    assert erp(0.0368, 1.6123) == pytest.approx(2.0677)


@pytest.mark.parametrize(
    "dividend_yield,bond10y",
    [
        (None, 1.6),
        (0.03, None),
        (None, None),
        (math.nan, 1.6),
        (0.03, math.nan),
    ],
)
def test_erp_missing_either_side_returns_none(dividend_yield, bond10y):
    assert erp(dividend_yield, bond10y) is None


@pytest.mark.parametrize(
    "pct,expected",
    [
        (19.99, "低估"),
        (20.0, "中性"),
        (79.99, "中性"),
        (80.0, "高估"),
    ],
)
def test_level_of_three_tier_boundaries(pct, expected):
    assert level_of(pct) == expected


def test_level_of_none_and_custom_thresholds():
    assert level_of(None) is None
    assert level_of(50.0, low=60, high=90) == "低估"
    assert level_of(95.0, low=60, high=90) == "高估"


# ---------------------------------------------------------------------------
# 多窗口分位（1/3/5/10 年 + 全历史）
# ---------------------------------------------------------------------------

def test_min_sample_for_window_thresholds():
    from bp_api.quant.valuation import min_sample_for

    # 估值序列是周频（约 52 点/年），1 年窗口门槛必须低于 120 才可能有分位
    assert min_sample_for("1y") == 40
    assert min_sample_for("3y") == 120
    assert min_sample_for("5y") == 120
    assert min_sample_for("10y") == 120
    assert min_sample_for("all") == 120
    assert min_sample_for("unknown") == 120


def test_window_slice_1y_and_3y_bounds():
    as_of = date(2026, 11, 14)
    series = [
        (date(2022, 1, 1), 1.0),
        (date(2024, 1, 1), 2.0),
        (date(2026, 1, 1), 3.0),
        (as_of, 4.0),
    ]

    assert window_slice(series, as_of, "1y") == [3.0, 4.0]
    assert window_slice(series, as_of, "3y") == [2.0, 3.0, 4.0]


def test_summarize_respects_custom_min_sample():
    out = summarize([1.0, 2.0, 3.0], min_sample=3)
    assert out["pct"] is not None
    out2 = summarize([1.0, 2.0, 3.0], min_sample=10)
    assert out2["pct"] is None
    assert out2["reason"] == "insufficient_sample"

"""指数 vs 基准日收益描述统计（benchmark_histogram）单元测试（无 DB，伪 cursor）。

覆盖 2026-11-27 第二轮反馈 B3：
- build_return_histograms 同窗口/公共 bins、样本不足返回空；
- get_index_benchmark_stats 返回 histogram + benchmark_histogram 两个同 bin 序列
  （前端据此画对比分布，缺失时退回单系列）。
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from bp_api import repositories_valuation as repo


def _daily_rows(symbol: str, benchmark: bool = False) -> list[tuple]:
    rng = np.random.default_rng(7 if not benchmark else 11)
    rows: list[tuple] = []
    price = 100.0
    day = date(2024, 1, 2)
    for _ in range(320):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price *= float(1.0 + rng.normal(0.0, 0.01))
        rows.append((symbol, day, price))
        day += timedelta(days=1)
    return rows


class _FakeCursor:
    def __init__(self, rows: list[tuple], name: str) -> None:
        self.rows = rows
        self.name = name
        self._pending: list[object] = []

    def execute(self, sql: str, params: object = None) -> None:
        if "FROM bp_index_quote_daily" in sql:
            self._pending.append(self.rows)
        else:
            self._pending.append(None)

    def fetchall(self) -> list[tuple]:
        return self._pending.pop(0)  # type: ignore[return-value]

    def fetchone(self) -> tuple:
        self._pending.pop(0)
        return (self.name,)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConn:
    def __init__(self, rows: list[tuple], name: str = "沪深300") -> None:
        self.rows = rows
        self.name = name

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows, self.name)


def test_build_return_histograms_uses_common_bins_and_counts() -> None:
    rng = np.random.default_rng(3)
    target = rng.normal(0.0, 0.01, 252)
    bench = rng.normal(0.0005, 0.008, 252)
    histogram, benchmark_histogram = repo.build_return_histograms(target, bench)
    assert len(histogram) == repo.BENCHMARK_HISTOGRAM_BINS
    assert len(benchmark_histogram) == len(histogram)
    # 公共 bins：两条序列的 bin 中心一一相同
    assert [item["bin"] for item in histogram] == [item["bin"] for item in benchmark_histogram]
    assert sum(item["count"] for item in histogram) == 252
    assert sum(item["count"] for item in benchmark_histogram) == 252
    # 分布不同 -> 至少一个 bin 计数不同（否则说明基准没真正参与分箱）
    assert any(
        left["count"] != right["count"]
        for left, right in zip(histogram, benchmark_histogram)
    )


@pytest.mark.parametrize(
    "target,bench",
    [
        (np.array([0.01] * 5), np.array([0.01] * 100)),
        (np.array([0.01] * 100), np.array([0.01] * 5)),
        (np.array([]), np.array([0.01] * 100)),
    ],
)
def test_build_return_histograms_insufficient_samples_returns_empty(
    target: np.ndarray, bench: np.ndarray
) -> None:
    assert repo.build_return_histograms(target, bench) == ([], [])


def test_build_return_histograms_ignores_nan() -> None:
    values = np.concatenate([np.full(60, 0.01), np.array([np.nan, np.inf])])
    histogram, _ = repo.build_return_histograms(values, values)
    assert sum(item["count"] for item in histogram) == 60


def test_get_index_benchmark_stats_includes_benchmark_histogram() -> None:
    rows = _daily_rows("IDX1") + _daily_rows("IDX1B", benchmark=True)
    conn = _FakeConn(rows)
    stats = repo.get_index_benchmark_stats(conn, "IDX1", "IDX1B")
    assert stats["histogram"], "指数直方图不应为空"
    assert len(stats["benchmark_histogram"]) == len(stats["histogram"])
    assert [item["bin"] for item in stats["histogram"]] == [
        item["bin"] for item in stats["benchmark_histogram"]
    ]
    assert stats["benchmark_name"] == "沪深300"
    assert stats["n_obs"] == sum(item["count"] for item in stats["histogram"])

import { describe, expect, it } from "vitest";
import {
  backtestFromLatestResult,
  latestResultFromBacktest,
  type LatestResultContext,
} from "./basket-latest-result";
import type { BasketBacktestResult } from "./basket-types";

const CONTEXT: LatestResultContext = {
  lookback_days: 156,
  rebalance_band: 0.05,
  risk_free: 0.02,
};

function backtest(overrides: Partial<BasketBacktestResult> = {}): BasketBacktestResult {
  return {
    method: "risk_parity",
    effective_start: "2023-01-03",
    lookback: 156,
    n_obs: 3,
    nav: [
      { trade_date: "2023-01-03", nav: 0.9987, ret: -0.0013 },
      { trade_date: "2023-01-04", nav: 1.0031, ret: 0.0044 },
      { trade_date: "2023-01-05", nav: 1.0002, ret: -0.0029 },
    ],
    annualized_return: 0.0821,
    annualized_vol: 0.101,
    max_drawdown: -0.1355,
    sharpe: 1.234,
    sortino: 1.876,
    calmar: 0.606,
    trading_days: 244,
    fees: {
      fee_rate: 0.0003,
      slippage_rate: 0.001,
      stamp_duty_rate: 0.001,
      total_cost: 0.0031,
    },
    turnover: 0.84,
    turnover_total: 4.73,
    rebalance_count: 2,
    weights: [
      { symbol: "600519", source: "etl_a_stock", weight: 0.6 },
      { symbol: "000300", source: "cn_index_em", weight: 0.4 },
    ],
    contributions: [],
    rebalances: [],
    metrics: { annualized_return: 0.0821 },
    ...overrides,
  };
}

describe("latestResultFromBacktest", () => {
  it("serializes nav + 7 指标 + fees + 表单上下文", () => {
    const latest = latestResultFromBacktest(backtest(), CONTEXT, "2026-11-27T12:00:00Z");
    expect(latest.method).toBe("risk_parity");
    expect(latest.as_of).toBe("2023-01-05");
    expect(latest.computed_at).toBe("2026-11-27T12:00:00Z");
    expect(latest.effective_start).toBe("2023-01-03");
    expect(latest.lookback_days).toBe(156);
    expect(latest.rebalance_band).toBe(0.05);
    expect(latest.risk_free).toBe(0.02);
    expect(latest.trading_days).toBe(244);
    expect(latest.n_obs).toBe(3);
    expect(latest.max_drawdown).toBe(-0.1355);
    expect(latest.sortino).toBe(1.876);
    expect(latest.calmar).toBe(0.606);
    expect(latest.turnover).toBe(0.84);
    expect(latest.fees?.total_cost).toBe(0.0031);
    expect(latest.assets).toEqual([
      { symbol: "600519", source: "etl_a_stock" },
      { symbol: "000300", source: "cn_index_em" },
    ]);
    expect(latest.nav).toHaveLength(3);
    expect(latest.nav[0]).toEqual({ trade_date: "2023-01-03", nav: 0.9987, ret: -0.0013 });
  });

  it("falls back to metrics for Sortino/Calmar and drops invalid nav points", () => {
    const latest = latestResultFromBacktest(
      backtest({
        sortino: undefined,
        calmar: undefined,
        metrics: { sortino: 0.9, calmar: 0.4 },
        nav: [
          { trade_date: "2023-01-03", nav: 1, ret: 0 },
          { trade_date: "2023-01-04", nav: Number.NaN, ret: 0 },
          { trade_date: "2023-01-05", nav: 1.01, ret: 0.01 },
        ],
      }),
      CONTEXT,
    );
    expect(latest.sortino).toBe(0.9);
    expect(latest.calmar).toBe(0.4);
    expect(latest.nav.map((point) => point.trade_date)).toEqual([
      "2023-01-03",
      "2023-01-05",
    ]);
  });
});

describe("backtestFromLatestResult", () => {
  it("restores nav and 7 指标（打开篮子不重新回测）", () => {
    const latest = latestResultFromBacktest(backtest(), CONTEXT, "2026-11-27T12:00:00Z");
    const restored = backtestFromLatestResult(latest as unknown as Record<string, unknown>);
    expect(restored).not.toBeNull();
    if (restored == null) return;
    expect(restored.method).toBe("risk_parity");
    expect(restored.effective_start).toBe("2023-01-03");
    expect(restored.lookback).toBe(156);
    expect(restored.n_obs).toBe(3);
    expect(restored.nav).toEqual(latest.nav);
    expect(restored.annualized_return).toBeCloseTo(0.0821);
    expect(restored.max_drawdown).toBeCloseTo(-0.1355);
    expect(restored.sortino).toBeCloseTo(1.876);
    expect(restored.calmar).toBeCloseTo(0.606);
    expect(restored.turnover).toBeCloseTo(0.84);
    expect(restored.trading_days).toBe(244);
    expect(restored.fees?.fee_rate).toBeCloseTo(0.0003);
    expect(restored.weights).toHaveLength(2);
  });

  it("accepts service-side latest_result with extra fields", () => {
    const restored = backtestFromLatestResult({
      method: "risk_parity",
      effective_start: "2021-02-05",
      lookback_days: 156,
      rebalance_band: 0.05,
      risk_free: 0,
      n_obs: 2,
      trading_days: 244,
      annualized_return: 0.141,
      annualized_vol: 0.21,
      max_drawdown: -0.32,
      sharpe: 0.55,
      sortino: 0.7,
      calmar: 0.44,
      turnover: 0.4,
      fees: { fee_rate: 0.0003, slippage_rate: 0.001, stamp_duty_rate: 0.001 },
      weights: [],
      nav: [
        { trade_date: "2021-02-05", nav: 0.9987, ret: -0.0013 },
        { trade_date: "2021-02-08", nav: 1.002, ret: 0.0033 },
      ],
    });
    expect(restored?.annualized_return).toBeCloseTo(0.141);
    expect(restored?.sharpe).toBeCloseTo(0.55);
    expect(restored?.sortino).toBeCloseTo(0.7);
    expect(restored?.calmar).toBeCloseTo(0.44);
    expect(restored?.n_obs).toBe(2);
  });

  it("returns null when nav is missing or invalid (列表摘要 / 旧记录)", () => {
    expect(backtestFromLatestResult(null)).toBeNull();
    expect(backtestFromLatestResult(undefined)).toBeNull();
    expect(
      backtestFromLatestResult({ annualized_return: 0.1, max_drawdown: -0.2 }),
    ).toBeNull();
    expect(
      backtestFromLatestResult({
        nav: [{ trade_date: "2021-02-05", nav: 1 }],
      }),
    ).toBeNull();
    expect(
      backtestFromLatestResult({
        nav: [
          { trade_date: "2021-02-05", nav: 1 },
          { trade_date: "2021-02-08", nav: "bad" },
        ],
      }),
    ).toBeNull();
  });

  it("tolerates older records without Sortino/Calmar/fees", () => {
    const restored = backtestFromLatestResult({
      method: "equal_weight",
      effective_start: "2022-01-04",
      n_obs: 2,
      annualized_return: 0.05,
      max_drawdown: -0.1,
      sharpe: 0.8,
      turnover: 0.1,
      nav: [
        { trade_date: "2022-01-04", nav: 1, ret: 0 },
        { trade_date: "2022-01-05", nav: 1.01, ret: 0.01 },
      ],
    });
    expect(restored).not.toBeNull();
    expect(restored?.sortino).toBeNull();
    expect(restored?.calmar).toBeNull();
    expect(restored?.fees).toBeNull();
    expect(restored?.lookback).toBe(156);
    expect(restored?.n_obs).toBe(2);
  });
});

import { describe, expect, it } from "vitest";
import {
  backtestFromLatestResult,
  basketAssetHash,
  latestResultFromBacktest,
  latestResultParams,
  latestResultParamsMatch,
  paramsMatch,
  paramsSnapshotFromInput,
  type BasketParamsSnapshot,
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

  it("后端响应含等权净值 / 调仓事件时一并保留", () => {
    const latest = latestResultFromBacktest(
      backtest({
        equal_weight_nav: [
          { trade_date: "2023-01-03", nav: 1 },
          { trade_date: "2023-01-04", nav: 1.001 },
        ],
        rebalance_events: [
          {
            trade_date: "2023-01-04",
            reason: "偏离带",
            turnover: 0.12,
            max_deviation: 0.06,
            assets: [],
          },
        ],
      }),
      CONTEXT,
    );
    expect(latest.equal_weight_nav).toEqual([
      { trade_date: "2023-01-03", nav: 1 },
      { trade_date: "2023-01-04", nav: 1.001 },
    ]);
    expect(latest.rebalance_events).toHaveLength(1);
  });

  it("缺失时不为等权/调仓写空字段", () => {
    const latest = latestResultFromBacktest(backtest(), CONTEXT);
    expect(latest.equal_weight_nav).toBeUndefined();
    expect(latest.rebalance_events).toBeUndefined();
  });

  it("把结果参数快照与 nav 一起写入（供打开时比对）", () => {
    const latest = latestResultFromBacktest(backtest(), {
      ...CONTEXT,
      start: "2023-01-03",
      end: "2023-01-05",
    });
    expect(latest.params).toEqual({
      method: "risk_parity",
      lookback_days: 156,
      rebalance_band: 0.05,
      risk_free: 0.02,
      start: "2023-01-03",
      end: "2023-01-05",
      // 与后端 build_latest_result 同口径：60519/000300 按 symbol@source 升序后取 sha256 前 16 位。
      asset_hash: "5a0cb86ecfb7e31d",
    });
  });
});

describe("basketAssetHash（与后端 params.asset_hash 同口径）", () => {
  const ASSETS = [
    { symbol: "600519", source: "etl_a_stock" },
    { symbol: "000300", source: "cn_index_em" },
  ];

  it("symbol@source 升序换行连接后 sha256 前 16 位", () => {
    expect(basketAssetHash(ASSETS)).toBe("5a0cb86ecfb7e31d");
    // 输入顺序不影响指纹
    expect(basketAssetHash([...ASSETS].reverse())).toBe("5a0cb86ecfb7e31d");
  });

  it("空资产列表取空串 sha256 前 16 位", () => {
    expect(basketAssetHash([])).toBe("e3b0c44298fc1c14");
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

  it("还原等权净值 / 调仓事件；旧记录缺失时保持缺失（图例随之隐藏）", () => {
    const latest = latestResultFromBacktest(
      backtest({
        equal_weight_nav: [
          { trade_date: "2023-01-03", nav: 1 },
          { trade_date: "2023-01-04", nav: 1.001 },
        ],
        rebalance_events: [
          {
            trade_date: "2023-01-04",
            reason: "偏离带",
            turnover: 0.12,
            max_deviation: 0.06,
            assets: [],
          },
        ],
      }),
      CONTEXT,
    );
    const restored = backtestFromLatestResult(latest);
    expect(restored?.equal_weight_nav).toEqual(latest.equal_weight_nav);
    expect(restored?.rebalance_events).toHaveLength(1);

    const legacy = backtestFromLatestResult({
      method: "risk_parity",
      effective_start: "2023-01-03",
      nav: [
        { trade_date: "2023-01-03", nav: 1, ret: 0 },
        { trade_date: "2023-01-04", nav: 1.001, ret: 0.001 },
      ],
    });
    expect(legacy?.equal_weight_nav).toBeUndefined();
    expect(legacy?.rebalance_events).toEqual([]);
  });
});

describe("latest_result 参数绑定", () => {
  const ASSET_HASH = "5a0cb86ecfb7e31d";
  const CURRENT: BasketParamsSnapshot = {
    lookback_days: 156,
    rebalance_band: 0.05,
    risk_free: 0.02,
    start: null,
    end: null,
    method: "risk_parity",
    asset_hash: ASSET_HASH,
  };

  it("旧记录没有 params 时返回 null（调用方降级为旧行为）", () => {
    expect(latestResultParams(null)).toBeNull();
    expect(latestResultParams({ nav: [] })).toBeNull();
    expect(latestResultParams({ params: "bad" })).toBeNull();
    expect(latestResultParams({ params: [] })).toBeNull();
    expect(latestResultParams({ params: {} })).toBeNull();
    expect(latestResultParamsMatch({ nav: [] }, CURRENT)).toBeNull();
  });

  it("前端写入的 params 与当前表单匹配", () => {
    const latest = latestResultFromBacktest(backtest(), CONTEXT);
    expect(latestResultParamsMatch(latest, CURRENT)).toBe(true);
    expect(latestResultParamsMatch(latest, { ...CURRENT, lookback_days: 120 })).toBe(false);
  });

  it("方法与资产指纹变化也判为过期（后端 params 契约含 method/asset_hash）", () => {
    const latest = latestResultFromBacktest(backtest(), CONTEXT);
    expect(latestResultParamsMatch(latest, { ...CURRENT, method: "max_sharpe" })).toBe(false);
    expect(
      latestResultParamsMatch(latest, {
        ...CURRENT,
        asset_hash: "0000000000000000",
      }),
    ).toBe(false);
  });

  it("解析后端 build_latest_result 的 params 契约并可比对", () => {
    const raw = {
      nav: [],
      params: {
        method: "max_sharpe",
        lookback_days: 120,
        rebalance_band: 0.08,
        risk_free: 0.01,
        start: "2022-01-01",
        end: "2025-12-31",
        asset_hash: ASSET_HASH,
      },
    };
    expect(latestResultParams(raw)).toEqual({
      method: "max_sharpe",
      lookback_days: 120,
      rebalance_band: 0.08,
      risk_free: 0.01,
      start: "2022-01-01",
      end: "2025-12-31",
      asset_hash: ASSET_HASH,
    });
    const snapshot = paramsSnapshotFromInput({
      lookback_days: 120,
      rebalance_band: 0.08,
      risk_free: 0.01,
      start: "2022-01-01",
      end: "2025-12-31",
      method: "max_sharpe",
      // 与后端同口径：输入顺序已由排序归一化
      assets: [
        { symbol: "600519", source: "etl_a_stock" },
        { symbol: "000300", source: "cn_index_em" },
      ],
    });
    expect(snapshot.asset_hash).toBe(ASSET_HASH);
    expect(latestResultParamsMatch(raw, snapshot)).toBe(true);
  });

  it("回看窗口/再平衡带/无风险利率/日期变化均判为过期", () => {
    const latest = latestResultFromBacktest(backtest(), {
      ...CONTEXT,
      start: "2023-01-03",
      end: "2023-01-05",
    });
    const stored = latestResultParams(latest);
    expect(stored).not.toBeNull();
    if (!stored) return;
    const base: BasketParamsSnapshot = {
      ...CURRENT,
      start: "2023-01-03",
      end: "2023-01-05",
    };
    expect(paramsMatch(stored, base)).toBe(true);
    expect(paramsMatch(stored, { ...base, lookback_days: 120 })).toBe(false);
    expect(paramsMatch(stored, { ...base, rebalance_band: 0.08 })).toBe(false);
    expect(paramsMatch(stored, { ...base, risk_free: 0.03 })).toBe(false);
    expect(paramsMatch(stored, { ...base, start: "2022-01-03" })).toBe(false);
    expect(paramsMatch(stored, { ...base, end: null })).toBe(false);
  });

  it("后端只补数值参数（无日期）时不与表单默认区间误报", () => {
    const stored = latestResultParams({
      params: { lookback_days: 156, rebalance_band: 0.05, risk_free: 0 },
    });
    expect(stored).not.toBeNull();
    if (!stored) return;
    expect(
      paramsMatch(stored, {
        ...CURRENT,
        risk_free: 0,
        start: "2021-01-01",
        end: "2026-01-01",
      }),
    ).toBe(true);
  });

  it("paramsSnapshotFromInput 归一化 lookback/日期并计算资产指纹", () => {
    expect(
      paramsSnapshotFromInput({
        lookback_days: 155.6,
        rebalance_band: 0.05,
        risk_free: 0,
        start: "2023-01-03T00:00:00Z",
        end: "",
        method: "risk_parity",
        assets: [
          { symbol: "600519", source: "etl_a_stock" },
          { symbol: "000300", source: "cn_index_em" },
        ],
      }),
    ).toEqual({
      lookback_days: 156,
      rebalance_band: 0.05,
      risk_free: 0,
      start: "2023-01-03",
      end: null,
      method: "risk_parity",
      asset_hash: ASSET_HASH,
    });
  });

  it("还原结果时：params 匹配则写入 sig，不匹配则判过期（不置 sig）", () => {
    const latest = latestResultFromBacktest(backtest(), {
      ...CONTEXT,
      start: "2023-01-03",
      end: "2023-01-05",
    });
    const raw = latest as unknown as Record<string, unknown>;
    expect(
      latestResultParamsMatch(raw, {
        ...CURRENT,
        start: "2023-01-03",
        end: "2023-01-05",
      }),
    ).toBe(true);
    expect(
      latestResultParamsMatch(raw, {
        ...CURRENT,
        start: "2022-01-03",
        end: "2023-01-05",
      }),
    ).toBe(false);
  });
});

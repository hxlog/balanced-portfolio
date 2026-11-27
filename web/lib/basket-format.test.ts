import { describe, expect, it } from "vitest";
import {
  basketNavLegend,
  basketNavSeriesFlags,
  basketSkyColor,
  basketWeightRows,
  formatPct,
  formatRatio,
  formatSignedPct,
  normalizeRiskBudget,
} from "./basket-format";

describe("normalizeRiskBudget", () => {
  it("normalizes relative budgets to exactly 1", () => {
    const out = normalizeRiskBudget({ a: 1, b: 2, c: 1 });
    expect(out.a).toBeCloseTo(0.25, 12);
    expect(out.b).toBeCloseTo(0.5, 12);
    expect(out.c).toBeCloseTo(0.25, 12);
    expect(Object.values(out).reduce((s, v) => s + v, 0)).toBeCloseTo(1, 12);
  });

  it("falls back to equal weights when every value is zero/invalid", () => {
    const out = normalizeRiskBudget({ a: 0, b: -3, c: Number.NaN });
    expect(out.a).toBeCloseTo(1 / 3, 12);
    expect(out.b).toBeCloseTo(1 / 3, 12);
    expect(out.c).toBeCloseTo(1 / 3, 12);
  });

  it("ignores non-positive and non-finite values when others are valid", () => {
    const out = normalizeRiskBudget({ a: 2, b: 0, c: Number.POSITIVE_INFINITY });
    expect(out.a).toBe(1);
    expect(out.b).toBe(0);
    expect(out.c).toBe(0);
  });

  it("returns an empty map for empty input", () => {
    expect(normalizeRiskBudget({})).toEqual({});
  });
});

describe("basketWeightRows", () => {
  it("sorts descending, maps names and assigns deterministic sky colors", () => {
    const names = new Map([
      ["a@stock_sina", "甲"],
      ["b@etf_em", "乙"],
    ]);
    const rows = basketWeightRows(
      [
        { symbol: "a", source: "stock_sina", weight: 0.2 },
        { symbol: "b", source: "etf_em", weight: 0.8 },
        { symbol: "c", source: "etf_em", weight: 0 },
      ],
      names,
      false,
    );
    expect(rows.map((r) => r.symbol)).toEqual(["b", "a", "c"]);
    expect(rows[0].name).toBe("乙");
    expect(rows[1].name).toBe("甲");
    expect(rows[2].name).toBe("c");
    expect(rows[0].color).toBe(basketSkyColor(0, false));
    expect(rows[1].color).toBe(basketSkyColor(1, false));
  });

  it("clamps negative/non-finite weights to zero", () => {
    const rows = basketWeightRows(
      [
        { symbol: "a", source: "x", weight: -1 },
        { symbol: "b", source: "x", weight: Number.NaN },
      ],
      new Map(),
      true,
    );
    expect(rows.every((r) => r.weight === 0)).toBe(true);
  });
});

describe("number formatting", () => {
  it("formats percentages and avoids negative zero", () => {
    expect(formatPct(0.1234)).toBe("12.3%");
    expect(formatPct(-0.000001)).toBe("0.0%");
    expect(formatPct(Number.NaN)).toBe("—");
  });

  it("不再把 0.03%（3bp 费用/权重）误判成 0.00%", () => {
    // 入参是小数、展示时 ×100：阈值必须是 0.5*10^-(digits+2)，digits=2 时为 0.00005。
    expect(formatPct(0.0003, 2)).toBe("0.03%");
    expect(formatPct(-0.0003, 2)).toBe("-0.03%");
    expect(formatPct(0.00004, 2)).toBe("0.00%");
    expect(formatPct(0, 2)).toBe("0.00%");
  });

  it("formats signed percentages for directional metrics", () => {
    expect(formatSignedPct(0.05)).toBe("+5.0%");
    expect(formatSignedPct(-0.05)).toBe("-5.0%");
    expect(formatSignedPct(0)).toBe("0.0%");
  });

  it("formats ratios", () => {
    expect(formatRatio(1.234)).toBe("1.23");
    expect(formatRatio(null)).toBe("—");
  });
});

describe("basketNavSeriesFlags / basketNavLegend", () => {
  it("只承诺真实画出的等权/调仓系列（缺失即隐藏图例项）", () => {
    expect(basketNavSeriesFlags(null)).toEqual({ equalWeight: false, rebalance: false });
    expect(basketNavSeriesFlags({})).toEqual({ equalWeight: false, rebalance: false });
    expect(basketNavSeriesFlags({ equal_weight_nav: [], rebalance_events: [] })).toEqual({
      equalWeight: false,
      rebalance: false,
    });
    expect(basketNavLegend(undefined)).toEqual(["篮子净值"]);
    expect(basketNavLegend({ rebalance_events: [] })).toEqual(["篮子净值"]);
  });

  it("后端/还原结果带等权净值与调仓事件时图例才出现", () => {
    const flags = basketNavSeriesFlags({
      equal_weight_nav: [{ trade_date: "2024-01-02", nav: 1 }],
      rebalance_events: [{ trade_date: "2024-02-01" }],
    });
    expect(flags).toEqual({ equalWeight: true, rebalance: true });
    expect(
      basketNavLegend({
        equal_weight_nav: [{ trade_date: "2024-01-02", nav: 1 }],
        rebalance_events: [{ trade_date: "2024-02-01" }],
      }),
    ).toEqual(["篮子净值", "等权净值", "调仓"]);
    expect(
      basketNavLegend({ equal_weight_nav: [{ trade_date: "2024-01-02", nav: 1 }] }),
    ).toEqual(["篮子净值", "等权净值"]);
  });
});

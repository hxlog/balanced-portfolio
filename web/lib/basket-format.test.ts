import { describe, expect, it } from "vitest";
import {
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

import { describe, expect, it } from "vitest";
import {
  applyShares,
  computeFees,
  computeLines,
  computeTotals,
  defaultCurrentByPrev,
  lotRound,
  targetAmounts,
  type CalcRow,
} from "./rebalance-calc";

const rows: CalcRow[] = [
  { key: "A@x", name: "甲", symbol: "A", source: "x", category: "index", targetWeight: 0.5, prevWeight: 0.6 },
  { key: "B@x", name: "乙", symbol: "B", source: "x", category: "etf", targetWeight: 0.3, prevWeight: 0.4 },
  { key: "C@x", name: "丙", symbol: "C", source: "x", category: "etf", targetWeight: 0.2, prevWeight: 0 },
];

describe("defaultCurrentByPrev", () => {
  it("按上期权重 × 拟投资金额反推当前持仓", () => {
    const got = defaultCurrentByPrev(rows, 1_000_000);
    expect(got["A@x"]).toBe(600_000);
    expect(got["B@x"]).toBe(400_000);
    expect(got["C@x"]).toBe(0);
  });

  it("prevWeight 缺失时视为 0（新建仓行当前持仓为 0）", () => {
    const noPrev: CalcRow[] = [
      { key: "N@x", name: "新", symbol: "N", source: "x", targetWeight: 1, prevWeight: null },
    ];
    expect(defaultCurrentByPrev(noPrev, 1_000_000)["N@x"]).toBe(0);
  });

  it("金额非法时全部为 0", () => {
    const got = defaultCurrentByPrev(rows, Number.NaN);
    expect(Object.keys(got).sort()).toEqual(["A@x", "B@x", "C@x"]);
    expect(Object.values(got)).toEqual([0, 0, 0]);
  });
});

describe("targetAmounts", () => {
  it("最后一行吸收舍入残差, Σ 严格等于拟投资金额", () => {
    const uneven: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 1 / 3 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 1 / 3 },
      { key: "C", name: "丙", symbol: "C", source: "x", targetWeight: 1 / 3 },
    ];
    const got = targetAmounts(uneven, 1_000_000);
    const sum = got.A + got.B + got.C;
    expect(sum).toBe(1_000_000);
  });

  it("空行集返回空对象", () => {
    expect(targetAmounts([], 1_000_000)).toEqual({});
  });
});

describe("computeLines", () => {
  it("清仓行(计划 0)算出全额卖出 —— 修复原本永远显示 '—' 的缺陷", () => {
    const closeRows: CalcRow[] = [
      { key: "C@x", name: "丙", symbol: "C", source: "x", targetWeight: 0 },
    ];
    const lines = computeLines(closeRows, { "C@x": 59_300 }, { "C@x": 0 });
    expect(lines[0].sell).toBe(59_300);
    expect(lines[0].buy).toBe(0);
  });

  it("减仓行只算卖出, 加仓行只算买入", () => {
    const r: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.5 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 0.5 },
    ];
    const lines = computeLines(r, { A: 400_000, B: 700_000 }, { A: 500_000, B: 500_000 });
    expect([lines[0].buy, lines[0].sell]).toEqual([100_000, 0]);
    expect([lines[1].buy, lines[1].sell]).toEqual([0, 200_000]);
  });

  it("0 是合法金额(不再被当作未填)", () => {
    const r: CalcRow[] = [{ key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 1 }];
    const lines = computeLines(r, { A: 0 }, { A: 1_000_000 });
    expect(lines[0].buy).toBe(1_000_000);
  });
});

describe("applyShares", () => {
  it("仅 ETF 换算份额, 且按 100 份向下取整, 零头单列", () => {
    const r: CalcRow[] = [
      { key: "E@x", name: "ETF", symbol: "E", source: "x", category: "etf", targetWeight: 1 },
      { key: "I@x", name: "指数", symbol: "I", source: "x", category: "index", targetWeight: 0 },
    ];
    const lines = computeLines(r, { "E@x": 0, "I@x": 0 }, { "E@x": 50_000, "I@x": 0 });
    const out = applyShares(lines, r, { "E@x": 4.12, "I@x": 4000 });
    // 50000 / 4.12 = 12135.9 份 → 12100 份
    expect(out[0].buyShares).toBe(12_100);
    expect(out[0].buyRemainder).toBeCloseTo(50_000 - 12_100 * 4.12, 6);
    // 非 ETF 不换算
    expect(out[1].buyShares).toBeNull();
  });

  it("无价格时不换算, 不报错", () => {
    const r: CalcRow[] = [
      { key: "E@x", name: "ETF", symbol: "E", source: "x", category: "etf", targetWeight: 1 },
    ];
    const lines = computeLines(r, { "E@x": 0 }, { "E@x": 10_000 });
    const out = applyShares(lines, r, {});
    expect(out[0].buyShares).toBeNull();
    expect(out[0].buy).toBe(10_000);
  });
});

describe("computeTotals / computeFees", () => {
  it("总额与费用与手工计算一致", () => {
    const r: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.5 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 0.5 },
    ];
    const lines = computeLines(r, { A: 400_000, B: 700_000 }, { A: 500_000, B: 500_000 });
    const t = computeTotals(lines);
    expect(t.buyTotal).toBe(100_000);
    expect(t.sellTotal).toBe(200_000);
    expect(t.turnover).toBe(300_000);

    const f = computeFees(t.buyTotal, t.sellTotal, {
      feeRate: 0.00015,
      slippageRate: 0.00015,
      stampDutyRate: 0.0005,
    });
    expect(f.commission).toBeCloseTo(45, 6); // 300000 × 0.00015
    expect(f.slippage).toBeCloseTo(45, 6);
    expect(f.stampDuty).toBeCloseTo(100, 6); // 200000 × 0.0005
    expect(f.total).toBeCloseTo(190, 6);
  });
});

describe("审查修复回的边界(Task 6 复审 Minor)", () => {
  it("targetAmounts: ΣtargetWeight > 1 时仍不超发(权重重归一)", () => {
    const over: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.6 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 0.6 },
      { key: "C", name: "丙", symbol: "C", source: "x", targetWeight: 0 },
    ];
    const got = targetAmounts(over, 1_000_000);
    expect(got.A + got.B + got.C).toBe(1_000_000);
    // 归一后 A、B 各得一半, 而不是各拿 600,000
    expect(got.A).toBe(500_000);
    expect(got.B).toBe(500_000);
  });

  it("lotRound: 零头永不为负(toFixed(2) 不会出现 '-0.00')", () => {
    const r = lotRound(3_300, 1.1);
    expect(r.remainder).toBeGreaterThanOrEqual(0);
    expect(r.remainder.toFixed(2)).not.toBe("-0.00");
  });

  it("computeFees: 负费率被钳到 0(与后端 backtest.py 同口径)", () => {
    const f = computeFees(100_000, 100_000, {
      feeRate: -0.001,
      slippageRate: -0.001,
      stampDutyRate: -0.001,
    });
    expect(f.commission).toBe(0);
    expect(f.slippage).toBe(0);
    expect(f.stampDuty).toBe(0);
    expect(f.total).toBe(0);
  });
});

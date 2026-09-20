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
  it("Σ 严格等于拟投资金额(残差补给权重最大的行)", () => {
    const uneven: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 1 / 3 },
      { key: "B", name: "乙", symbol: "B", source: "x", targetWeight: 1 / 3 },
      { key: "C", name: "丙", symbol: "C", source: "x", targetWeight: 1 / 3 },
    ];
    const got = targetAmounts(uneven, 1_000_000);
    const sum = got.A + got.B + got.C;
    expect(sum).toBe(1_000_000);
    // 残差 +1 落在并列最大权重的首行(A), 而不是行集最后一行(C)
    expect(got.A).toBe(333_334);
    expect(got.C).toBe(333_333);
  });

  it("空行集返回空对象", () => {
    expect(targetAmounts([], 1_000_000)).toEqual({});
  });

  it("清仓行排在最后时不会分到残差 —— 真实事故 2024-09-30(e2e 回归)", () => {
    // 调仓变动表按 |Δ| 升序排, 清仓行 |Δ| = 上期权重, 落于末尾。
    // 老实现把残差给「最后一行」, 于是给目标权重为 0 的 000510 分到 ¥204 →
    // 该行当前持仓 = 0.0877% × 100 万 = ¥877, 差额算出「卖出 673」,
    // 而正确答案是清仓卖出 877, 少卖 ¥204(该笔的 23%)。
    const rows: CalcRow[] = [
      { key: "518880@etf_em", name: "黄金", symbol: "518880", source: "etf_em", targetWeight: 0.134123, prevWeight: 0.166571 },
      { key: "511090@etf_em", name: "国债", symbol: "511090", source: "etf_em", targetWeight: 0.128018, prevWeight: 0.134506 },
      { key: "511260@etf_em", name: "十年国债", symbol: "511260", source: "etf_em", targetWeight: 0.128018, prevWeight: 0.134447 },
      { key: "000510@cn_index_em", name: "中证A500", symbol: "000510", source: "cn_index_em", targetWeight: 0, prevWeight: 0.000877 },
    ];
    const got = targetAmounts(rows, 1_000_000);
    // 清仓行拿到的计划额必须是 0(目标权重为 0), 而不是被残差塞进去的正数
    expect(got["000510@cn_index_em"]).toBe(0);
    // Σ计划 = round(Σ权重 × 金额) —— Σ权重 < 1 时不放大, 未分配的权重属于表外标的
    const sumW = 0.134123 + 0.128018 + 0.128018 + 0;
    expect(Object.values(got).reduce((s, x) => s + x, 0)).toBe(Math.round(sumW * 1_000_000));
    // 该行的买卖: 当前持仓 ¥877, 计划 0 → 全额卖出(旧实现只能卖出 673)
    const lines = computeLines(rows, { "000510@cn_index_em": 877 }, got);
    const close = lines.find((l) => l.key === "000510@cn_index_em")!;
    expect(close.sell).toBe(877);
    expect(close.buy).toBe(0);
  });

  it("Σ权重 < 1 时不摊派未分配权重给任何一行", () => {
    // 真实调用路径里被保留的行几乎总是 Σ≈1(仅噪声行被 ZERO_EPS 归零),
    // 但纯函数契约必须对任意输入成立: 12 行各 7% + 末行 3.12% → Σ=0.8712
    const rows: CalcRow[] = [
      ...Array.from({ length: 12 }, (_, i) => ({
        key: `r${i}`, name: `r${i}`, symbol: `r${i}`, source: "x", targetWeight: 0.07,
      })),
      { key: "LAST", name: "末", symbol: "LAST", source: "x", targetWeight: 0.0312 },
    ];
    const got = targetAmounts(rows, 1_000_000);
    // 首行严格等于 70,000(不因残差被放大), 末行严格等于 31,200
    expect(got.r0).toBe(70_000);
    expect(got.LAST).toBe(31_200);
    expect(Object.values(got).reduce((s, x) => s + x, 0)).toBe(871_200);
  });

  it("单行行集按自身权重的 1/Σ 缩放(调用方传了未归一的权重)", () => {
    // Σ=0.12 < 1 → 不缩放: 该行拿 round(0.12×100万)=120,000, 不是整额
    const one: CalcRow[] = [
      { key: "A", name: "甲", symbol: "A", source: "x", targetWeight: 0.12 },
    ];
    expect(targetAmounts(one, 1_000_000).A).toBe(120_000);
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
